from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from langchain_core.tools import tool

from ..config import PROXY_TIMEOUT, SERVER_A_BASE_URL, SERVER_A_HOST, SERVER_A_PORT


def _normalize_ticker(ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not value:
        raise ValueError("ticker 不能为空")
    return value


# region agent log
def _tool_ndjson_log(message: str, data: dict | None = None, hypothesis_id: str = "TB?") -> None:
    try:
        payload = {
            "id": f"log_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "location": "backend/agent_core/tools.py",
            "message": message,
            "data": data or {},
            "runId": "pre-fix-5",
            "hypothesisId": hypothesis_id,
        }
        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# endregion agent log


def _get_server_a_base_url() -> str:
    if SERVER_A_BASE_URL:
        return SERVER_A_BASE_URL.rstrip("/")
    return f"http://{SERVER_A_HOST}:{SERVER_A_PORT}"


def _empty_metric(metric_name: str) -> dict[str, Any]:
    return {
        "metric": metric_name,
        "latest": None,
        "historical_mean": None,
        "history": {},
        "source_label": None,
    }


def _default_valuation_payload(ticker: str, error: str | None = None) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "error": error,
        "valuation_metrics": {
            "pe": _empty_metric("pe"),
            "pb": _empty_metric("pb"),
        },
        "profitability_metrics": {
            "roe": _empty_metric("roe"),
        },
        "intrinsic_value": {
            "method": None,
            "intrinsic_value": None,
            "inputs": None,
            "raw": None,
        },
        "raw_tables": {},
    }


def _default_health_payload(ticker: str, error: str | None = None) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "error": error,
        "source_method": None,
        "metrics": {},
        "raw_table": None,
    }


def _request_server_a(endpoint: str, ticker: str) -> dict[str, Any]:
    url = f"{_get_server_a_base_url()}{endpoint}"
    timeout = max(5.0, float(PROXY_TIMEOUT or 30))
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, params={"ticker": ticker})
        if response.status_code != 200:
            preview = response.text[:200]
            raise RuntimeError(f"Server A HTTP {response.status_code}: {preview}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Server A 返回的不是 JSON 对象")
        return payload
    except Exception as exc:
        _tool_ndjson_log(
            "server_a_request_failed",
            {"endpoint": endpoint, "ticker": ticker, "error": str(exc)},
            "TB1",
        )
        raise


@tool(
    "get_company_valuation_metrics",
    description="通过 Server A 获取公司估值与核心回报指标。",
)
def get_company_valuation_metrics(ticker: str) -> dict[str, Any]:
    """通过 HTTP 调用 Server A，获取 JSON 化的估值数据。"""
    normalized_ticker = _normalize_ticker(ticker)
    try:
        payload = _request_server_a("/api/agent-data/valuation", normalized_ticker)
        result = _default_valuation_payload(normalized_ticker, None)
        result.update(payload)
        result["ticker"] = normalized_ticker
        return result
    except Exception as exc:
        print(f"[AgentTool][ERROR] valuation request failed for {normalized_ticker}: {exc}")
        return _default_valuation_payload(normalized_ticker, f"API请求失败: {str(exc)}")


@tool(
    "get_company_financial_health_snapshot",
    description="通过 Server A 获取公司财务健康度快照。",
)
def get_company_financial_health_snapshot(ticker: str) -> dict[str, Any]:
    """通过 HTTP 调用 Server A，获取 JSON 化的财务健康度数据。"""
    normalized_ticker = _normalize_ticker(ticker)
    try:
        payload = _request_server_a("/api/agent-data/health", normalized_ticker)
        result = _default_health_payload(normalized_ticker, None)
        result.update(payload)
        result["ticker"] = normalized_ticker
        return result
    except Exception as exc:
        print(f"[AgentTool][ERROR] health request failed for {normalized_ticker}: {exc}")
        return _default_health_payload(normalized_ticker, f"API请求失败: {str(exc)}")
