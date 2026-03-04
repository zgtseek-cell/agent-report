"""
股票价格查询服务（Server A）：
- A股：本地 akshare
- 港/美股：本地 yfinance
- 缓存层：Redis（统一缓存）+ SQLite（兜底）
- 自动判断交易日：非交易日使用上一交易日；获取失败时依次向前尝试最多 3 次
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import yfinance as yf

from .config import (
    AKSHARE_ADJUST,
    PRICE_CACHE_DB_PATH,
    REDIS_ENABLED,
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


def _debug_log_price(message: str, data: dict | None = None, hypothesis_id: str = "P?") -> None:
    """价格模块专用 debug 日志"""
    try:
        payload = {
            "sessionId": "server-a-price",
            "location": "backend/price.py",
            "message": message,
            "data": data or {},
            "timestamp": datetime.now().timestamp(),
        }
        # 可以写入日志文件，这里简化处理
        pass
    except Exception:
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
        # 根据 API 文档：调用方可传 700 或 0700.HK
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


def _fetch_cn_price(symbol: str, trade_date: str) -> Tuple[float | None, str, str]:
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


def _fetch_hk_us_price(symbol: str, trade_date: str, market: str) -> Tuple[float | None, str, str]:
    """港/美股：yfinance 本地，返回 (price, currency, source)"""
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
    支持 A股（akshare）和 港/美股（yfinance）。
    返回：{market, symbol, date, price, currency, source, cached, error?}
    """
    _init_cache_db()
    _debug_log_price(
        "fetch_single_price_called",
        {
            "market": market,
            "symbol": symbol,
            "trade_date": trade_date,
        },
        hypothesis_id="P1",
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
            hypothesis_id="P1",
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

    # 查询外部数据源
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
    _debug_log_price(
        "fetch_single_price_with_fallback_enter",
        {
            "market": market,
            "normalized_market": m,
            "symbol": symbol,
            "trade_date_initial": trade_date,
        },
        hypothesis_id="P2",
    )
    last_result: dict | None = None

    for attempt in range(4):  # 1 次初始 + 3 次向前重试
        _debug_log_price(
            "fetch_single_price_with_fallback_attempt",
            {
                "attempt": attempt + 1,
                "market": m,
                "symbol": symbol,
                "trade_date": trade_date,
            },
            hypothesis_id="P2",
        )
        result = fetch_single_price(m, symbol, trade_date)
        last_result = result
        if not result.get("error") and result.get("price"):
            _debug_log_price(
                "fetch_single_price_with_fallback_success",
                {
                    "attempt": attempt + 1,
                    "market": m,
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "price": result.get("price"),
                },
                hypothesis_id="P2",
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
