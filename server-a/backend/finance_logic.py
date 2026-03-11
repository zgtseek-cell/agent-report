from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from financetoolkit import Toolkit

from .config import FMP_API_KEY


# region agent log
def _logic_ndjson_log(message: str, data: dict | None = None, hypothesis_id: str = "A?") -> None:
    try:
        payload = {
            "id": f"log_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "location": "server-a/backend/finance_logic.py",
            "message": message,
            "data": data or {},
            "runId": "pre-fix-4",
            "hypothesisId": hypothesis_id,
        }
        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# endregion agent log


def _normalize_ticker(ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not value:
        raise ValueError("ticker 不能为空")
    return value


def _empty_metric(metric_name: str) -> dict[str, Any]:
    return {
        "metric": metric_name,
        "latest": None,
        "historical_mean": None,
        "history": {},
        "source_label": None,
    }


def _safe_number(value: Any) -> float | int | None:
    try:
        if value is None:
            return None
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                return None
            return round(value, 6)
        if hasattr(value, "item"):
            item = value.item()
            if isinstance(item, (int, float)):
                if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
                    return None
                return round(item, 6)
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return None
        numeric = float(numeric)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        return round(numeric, 6)
    except Exception:
        return None


def _safe_scalar(value: Any) -> Any:
    num = _safe_number(value)
    if num is not None:
        return num
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _clean_json_payload(obj: Any) -> Any:
    """递归清洗字典：1. 非标准Key转为字符串; 2. NaN/Inf转为None"""
    if isinstance(obj, dict):
        return {str(k): _clean_json_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json_payload(item) for item in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {str(k): _sanitize_value(v) for k, v in data.items()}


def _sanitize_series(series: pd.Series) -> dict[str, Any]:
    return {str(idx): _safe_scalar(value) for idx, value in series.items()}


def _sanitize_dataframe(frame: pd.DataFrame, max_rows: int = 40, max_cols: int = 24) -> dict[str, Any]:
    df = frame.copy()

    if isinstance(df.index, pd.MultiIndex):
        df.index = [" | ".join(str(x) for x in idx) for idx in df.index]
    else:
        df.index = df.index.map(str)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" | ".join(str(x) for x in col) for col in df.columns]
    else:
        df.columns = df.columns.map(str)

    df = df.iloc[:max_rows, :max_cols]

    records: list[dict[str, Any]] = []
    for index_name, row in df.iterrows():
        item = {"_row": str(index_name)}
        for col_name, value in row.items():
            item[str(col_name)] = _safe_scalar(value)
        records.append(item)

    return {
        "columns": [str(c) for c in df.columns],
        "rows": records,
    }


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return _sanitize_dataframe(value)
    if isinstance(value, pd.Series):
        return _sanitize_series(value)
    if isinstance(value, dict):
        return _sanitize_dict(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]
    return _safe_scalar(value)


def _unwrap_ticker_frame(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    df = frame.copy()

    if isinstance(df.columns, pd.MultiIndex):
        for level in range(df.columns.nlevels):
            try:
                if ticker in df.columns.get_level_values(level):
                    df = df.xs(ticker, axis=1, level=level)
                    break
            except Exception:
                continue

    if isinstance(df.index, pd.MultiIndex):
        for level in range(df.index.nlevels):
            try:
                if ticker in df.index.get_level_values(level):
                    df = df.xs(ticker, axis=0, level=level)
                    break
            except Exception:
                continue

    return df


def _match_label(labels: list[str], candidates: list[str]) -> str | None:
    normalized = {label.lower().strip(): label for label in labels}
    for candidate in candidates:
        cand = candidate.lower().strip()
        if cand in normalized:
            return normalized[cand]
    for candidate in candidates:
        cand = candidate.lower().strip()
        for label in labels:
            text = label.lower().strip()
            if cand in text or text in cand:
                return label
    return None


def _extract_metric_stats_from_frame(
    frame: pd.DataFrame,
    ticker: str,
    metric_name: str,
    candidate_labels: list[str],
) -> dict[str, Any]:
    df = _unwrap_ticker_frame(frame, ticker)

    if df.empty:
        return _empty_metric(metric_name)

    row_label = _match_label([str(x) for x in df.index], candidate_labels)
    if row_label is not None:
        series = df.loc[row_label]
        source_label = row_label
    else:
        col_label = _match_label([str(x) for x in df.columns], candidate_labels)
        if col_label is None:
            return _empty_metric(metric_name)
        series = df[col_label]
        source_label = col_label

    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]

    numeric = pd.to_numeric(series, errors="coerce").dropna()
    history = {str(idx): _safe_number(val) for idx, val in numeric.items()}

    return {
        "metric": metric_name,
        "latest": _safe_number(numeric.iloc[-1]) if not numeric.empty else None,
        "historical_mean": _safe_number(numeric.mean()) if not numeric.empty else None,
        "history": history,
        "source_label": source_label,
    }


def _try_call(obj: Any, method_names: list[str]) -> tuple[str | None, Any]:
    for name in method_names:
        target = getattr(obj, name, None)
        if not callable(target):
            continue
        try:
            return name, target()
        except TypeError:
            continue
        except Exception:
            continue
    return None, None


def _build_toolkit(ticker: str) -> Toolkit:
    normalized_ticker = _normalize_ticker(ticker)
    if not FMP_API_KEY:
        print(
            f"[FinanceToolkit][WARN] FMP_API_KEY 未配置，ticker={normalized_ticker}，"
            "估值/财务健康度请求可能失败。"
        )
        _logic_ndjson_log("fmp_api_key_missing", {"ticker": normalized_ticker}, "A0")

    return Toolkit(
        tickers=[normalized_ticker],
        api_key=FMP_API_KEY,
    )


def _get_valuation_ratio_frame(toolkit: Toolkit) -> tuple[str | None, pd.DataFrame | None]:
    method_name, result = _try_call(
        toolkit.ratios,
        [
            "collect_valuation_ratios",
            "get_valuation_ratios",
        ],
    )
    if isinstance(result, pd.DataFrame):
        return method_name, result
    return method_name, None


def _get_profitability_ratio_frame(toolkit: Toolkit) -> tuple[str | None, pd.DataFrame | None]:
    method_name, result = _try_call(
        toolkit.ratios,
        [
            "collect_profitability_ratios",
            "get_profitability_ratios",
        ],
    )
    if isinstance(result, pd.DataFrame):
        return method_name, result
    return method_name, None


def _extract_intrinsic_value_payload(toolkit: Toolkit, ticker: str) -> dict[str, Any]:
    method_name, result = _try_call(
        toolkit.models,
        [
            "get_intrinsic_valuation",
            "get_intrinsic_value",
            "get_discounted_cash_flow",
            "get_enterprise_value_breakdown",
        ],
    )

    payload: dict[str, Any] = {
        "method": method_name,
        "intrinsic_value": None,
        "inputs": None,
        "raw": None,
    }

    if result is None:
        return payload

    payload["raw"] = _sanitize_value(result)

    if isinstance(result, pd.DataFrame):
        df = _unwrap_ticker_frame(result, ticker)
        if not df.empty:
            labels = [str(x) for x in df.index] + [str(x) for x in df.columns]
            key = _match_label(
                labels,
                [
                    "Intrinsic Value",
                    "Intrinsic Value Per Share",
                    "Equity Value Per Share",
                    "Fair Value",
                    "DCF Value",
                ],
            )
            if key is not None:
                stats = _extract_metric_stats_from_frame(df, ticker, "intrinsic_value", [key])
                payload["intrinsic_value"] = stats.get("latest")
            payload["inputs"] = _sanitize_dataframe(df)
        return payload

    if isinstance(result, pd.Series):
        cleaned = _sanitize_series(result)
        payload["inputs"] = cleaned
        match_key = _match_label(
            list(cleaned.keys()),
            [
                "Intrinsic Value",
                "Intrinsic Value Per Share",
                "Equity Value Per Share",
                "Fair Value",
                "DCF Value",
            ],
        )
        if match_key is not None:
            payload["intrinsic_value"] = cleaned.get(match_key)
        return payload

    if isinstance(result, dict):
        cleaned = _sanitize_dict(result)
        payload["inputs"] = cleaned
        match_key = _match_label(
            list(cleaned.keys()),
            [
                "Intrinsic Value",
                "Intrinsic Value Per Share",
                "Equity Value Per Share",
                "Fair Value",
                "DCF Value",
            ],
        )
        if match_key is not None:
            payload["intrinsic_value"] = cleaned.get(match_key)
        return payload

    return payload


def _get_yf_snapshot(ticker: str) -> dict:
    """使用 yfinance 获取最新准确估值与币种信息，解决 ADR 错配问题"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "price_currency": info.get("currency", "USD"),
            "financial_currency": info.get("financialCurrency", "USD"),
            "yf_pe": info.get("trailingPE"),
            "yf_pb": info.get("priceToBook"),
            "yf_ev_ebitda": info.get("enterpriseToEbitda"),
            "yf_market_cap": info.get("marketCap"),
        }
    except Exception as e:
        print(f"[YFinance Error] 获取 {ticker} 失败: {e}")
        return {}


def _calculate_valuation_band(history_dict: dict) -> dict:
    """计算历史估值通道，增加极致防呆与错误捕获"""
    if not isinstance(history_dict, dict) or not history_dict:
        return {}

    try:
        # 严格过滤，确保只有单一数值型才参与计算，防范嵌套字典导致的 unhashable 错误
        values = [
            float(v)
            for v in history_dict.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        if not values:
            return {}

        return {
            "min": round(float(np.min(values)), 2),
            "p10_extreme_undervalued": round(float(np.percentile(values, 10)), 2),
            "p20_undervalued": round(float(np.percentile(values, 20)), 2),
            "p50_median": round(float(np.median(values)), 2),
            "p80_overvalued": round(float(np.percentile(values, 80)), 2),
            "p90_extreme_overvalued": round(float(np.percentile(values, 90)), 2),
            "max": round(float(np.max(values)), 2),
        }
    except Exception as e:
        print(f"[Band Calc Error] 通道计算失败: {e}")
        return {}


def get_company_valuation_metrics(ticker: str) -> dict[str, Any]:
    normalized_ticker = _normalize_ticker(ticker)
    try:
        toolkit = _build_toolkit(normalized_ticker)

        valuation_method, valuation_frame = _get_valuation_ratio_frame(toolkit)
        profitability_method, profitability_frame = _get_profitability_ratio_frame(toolkit)
        intrinsic_payload = _extract_intrinsic_value_payload(toolkit, normalized_ticker)

        pe_stats = (
            _extract_metric_stats_from_frame(
                valuation_frame,
                normalized_ticker,
                "pe",
                [
                    "Price to Earnings Ratio",
                    "P/E Ratio",
                    "PE Ratio",
                    "Price Earnings Ratio",
                    "Price to Earnings",
                ],
            )
            if isinstance(valuation_frame, pd.DataFrame)
            else _empty_metric("pe")
        )
        pb_stats = (
            _extract_metric_stats_from_frame(
                valuation_frame,
                normalized_ticker,
                "pb",
                [
                    "Price to Book Ratio",
                    "P/B Ratio",
                    "PB Ratio",
                    "Price Book Ratio",
                    "Price to Book",
                ],
            )
            if isinstance(valuation_frame, pd.DataFrame)
            else _empty_metric("pb")
        )
        roe_stats = (
            _extract_metric_stats_from_frame(
                profitability_frame,
                normalized_ticker,
                "roe",
                [
                    "Return on Equity",
                    "ROE",
                    "Return On Equity",
                ],
            )
            if isinstance(profitability_frame, pd.DataFrame)
            else _empty_metric("roe")
        )

        # --- 新增：获取外挂黄金数据 ---
        yf_snapshot = _get_yf_snapshot(normalized_ticker)

        # 提取 history 时增加安全校验，防范 NoneType 或不规范字典
        pe_history = pe_stats.get("history", {}) if isinstance(pe_stats, dict) else {}
        pb_history = pb_stats.get("history", {}) if isinstance(pb_stats, dict) else {}

        pe_band = _calculate_valuation_band(pe_history)
        pb_band = _calculate_valuation_band(pb_history)
        # ------------------------------

        # 如果 FMP 限流导致基础数据全空，给大模型一个明确的系统级 error_note
        error_note: str | None = None
        if not pe_history and not pb_history:
            error_note = (
                "【系统底层警报】：核心财务数据API额度耗尽。请强制使用 yfinance_snapshot 中的最新估值，"
                "并向用户提示『历史区间估值暂不可用』。"
            )

        raw_tables: dict[str, Any] = {
            "valuation_ratios": valuation_frame.to_dict(orient="index") if isinstance(valuation_frame, pd.DataFrame) else {},
            "profitability_ratios": profitability_frame.to_dict(orient="index") if isinstance(profitability_frame, pd.DataFrame) else {},
        }

        # 1. 组装全量数据（此时可能含有 Period 键和 NaN 值）
        response_payload: dict[str, Any] = {
            "ticker": normalized_ticker,
            "error": error_note,
            "valuation_metrics": {
                "pe": pe_stats if isinstance(pe_stats, dict) else {},
                "pb": pb_stats if isinstance(pb_stats, dict) else {},
            },
            "profitability_metrics": {
                "roe": roe_stats if isinstance(roe_stats, dict) else {},
            },
            "intrinsic_value": intrinsic_payload,
            "yfinance_snapshot": yf_snapshot,
            "valuation_bands": {
                "pe_band": pe_band,
                "pb_band": pb_band,
            },
            "raw_tables": raw_tables if isinstance(raw_tables, dict) else {},
        }

        # 【终极净化】清洗所有非法键与 NaN/Inf 浮点数
        response_payload = _clean_json_payload(response_payload)

        # 2. JSON 序列化防火墙 (严格模拟 FastAPI 的 allow_nan=False)
        try:
            import json
            json.dumps(response_payload, default=str, allow_nan=False)
            return response_payload

        except ValueError as e:
            # 捕获 NaN 遗漏等 Value 错误
            print(
                f"[\033[91mCRITICAL ERROR\033[0m] JSON 序列化失败 (值异常): {e}"
            )
            return {
                "ticker": normalized_ticker,
                "error": f"浮点数值异常: {str(e)}",
                "yfinance_snapshot": yf_snapshot,
                "valuation_bands": {
                    "pe_band": pe_band,
                    "pb_band": pb_band,
                },
            }
        except TypeError as e:
            print(
                f"[\033[91mCRITICAL ERROR\033[0m] JSON 序列化失败 (键异常): {e}"
            )
            return {
                "ticker": normalized_ticker,
                "error": f"字典键异常: {str(e)}",
                "yfinance_snapshot": yf_snapshot,
                "valuation_bands": {
                    "pe_band": pe_band,
                    "pb_band": pb_band,
                },
            }
    except Exception as exc:
        print(f"[FinanceToolkit][ERROR] valuation failed for {normalized_ticker}: {exc}")
        _logic_ndjson_log(
            "valuation_logic_failed",
            {"ticker": normalized_ticker, "error": str(exc)},
            "A1",
        )
        return {
            "ticker": normalized_ticker,
            "error": f"API请求失败: {str(exc)}",
            "valuation_metrics": {"pe": _empty_metric("pe"), "pb": _empty_metric("pb")},
            "profitability_metrics": {"roe": _empty_metric("roe")},
            "intrinsic_value": {"method": None, "intrinsic_value": None, "inputs": None, "raw": None},
            "raw_tables": {},
        }


def get_company_financial_health_snapshot(ticker: str) -> dict[str, Any]:
    normalized_ticker = _normalize_ticker(ticker)
    try:
        toolkit = _build_toolkit(normalized_ticker)
        method_name, ratio_frame = _try_call(
            toolkit.ratios,
            [
                "collect_solvency_ratios",
                "get_solvency_ratios",
                "collect_liquidity_ratios",
                "get_liquidity_ratios",
            ],
        )

        if not isinstance(ratio_frame, pd.DataFrame):
            return {
                "ticker": normalized_ticker,
                "error": None,
                "source_method": method_name,
                "metrics": {},
                "raw_table": None,
            }

        debt_to_equity = _extract_metric_stats_from_frame(
            ratio_frame,
            normalized_ticker,
            "debt_to_equity",
            [
                "Debt to Equity Ratio",
                "Debt-to-Equity Ratio",
                "Debt to Equity",
            ],
        )
        current_ratio = _extract_metric_stats_from_frame(
            ratio_frame,
            normalized_ticker,
            "current_ratio",
            ["Current Ratio"],
        )

        return {
            "ticker": normalized_ticker,
            "error": None,
            "source_method": method_name,
            "metrics": {
                "debt_to_equity": debt_to_equity,
                "current_ratio": current_ratio,
            },
            "raw_table": _sanitize_dataframe(_unwrap_ticker_frame(ratio_frame, normalized_ticker)),
        }
    except Exception as exc:
        print(f"[FinanceToolkit][ERROR] health failed for {normalized_ticker}: {exc}")
        _logic_ndjson_log(
            "financial_health_logic_failed",
            {"ticker": normalized_ticker, "error": str(exc)},
            "A2",
        )
        return {
            "ticker": normalized_ticker,
            "error": f"API请求失败: {str(exc)}",
            "source_method": None,
            "metrics": {},
            "raw_table": None,
        }
