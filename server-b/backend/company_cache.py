"""
公司信息缓存与解析：
- 作用：根据「公司名称 + 市场」解析出标准股票代码，并在本地缓存，避免每次都调大模型。
- 缓存层：Redis（优先） + backend/company_cache.json（兜底）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from openai import OpenAI

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    REDIS_ENABLED,
)
from .redis_cache import (
    get_company_cache,
    set_company_cache,
)

_BACKEND_DIR = Path(__file__).resolve().parent
_CACHE_PATH = _BACKEND_DIR / "company_cache.json"


class CompanyInfo(TypedDict, total=False):
    company_name: str
    market: str
    symbol: str
    official_name: str
    source: str  # cache / llm / redis


_CACHE: dict[str, CompanyInfo] | None = None


def _normalize_key(company_name: str, market: str) -> str:
    return f"{market.strip().lower()}::{company_name.strip().lower()}"


def _load_cache() -> dict[str, CompanyInfo]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not _CACHE_PATH.exists():
        _CACHE = {}
        return _CACHE
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            _CACHE = {str(k): v for k, v in data.items()}
    except Exception:
        _CACHE = {}
    return _CACHE


def _normalize_resolved_symbol(symbol: str, market: str) -> str:
    """规范化 LLM 返回的 symbol，使之符合价格接口要求。"""
    s = (symbol or "").strip()
    if not s:
        return ""
    m = market.lower()
    if m == "cn":
        # A股：6位数字，去除可能的点/空格
        digits = "".join(c for c in s if c.isdigit())
        if len(digits) >= 4:
            return digits.zfill(6)
        return s
    if m == "hk":
        # 港股：纯数字补4位加.HK，或已是 XXXX.HK
        if s.upper().endswith(".HK"):
            code = s.upper().replace(".HK", "").lstrip("0") or "0"
            return f"{code.zfill(4)}.HK"
        digits = "".join(c for c in s if c.isdigit())
        if digits:
            return f"{(digits.lstrip('0') or '0').zfill(4)}.HK"
        return s
    # 美股：转大写
    return s.upper()


def _save_cache() -> None:
    if _CACHE is None:
        return
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        # 缓存写入失败不影响主流程
        pass


def _resolve_via_llm(company_name: str, market: str) -> CompanyInfo | None:
    """调用 DeepSeek 解析公司 -> 股票代码，仅在缓存缺失时触发。"""
    if not DEEPSEEK_API_KEY:
        return None

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    market_label = {
        "hk": "港股",
        "us": "美股",
        "cn": "A股",
    }.get(market.lower(), "美股" if market.lower() == "auto" else market)

    system_prompt = (
        "你是一名证券分析师助手，负责把公司名称映射到证券交易所的股票代码。\n"
        "支持港股、美股、A股三大市场中的任意已上市公司。\n"
        "只输出 JSON，不要任何解释或多余文字。\n"
        "重要：当公司多市场上市时，优先级为 美股 > 港股 > A股。\n"
        "股票代码格式：A股为6位数字(上海60xxxx/深圳00xxxx或30xxxx)，港股为4位数字或XXXX.HK，美股为标准ticker(如AAPL)。"
    )
    user_prompt = f"""
请根据以下信息，返回该公司的主交易代码（支持简称、英文名、繁简体）：
- 公司名称：{company_name}
- 所在市场：{market.lower()}（cn=A股, hk=港股, us=美股，auto=自动识别时按美股>港股>A股优先级选择）

若该公司在任一市场上市，请按对应格式返回；若未找到或未上市，symbol 留空字符串。

请严格按照下面 JSON 结构输出（不要加反引号、不要加多余文字）：
{{
  "company_name": "原始公司名",
  "market": "cn/hk/us 之一",
  "symbol": "股票代码：A股6位如600519/000001，港股如0700.HK或700，美股如AAPL",
  "official_name": "该市场的官方公司名称（如有）"
}}
"""

    try:
        completion = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            temperature=0.1,
            max_tokens=256,
        )
        content = completion.choices[0].message.content or ""
        # 尝试从返回文本中提取 JSON
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        obj = json.loads(content[start : end + 1])
        symbol = (obj.get("symbol") or "").strip()
        if not symbol:
            return None
        raw_market = (obj.get("market") or market).strip().lower()
        # 确保 market 为 cn/hk/us 之一
        if raw_market not in ("cn", "hk", "us"):
            raw_market = "us" if raw_market == "auto" else "hk"
        symbol = _normalize_resolved_symbol(symbol, raw_market)
        if not symbol:
            return None
        info: CompanyInfo = {
            "company_name": obj.get("company_name") or company_name,
            "market": raw_market,
            "symbol": symbol,
            "official_name": obj.get("official_name") or company_name,
            "source": "llm",
        }
        return info
    except Exception:
        return None


def resolve_company(company_name: str, market: str) -> CompanyInfo | None:
    """
    行业化方案：
    - 优先查 Redis 缓存
    - 再查本地 JSON 缓存
    - 未命中时调用 DeepSeek 做一次解析，并同时写入两层缓存
    """
    key = _normalize_key(company_name, market)

    # 第一层：Redis 缓存
    if REDIS_ENABLED:
        cached = get_company_cache(company_name, market)
        if cached:
            return cached

    # 第二层：本地 JSON 缓存
    cache = _load_cache()
    if key in cache:
        info = cache[key].copy()
        info["source"] = "cache"
        # 回写 Redis
        if REDIS_ENABLED:
            set_company_cache(company_name, market, info)
        return info

    # LLM 解析
    info = _resolve_via_llm(company_name, market)
    if not info:
        return None

    # 同时写入两层缓存
    if REDIS_ENABLED:
        set_company_cache(company_name, market, info)
    cache[key] = info
    _save_cache()

    # 命中方也统一标记来源
    info = info.copy()
    info["source"] = "llm"
    return info
