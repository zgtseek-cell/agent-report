"""
股票价格查询服务（参考 API_DOC.md）：
- 拆分模式：
  * A股：本地 akshare（Server B 国内）
  * 港/美股：调用 Server A（新加坡）yfinance
- 缓存层：Redis（统一缓存）+ SQLite（兜底）
- 自动判断交易日：非交易日使用上一交易日；获取失败时依次向前尝试最多 3 次
"""

import os
import json
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import httpx
import yfinance as yf

# Server A 代理配置：支持两种模式
# 1) 端口代理：A 开启 PROXY_PORT，B 设 USE_HTTP_PROXY=true + SERVER_A_PROXY_PORT，外网经 A 的端口代理
# 2) API 代理：B 通过 /api/proxy/extern 逐请求转发（需 monkey-patch urlopen）
from .config import (
    SERVER_A_HOST,
    SERVER_A_PORT,
    SERVER_A_BASE_URL,
    SERVER_A_API_TOKEN,
    USE_HTTP_PROXY,
    SERVER_A_PROXY_PORT,
)

# 端口代理模式：设置 HTTP_PROXY/HTTPS_PROXY，yfinance 直连 A 的代理端口，无需 patch
if USE_HTTP_PROXY and SERVER_A_PROXY_PORT > 0:
    from urllib.parse import quote
    if SERVER_A_API_TOKEN:
        # Proxy-Authorization: Basic base64(user:pass)，user 填 token、password 留空
        _proxy_url = f"http://{quote(SERVER_A_API_TOKEN, safe='')}:@{SERVER_A_HOST}:{SERVER_A_PROXY_PORT}"
    else:
        _proxy_url = f"http://{SERVER_A_HOST}:{SERVER_A_PROXY_PORT}"
    os.environ.setdefault("HTTP_PROXY", _proxy_url)
    os.environ.setdefault("HTTPS_PROXY", _proxy_url)
else:
    # API 代理模式：重定向 urlopen 到 Server A 的 /api/proxy/extern（A 鉴权用 Query token）
    _proxy_base = os.getenv("SERVER_A_PROXY_URL", "") or (
        (SERVER_A_BASE_URL or f"http://{SERVER_A_HOST}:{SERVER_A_PORT}") + "/api/proxy/extern"
    )
    SERVER_A_PROXY_URL = _proxy_base + (
        f"?token={urllib.parse.quote(SERVER_A_API_TOKEN, safe='')}" if SERVER_A_API_TOKEN else ""
    )

    def proxied_urlopen(req: Request, *args, **kwargs):
        """使 yfinance 的网络请求通过 Server A 的 /api/proxy/extern 转发"""
        url = req.get_full_url()
        method = req.get_method()
        headers = dict(req.header_items())
        data = getattr(req, "data", None)
        proxy_request = {
            "url": url,
            "method": method,
            "headers": headers,
            "params": {},
            "data": {},
            "json": {},
        }
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if query_params:
            proxy_request["params"] = {k: v[0] for k, v in query_params.items()}
        if data:
            data_str = data.decode("utf-8") if isinstance(data, bytes) else str(data)
            try:
                proxy_request["data"] = {k: v[0] for k, v in urllib.parse.parse_qs(data_str).items()}
            except Exception:
                try:
                    proxy_request["json"] = json.loads(data_str)
                except Exception:
                    proxy_request["data"] = data_str
        try:
            proxy_headers = {"Content-Type": "application/json"}
            if SERVER_A_API_TOKEN:
                proxy_headers["Authorization"] = f"Bearer {SERVER_A_API_TOKEN}"
            response = httpx.post(
                SERVER_A_PROXY_URL,
                json=proxy_request,
                headers=proxy_headers,
                timeout=int(os.getenv("PROXY_TIMEOUT", "30")),
            )
            if response.status_code != 200:
                raise HTTPError(
                    url, response.status_code, f"Proxy request failed: {response.text}",
                    response.headers, None,
                )
            r = response.json()

            class MockHTTPResponse:
                def __init__(self, data: bytes, status: int, headers: Dict[str, str]):
                    self.data, self.status, self.headers = data, status, headers
                    self.code, self.msg = status, ""

                def read(self):
                    return self.data

                def info(self):
                    class H:
                        def __init__(self, h): self._h = h
                        def getheader(self, name, default=None): return self._h.get(name, default)
                        def __getitem__(self, name): return self._h[name]
                        def get(self, name, default=None): return self._h.get(name, default)
                    return H(self.headers)

                def getcode(self): return self.code
                def close(self): pass

            return MockHTTPResponse(
                r.get("content", "").encode("utf-8"),
                r.get("status_code", 200),
                r.get("headers", {}),
            )
        except Exception as e:
            raise URLError(f"Proxy request failed: {str(e)}")

    import urllib.request
    urllib.request.urlopen = proxied_urlopen

from .config import (
    AKSHARE_ADJUST,
    DEBUG_LOG_PATH,
    PRICE_CACHE_DB_PATH,
    PRICE_API_BASE_URL,
    PRICE_API_ENABLED,
    PRICE_API_HOST,
    PRICE_API_PORT,
    PRICE_SPLIT_ENABLED,
    REDIS_ENABLED,
    OVERSEA_PRICE_API_ENABLED,
    OVERSEA_PRICE_API_HOST,
    OVERSEA_PRICE_API_PORT,
    OVERSEA_PRICE_API_BASE_URL,
    PROXY_TIMEOUT,
)
from .redis_cache import (
    get_price_cache,
    set_price_cache,
)

# 市场别名 -> 标准值
MARKET_ALIAS = {
    "cn": "cn",
    "a": "cn",
    "china": "cn",
    "hk": "hk",
    "hongkong": "hk",
    "us": "us",
    "usa": "us",
}


# region agent log helper (debug session 986d0a)
def _agent_price_debug(message: str, data: dict | None = None, hypothesis_id: str = "P?") -> None:
    """价格链路调试日志：写入 .cursor/debug-986d0a.log（NDJSON）"""
    try:
        import time as _time
        import json as _json
        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug-986d0a.log"
        payload = {
            "sessionId": "986d0a",
            "runId": "pre-fix-1",
            "hypothesisId": hypothesis_id,
            "location": "backend/price.py",
            "message": message,
            "data": data or {},
            "timestamp": int(_time.time() * 1000),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # 调试日志失败不能影响主流程
        pass
# endregion


def _debug_log_price(message: str, data: dict | None = None, hypothesis_id: str = "P?") -> None:
    """价格模块专用 debug 日志（写入同一 NDJSON 文件）"""
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": "backend/price.py",
            "message": message,
            "data": data or {},
            "timestamp": __import__("time").time(),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            import json as _json

            f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # 调试日志失败不影响主流程
        pass


def _normalize_market(market: str) -> str | None:
    m = (market or "").strip().lower()
    return MARKET_ALIAS.get(m) or (m if m in ("cn", "hk", "us") else None)


def _normalize_symbol(symbol: str, market: str) -> str:
    """标准化股票代码：A股补足6位，港股转 XXXX.HK"""
    s = (symbol or "").strip()
    if not s:
        return s
    m = _normalize_market(market) or market.lower()
    if m == "cn":
        return s.zfill(6) if s.isdigit() else s
    if m == "hk":
        # 根据 API_DOC：调用方可传 700 或 0700.HK
        # 这里对纯数字先去掉多余前导 0，再填充为 4 位，再统一加 .HK
        if s.isdigit():
            digits = s.lstrip("0") or "0"
            padded = digits.zfill(4)
            return f"{padded}.HK"
        if s.upper().endswith(".HK"):
            # 若已带 .HK，则只规范大小写 + 位数（最多保留 4 位主代码）
            code = s.upper().replace(".HK", "")
            digits = code.lstrip("0") or "0"
            padded = digits.zfill(4)
            return f"{padded}.HK"
        # 其它情况按纯数字处理尝试标准化
        digits = "".join(ch for ch in s if ch.isdigit())
        digits = digits.lstrip("0") or "0"
        padded = digits.zfill(4)
        return f"{padded}.HK"
    return s.upper()


# A股交易日历缓存
_CN_TRADE_DATES: list[str] | None = None


def _load_cn_trade_dates() -> list[str]:
    """加载 A股交易日历（akshare），返回 YYYY-MM-DD 格式的日期列表（升序）"""
    global _CN_TRADE_DATES
    if _CN_TRADE_DATES is not None:
        return _CN_TRADE_DATES
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        out = []
        for v in df[col].astype(str).tolist():
            v = v.strip()
            if "-" in v:
                out.append(v[:10])
            elif len(v) == 8 and v.isdigit():
                out.append(f"{v[:4]}-{v[4:6]}-{v[6:8]}")
        dates = [d for d in out if len(d) >= 10]
        _CN_TRADE_DATES = sorted(set(dates))
    except Exception:
        _CN_TRADE_DATES = []
    return _CN_TRADE_DATES


def _parse_date(s: str) -> datetime | None:
    """解析 YYYY-MM-DD 或 YYYYMMDD 为 datetime"""
    s = (s or "").strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _is_trade_day(market: str, date_str: str) -> bool:
    """判断指定日期是否为交易日"""
    m = _normalize_market(market)
    if not m or m not in ("cn", "hk", "us"):
        return True
    dt = _parse_date(date_str)
    if not dt:
        return False
    ds = _fmt_date(dt)
    if m == "cn":
        return ds in _load_cn_trade_dates()
    # 港股、美股：周六日非交易日
    return dt.weekday() < 5  # 0-4 = Mon-Fri


def _get_prev_trade_day(market: str, date_str: str) -> str | None:
    """获取指定日期的上一交易日，返回 YYYY-MM-DD"""
    m = _normalize_market(market)
    if not m or m not in ("cn", "hk", "us"):
        return None
    dt = _parse_date(date_str)
    if not dt:
        return None
    if m == "cn":
        dates = _load_cn_trade_dates()
        if not dates:
            dt = dt - timedelta(days=1)
            return _fmt_date(dt)
        ds = _fmt_date(dt)
        if ds in dates:
            idx = dates.index(ds)
            if idx > 0:
                return dates[idx - 1]
        # 当前日期不在日历中，向前找到最近交易日
        for i in range(1, 30):
            prev = dt - timedelta(days=i)
            ps = _fmt_date(prev)
            if ps in dates:
                return ps
        return _fmt_date(dt - timedelta(days=1))
    # 港股、美股：按日向前，跳过周末
    for i in range(1, 10):
        prev = dt - timedelta(days=i)
        if prev.weekday() < 5:
            return _fmt_date(prev)
    return _fmt_date(dt - timedelta(days=1))


def _get_effective_trade_date(market: str) -> str:
    """获取用于查询的有效交易日：当天是交易日则用当天，否则用上一交易日"""
    today = _fmt_date(datetime.now())
    if _is_trade_day(market, today):
        return today
    prev = _get_prev_trade_day(market, today)
    return prev or today


def _init_cache_db() -> None:
    Path(PRICE_CACHE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PRICE_CACHE_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_cache (
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT,
                source TEXT,
                PRIMARY KEY (market, symbol, trade_date)
            )
        """)


def _get_from_cache(market: str, symbol: str, trade_date: str) -> dict | None:
    """优先从 Redis 获取，Redis 不可用时从 SQLite 获取"""
    # 先试 Redis
    if REDIS_ENABLED:
        cached = get_price_cache(market, symbol, trade_date)
        if cached:
            return cached
    # 再试 SQLite
    with sqlite3.connect(PRICE_CACHE_DB_PATH) as conn:
        row = conn.execute(
            "SELECT price, currency, source FROM price_cache WHERE market=? AND symbol=? AND trade_date=?",
            (market, symbol, trade_date),
        ).fetchone()
    if row:
        return {"price": row[0], "currency": row[1] or "CNY", "source": row[2] or "cache"}
    return None


def _save_to_cache(market: str, symbol: str, trade_date: str, price: float, currency: str, source: str) -> None:
    """同时写入 Redis 和 SQLite"""
    data = {"price": price, "currency": currency, "source": source}
    if REDIS_ENABLED:
        set_price_cache(market, symbol, trade_date, data)
    with sqlite3.connect(PRICE_CACHE_DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_cache (market, symbol, trade_date, price, currency, source) VALUES (?,?,?,?,?,?)",
            (market, symbol, trade_date, price, currency, source),
        )


def _get_price_api_url() -> str:
    """获取旧价格接口 base URL（兼容）"""
    if PRICE_API_BASE_URL:
        return PRICE_API_BASE_URL.rstrip("/")
    return f"http://{PRICE_API_HOST}:{PRICE_API_PORT}"


def _get_oversea_price_api_url() -> str:
    """获取海外价格接口 base URL（Server A）"""
    if OVERSEA_PRICE_API_BASE_URL:
        return OVERSEA_PRICE_API_BASE_URL.rstrip("/")
    return f"http://{OVERSEA_PRICE_API_HOST}:{OVERSEA_PRICE_API_PORT}"


def _fetch_from_remote_api(market: str, symbol: str, trade_date: str) -> dict | None:
    """从旧价格接口请求（兼容）"""
    url = f"{_get_price_api_url()}/api/price"
    params = {"market": market, "symbol": symbol, "trade_date": trade_date}
    try:
        _debug_log_price(
            "call_remote_price_api",
            {"url": url, "params": params},
            hypothesis_id="P1",
        )
        with httpx.Client(timeout=10) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                if data.get("price") is not None and data.get("price", 0) > 0:
                    _debug_log_price(
                        "remote_price_api_success",
                        {
                            "url": url,
                            "status_code": r.status_code,
                            "price": data.get("price"),
                            "currency": data.get("currency", "CNY"),
                        },
                        hypothesis_id="P1",
                    )
                    return {
                        "price": float(data["price"]),
                        "currency": data.get("currency", "CNY"),
                        "source": data.get("source", "remote"),
                    }
            else:
                _debug_log_price(
                    "remote_price_api_non_200",
                    {
                        "url": url,
                        "status_code": r.status_code,
                        "body": r.text[:200],
                    },
                    hypothesis_id="P1",
                )
    except Exception as e:
        _debug_log_price(
            "remote_price_api_exception",
            {"url": url, "error": str(e)},
            hypothesis_id="P1",
        )
        pass
    return None


def _fetch_from_oversea_api(market: str, symbol: str, trade_date: str) -> dict | None:
    """
    从海外价格接口请求（Server A 新加坡 - 港/美股）。
    成功返回 {"price", "currency", "source"}，失败返回 {"error": "具体原因"} 便于上层展示。
    """
    # 使用 Server A 的通用代理接口（A 鉴权用 Query token，故 token 放 URL）
    base = _get_oversea_price_api_url()
    api_token = os.getenv("SERVER_A_API_TOKEN", "")
    url = f"{base}/api/proxy/extern"
    if api_token:
        url = f"{url}?token={urllib.parse.quote(api_token, safe='')}"

    # 构建 yfinance 查询 URL
    yfinance_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{_normalize_symbol(symbol, market)}"

    # 计算日期范围
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_date = int(dt.timestamp())
    end_date = int((dt + timedelta(days=1)).timestamp())

    # 构建代理请求
    proxy_request = {
        "url": yfinance_url,
        "method": "GET",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        "params": {
            "period1": str(start_date),
            "period2": str(end_date),
            "interval": "1d"
        },
        "data": {},
        "json": {}
    }

    def _fail(reason: str) -> dict:
        return {"error": reason}

    try:
        _debug_log_price(
            "call_oversea_price_api",
            {"url": url, "yfinance_url": yfinance_url},
            hypothesis_id="P1",
        )
        # 单次请求超时由 PROXY_TIMEOUT 控制（默认 30s），慢网络可在 .env 调大
        with httpx.Client(timeout=PROXY_TIMEOUT, follow_redirects=True) as client:
            # 最多重试 3 次
            last_reason = ""
            for attempt in range(3):
                try:
                    # 发送代理请求（鉴权已通过 URL query token 传递）
                    headers = {"Content-Type": "application/json"}
                    r = client.post(url, json=proxy_request, headers=headers)
                    print(f"Proxy request response: status={r.status_code}, body={r.text}")

                    if r.status_code != 200:
                        last_reason = f"代理 HTTP {r.status_code}: {r.text[:150]}"
                        print(f"Proxy request failed with status: {r.status_code}")
                        _debug_log_price(
                            "oversea_price_api_non_200",
                            {
                                "url": url,
                                "status_code": r.status_code,
                                "body": r.text[:200],
                            },
                            hypothesis_id="P1",
                        )
                        continue
                    proxy_response = r.json()
                    print(f"Proxy response: {json.dumps(proxy_response, indent=2)}")
                    if proxy_response.get("status_code") != 200:
                        last_reason = f"上游 Yahoo 返回 {proxy_response.get('status_code')}"
                        continue
                    # 解析 yfinance 响应
                    try:
                        yfinance_data = json.loads(proxy_response["content"])
                        if "chart" in yfinance_data and "result" in yfinance_data["chart"]:
                            result = yfinance_data["chart"]["result"][0]
                            if "meta" in result and "regularMarketPrice" in result["meta"]:
                                price = float(result["meta"]["regularMarketPrice"])
                                currency = "HKD" if market == "hk" else "USD"
                                _debug_log_price(
                                    "oversea_price_api_success",
                                    {
                                        "url": url,
                                        "status_code": r.status_code,
                                        "price": price,
                                        "currency": currency,
                                    },
                                    hypothesis_id="P1",
                                )
                                return {
                                    "price": price,
                                    "currency": currency,
                                    "source": "server_a_proxy",
                                }
                        last_reason = "Yahoo 响应无 chart.result 或 meta.regularMarketPrice"
                    except Exception as e:
                        last_reason = f"解析 Yahoo 响应失败: {e}"
                        print(f"Error parsing yfinance data: {str(e)}")
                        _debug_log_price(
                            "oversea_price_api_parse_error",
                            {"error": str(e)},
                            hypothesis_id="P1",
                        )
                except Exception as e:
                    last_reason = str(e)
                    _debug_log_price(
                        "oversea_price_api_retry",
                        {"url": url, "attempt": attempt + 1, "error": str(e)},
                        hypothesis_id="P1",
                    )
                    if attempt < 2:
                        import time
                        time.sleep(1)  # 等待 1 秒后重试
            return _fail(last_reason or "代理请求多次重试后仍失败")
    except Exception as e:
        _debug_log_price(
            "oversea_price_api_exception",
            {"url": url, "error": str(e)},
            hypothesis_id="P1",
        )
        return _fail(str(e))


def _fetch_cn_price(symbol: str, trade_date: str) -> tuple[float | None, str, str]:
    """A股：akshare，返回 (price, currency, source)"""
    try:
        import akshare as ak
    except ImportError:
        return None, "CNY", "akshare"
    sym = symbol.zfill(6) if symbol.isdigit() else symbol
    dt = trade_date.replace("-", "")
    try:
        df = ak.stock_zh_a_hist(
            symbol=sym,
            period="daily",
            start_date=dt,
            end_date=dt,
            adjust=AKSHARE_ADJUST,
        )
        if df is not None and not df.empty and "收盘" in df.columns:
            return float(df["收盘"].iloc[0]), "CNY", "akshare"
    except Exception:
        pass
    return None, "CNY", "akshare"


def _fetch_hk_us_price(symbol: str, trade_date: str, market: str) -> tuple[float | None, str, str]:
    """港/美股：yfinance 本地（兜底），返回 (price, currency, source)"""
    sym = symbol
    if market == "hk":
        # 与 _normalize_symbol 规则保持一致：去掉多余前导 0，规范为 XXXX.HK
        if symbol.isdigit():
            digits = symbol.lstrip("0") or "0"
            padded = digits.zfill(4)
            sym = f"{padded}.HK"
        elif not symbol.upper().endswith(".HK"):
            digits = "".join(ch for ch in symbol if ch.isdigit())
            digits = digits.lstrip("0") or "0"
            padded = digits.zfill(4)
            sym = f"{padded}.HK"
    try:
        tk = yf.Ticker(sym)
        hist = tk.history(start=trade_date, end=trade_date)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            price = float(hist["Close"].iloc[0])
            currency = "HKD" if market == "hk" else "USD"
            return price, currency, "yfinance"
    except Exception:
        pass
    return None, "HKD" if market == "hk" else "USD", "yfinance"


def fetch_single_price(market: str, symbol: str, trade_date: str) -> dict:
    """
    查询单条价格，优先缓存。
    拆分模式：
      - A股：本地 akshare
      - 港/美股：Server A 海外接口
    返回：{market, symbol, date, price, currency, source, cached, error?}
    """
    _init_cache_db()
    _agent_price_debug(
        "fetch_single_price_enter",
        {
            "market": market,
            "symbol": symbol,
            "trade_date": trade_date,
            "PRICE_SPLIT_ENABLED": PRICE_SPLIT_ENABLED,
        },
        "P2",
    )
    _debug_log_price(
        "fetch_single_price_called",
        {
            "market": market,
            "symbol": symbol,
            "trade_date": trade_date,
            "PRICE_SPLIT_ENABLED": PRICE_SPLIT_ENABLED,
            "REDIS_ENABLED": REDIS_ENABLED,
        },
        hypothesis_id="P2",
    )
    m = _normalize_market(market)
    if not m or m not in ("cn", "hk", "us"):
        return {
            "market": market,
            "symbol": symbol,
            "date": trade_date,
            "price": 0.0,
            "currency": "CNY",
            "source": "",
            "cached": False,
            "error": "不支持的 market，需为 cn/hk/us",
        }
    if not symbol or not trade_date:
        return {
            "market": m,
            "symbol": symbol or "",
            "date": trade_date or "",
            "price": 0.0,
            "currency": "CNY",
            "source": "",
            "cached": False,
            "error": "symbol 和 trade_date 不能为空",
        }
    norm_sym = _normalize_symbol(symbol, m)

    # 优先查缓存（Redis + SQLite）
    cached = _get_from_cache(m, norm_sym, trade_date)
    if cached:
        _debug_log_price(
            "price_cache_hit",
            {"market": m, "symbol": norm_sym, "trade_date": trade_date},
            hypothesis_id="P2",
        )
        _agent_price_debug(
            "price_cache_hit",
            {"market": m, "symbol": norm_sym, "trade_date": trade_date},
            "P2",
        )
        return {
            "market": m,
            "symbol": norm_sym,
            "date": trade_date,
            "price": cached["price"],
            "currency": cached["currency"],
            "source": cached["source"],
            "cached": True,
            "error": None,
        }

    # ========== 拆分模式路由 ==========
    if PRICE_SPLIT_ENABLED:
        if m == "cn":
            # A股：本地 akshare
            price, currency, source = _fetch_cn_price(norm_sym, trade_date)
            if price is not None:
                _save_to_cache(m, norm_sym, trade_date, price, currency, source)
                return {
                    "market": m,
                    "symbol": norm_sym,
                    "date": trade_date,
                    "price": price,
                    "currency": currency,
                    "source": source,
                    "cached": False,
                    "error": None,
                }
        else:
            # 港/美股：优先调用 Server A 海外接口
            if OVERSEA_PRICE_API_ENABLED:
                _agent_price_debug(
                    "call_oversea_price_api_from_fetch_single_price",
                    {"market": m, "symbol": norm_sym, "trade_date": trade_date},
                    "P3",
                )
                remote = _fetch_from_oversea_api(m, norm_sym, trade_date)
                if remote and "price" in remote:
                    _save_to_cache(m, norm_sym, trade_date, remote["price"], remote["currency"], remote["source"])
                    _agent_price_debug(
                        "oversea_price_api_price_ok",
                        {
                            "market": m,
                            "symbol": norm_sym,
                            "trade_date": trade_date,
                            "price": remote["price"],
                            "currency": remote["currency"],
                        },
                        "P3",
                    )
                    return {
                        "market": m,
                        "symbol": norm_sym,
                        "date": trade_date,
                        "price": remote["price"],
                        "currency": remote["currency"],
                        "source": remote["source"],
                        "cached": False,
                        "error": None,
                    }
                if remote and "error" in remote:
                    _agent_price_debug(
                        "oversea_price_api_price_error",
                        {
                            "market": m,
                            "symbol": norm_sym,
                            "trade_date": trade_date,
                            "error": remote["error"],
                        },
                        "P3",
                    )
                    return {
                        "market": m,
                        "symbol": norm_sym,
                        "date": trade_date,
                        "price": 0.0,
                        "currency": "HKD" if m == "hk" else "USD",
                        "source": "",
                        "cached": False,
                        "error": remote["error"],
                    }
            # 兜底：本地 yfinance
            price, currency, source = _fetch_hk_us_price(norm_sym, trade_date, m)
            if price is not None:
                _save_to_cache(m, norm_sym, trade_date, price, currency, source)
                return {
                    "market": m,
                    "symbol": norm_sym,
                    "date": trade_date,
                    "price": price,
                    "currency": currency,
                    "source": source,
                    "cached": False,
                    "error": None,
                }

    # ========== 兼容旧模式 ==========
    if PRICE_API_ENABLED:
        remote = _fetch_from_remote_api(m, norm_sym, trade_date)
        if remote:
            _save_to_cache(m, norm_sym, trade_date, remote["price"], remote["currency"], remote["source"])
            return {
                "market": m,
                "symbol": norm_sym,
                "date": trade_date,
                "price": remote["price"],
                "currency": remote["currency"],
                "source": remote["source"],
                "cached": False,
                "error": None,
            }
        _debug_log_price(
            "remote_price_api_no_data",
            {
                "market": m,
                "symbol": norm_sym,
                "trade_date": trade_date,
            },
            hypothesis_id="P3",
        )
        err_msg = "远程价格服务未返回有效价格（price_api），请检查外部价格服务是否正常。"
        return {
            "market": m,
            "symbol": norm_sym,
            "date": trade_date,
            "price": 0.0,
            "currency": "CNY",
            "source": "remote",
            "cached": False,
            "error": err_msg,
        }

    # 若明确关闭 price_api.enabled，才会走本地数据源（兼容旧逻辑）
    if m == "cn":
        price, currency, source = _fetch_cn_price(norm_sym, trade_date)
    else:
        price, currency, source = _fetch_hk_us_price(norm_sym, trade_date, m)
    if price is not None:
        _save_to_cache(m, norm_sym, trade_date, price, currency, source)
        return {
            "market": m,
            "symbol": norm_sym,
            "date": trade_date,
            "price": price,
            "currency": currency,
            "source": source,
            "cached": False,
            "error": None,
        }
    err_msg = "指定日期未查询到价格，可能为非交易日或代码错误"
    _debug_log_price(
        "price_not_found_local_source",
        {
            "market": m,
            "symbol": norm_sym,
            "trade_date": trade_date,
            "err": err_msg,
        },
        hypothesis_id="P3",
    )
    return {
        "market": m,
        "symbol": norm_sym,
        "date": trade_date,
        "price": 0.0,
        "currency": currency,
        "source": source,
        "cached": False,
        "error": err_msg,
    }


def fetch_single_price_with_fallback(market: str, symbol: str) -> dict:
    """
    带交易日与重试逻辑的价格查询：
    - 先计算有效交易日（当天非交易日则用上一交易日）
    - 首次查询失败则依次向前尝试最多 3 次（共 4 次尝试）
    - 全部失败返回错误：「当前用户较多，资源紧张，请稍后重试」
    """
    m = _normalize_market(market)
    if not m or m not in ("cn", "hk", "us"):
        return {
            "market": market,
            "symbol": symbol,
            "date": "",
            "price": 0.0,
            "currency": "CNY",
            "source": "",
            "cached": False,
            "error": "不支持的 market，需为 cn/hk/us",
        }
    if not symbol or not symbol.strip():
        return {
            "market": m,
            "symbol": symbol or "",
            "date": "",
            "price": 0.0,
            "currency": "CNY",
            "source": "",
            "cached": False,
            "error": "symbol 不能为空",
        }

    trade_date = _get_effective_trade_date(m)
    _agent_price_debug(
        "fetch_single_price_with_fallback_enter",
        {
            "market": market,
            "normalized_market": m,
            "symbol": symbol,
            "trade_date_initial": trade_date,
        },
        "P4",
    )
    last_result: dict | None = None

    for attempt in range(4):  # 1 次初始 + 3 次向前重试
        _agent_price_debug(
            "fetch_single_price_with_fallback_attempt",
            {
                "attempt": attempt + 1,
                "market": m,
                "symbol": symbol,
                "trade_date": trade_date,
            },
            "P4",
        )
        result = fetch_single_price(m, symbol, trade_date)
        last_result = result
        if not result.get("error") and result.get("price"):
            _agent_price_debug(
                "fetch_single_price_with_fallback_success",
                {
                    "attempt": attempt + 1,
                    "market": m,
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "price": result.get("price"),
                },
                "P4",
            )
            return result
        prev = _get_prev_trade_day(m, trade_date)
        if not prev or prev == trade_date:
            break
        trade_date = prev

    if last_result is not None:
        last_result = dict(last_result)
        # 若已有具体错误（如代理 HTTP、解析失败等）则保留，否则用通用提示
        if not last_result.get("error") or last_result.get("error") == "指定日期未查询到价格，可能为非交易日或代码错误":
            last_result["error"] = "当前用户较多，资源紧张，请稍后重试"
    else:
        last_result = {
            "market": m,
            "symbol": _normalize_symbol(symbol, m),
            "date": "",
            "price": 0.0,
            "currency": "CNY",
            "source": "",
            "cached": False,
            "error": "当前用户较多，资源紧张，请稍后重试",
        }
    return last_result


def fetch_batch_prices(items: list[dict]) -> list[dict]:
    """批量查询，每条独立返回，单条失败不影响其它"""
    return [fetch_single_price(i["market"], i["symbol"], i["trade_date"]) for i in items]
