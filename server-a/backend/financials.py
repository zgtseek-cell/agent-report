"""
财务和估值数据模块（Server A）
提供 DCF、财务趋势、PE Band 数据的计算接口
"""

import yfinance as yf

from typing import Dict, Any


def _ticker_for_symbol(symbol: str, market: str) -> str:
    """将 symbol+market 转为 yfinance ticker"""
    s = (symbol or "").strip()
    if not s:
        return ""
    if s.isdigit() and (market or "").lower() in ("hk", "hongkong", "港股"):
        return f"{s}.HK"
    if s.isdigit() and (market or "").lower() in ("us", "usa", "美股"):
        return s  # 美股数字代码较少，直接返回
    return s.upper()


def _get_dcf_payload(tk: "yf.Ticker", info: Dict[str, Any]) -> Dict[str, Any]:
    """从 Ticker 与 info 构造 /api/dcf 前端所需结构"""
    if not isinstance(info, dict):
        info = {}
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0
    currency = info.get("currency") or "udi"
    pe = info.get("trailingPE") or info.get("forwardPE")
    eps = info.get("trailingEps") or info.get("forwardEps")
    # 简化内在价值：若有 PE 和 EPS 则 intrinsic = PE * EPS，否则用当前价作占位
    intrinsic = (float(pe) * float(eps)) if (pe is not None and eps is not None and float(eps) != 0) else price
    margin = ((intrinsic - price) / intrinsic * 100) if intrinsic and float(intrinsic) > 0 else 0
    if margin >= 20:
        recommendation = "低估"
    elif margin >= 0:
        recommendation = "合理"
    else:
        recommendation = "高估"
    labels = []
    datasets = []
    try:
        # 简单 DCF 图：过去几年 + 未来几年占位
        hist = tk.history(period="5y") if hasattr(tk, "history") else None
        if hist is not None and not hist.empty:
            hist = hist.tail(12)
            labels = [x.strftime("%Y-%m") for x in hist.index]
            datasets = [
                {"label": "股价", "data": hist["Close"].fillna(0).tolist()},
            ]
    except Exception:
        pass
    return {
        "raw": {"current_price": round(float(price), 2), "currency": currency},
        "valuation": {
            "intrinsic_value": round(float(intrinsic), 2),
            "margin_of_safety": round(float(margin), 1),
            "recommendation": recommendation,
        },
        "chart": {"labels": labels, "datasets": datasets} if labels else {},
        "parameters": {
            "growth_rate": 0.08,
            "terminal_growth": 0.02,
            "discount_rate": 0.10,
            "years": 5,
        },
    }


def _get_financials_payload(tk: "yf.Ticker") -> Dict[str, Any]:
    """从 Ticker 构造 /api/financials 前端所需结构（营收、净利润、EBITDA）"""
    out = {"chart": {"income_statement": {"labels": [], "datasets": []}}}
    try:
        import pandas as pd
        stmt = getattr(tk, "income_stmt", None)
        if stmt is None:
            get_stmt = getattr(tk, "get_income_stmt", None)
            stmt = get_stmt() if callable(get_stmt) else None
        if stmt is None or (hasattr(stmt, "empty") and stmt.empty):
            return out
        if not isinstance(stmt, pd.DataFrame):
            return out
        stmt = stmt.tail(5)
        labels = [str(c)[:7] for c in stmt.columns]
        want = {"revenue": "营收", "net income": "净利润", "ebitda": "EBITDA"}
        seen = set()
        datasets = []
        for idx in stmt.index:
            idx_str = str(idx).lower()
            for key, label in want.items():
                if key in idx_str and label not in seen:
                    seen.add(label)
                    try:
                        row = stmt.loc[idx]
                    except Exception:
                        continue
                    data = []
                    for c in stmt.columns:
                        v = row.get(c)
                        data.append(float(v) if v is not None and pd.notna(v) else 0)
                    if any(x != 0 for x in data):
                        datasets.append({"label": label, "data": data})
                    break
        out["chart"]["income_statement"] = {"labels": labels, "datasets": datasets}
    except Exception:
        pass
    return out


def _get_pepb_payload(tk: "yf.Ticker", info: Dict[str, Any]) -> Dict[str, Any]:
    """从 Ticker 构造 /api/pepb-band 前端所需结构"""
    out = {"chart": {"pe_band": {"labels": [], "datasets": []}}}
    try:
        hist = tk.history(period="2y") if hasattr(tk, "history") else None
        if hist is None or hist.empty:
            return out
        hist = hist.tail(24)
        labels = [x.strftime("%Y-%m") for x in hist.index]
        close = hist["Close"].fillna(0).tolist()
        pe = info.get("trailingPE") or info.get("forwardPE")
        pe = float(pe) if pe is not None else 20
        # 简化 PE band：用当前 PE 的 0.5/0.75/1/1.25/1.5 倍 * 基准价
        if not close or close[-1] <= 0:
            return out
        pe_min, pe_25, pe_75, pe_max = pe * 0.5, pe * 0.75, pe * 1.25, pe * 1.5

        def band(ratio):
            return [round(c * ratio, 2) for c in close]

        datasets = [
            {"label": "股价", "data": close},
            {"label": "PE Min", "data": band(pe_min / pe), "borderDash": True},
            {"label": "PE 25%", "data": band(pe_25 / pe), "borderDash": True},
            {"label": "PE 50%", "data": band(1.0)},
            {"label": "PE 75%", "data": band(pe_75 / pe), "borderDash": True},
            {"label": "PE Max", "data": band(pe_max / pe), "borderDash": True},
        ]
        out["chart"]["pe_band"] = {"labels": labels, "datasets": datasets}
    except Exception:
        pass
    return out
