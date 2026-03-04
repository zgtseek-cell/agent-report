#!/usr/bin/env python3
"""
财务看板接口测试（Server B）
- GET /api/dcf?symbol=...&market=...
- GET /api/financials?symbol=...&market=...
- GET /api/pepb-band?symbol=...&market=...

运行方式：
  python scripts/test_dashboard_api.py [--base http://127.0.0.1:8001] [--symbol 0700.HK] [--market hk]
  需先启动 B：./start.sh 或 uvicorn backend.main:app --host 0.0.0.0 --port 8001
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

SERVER_B_ROOT = Path(__file__).resolve().parent.parent

# 前端看板期望的响应结构（最小键集）
DCF_REQUIRED = ["raw", "valuation", "chart", "parameters"]
DCF_RAW_REQUIRED = ["current_price", "currency"]
DCF_VALUATION_REQUIRED = ["intrinsic_value", "margin_of_safety", "recommendation"]

FINANCIALS_REQUIRED = ["chart"]
FINANCIALS_CHART_REQUIRED = ["income_statement"]
INCOME_STMT_REQUIRED = ["labels", "datasets"]

PEPB_REQUIRED = ["chart"]
PEPB_CHART_REQUIRED = ["pe_band"]
PE_BAND_REQUIRED = ["labels", "datasets"]


def get(url: str, timeout: int = 30) -> Tuple[int, Optional[dict], Optional[str]]:
    """GET 请求，返回 (status_code, json_body or None, error_message or None)。"""
    try:
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return (resp.status, None, f"非 JSON 响应: {raw[:200]}")
            return (resp.status, data, None)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = None
        except Exception:
            body = ""
            data = None
        return (e.code, data, body or str(e))
    except urllib.error.URLError as e:
        return (0, None, str(e.reason) if getattr(e, "reason", None) else str(e))
    except Exception as e:
        return (0, None, str(e))


def check_dcf(data: dict) -> List[str]:
    """检查 /api/dcf 响应结构，返回错误列表（空表示通过）。"""
    errs = []
    if not isinstance(data, dict):
        return ["响应不是对象"]
    for key in DCF_REQUIRED:
        if key not in data:
            errs.append(f"缺少顶层键: {key}")
    if "raw" in data:
        for k in DCF_RAW_REQUIRED:
            if k not in data["raw"]:
                errs.append(f"raw 缺少: {k}")
    if "valuation" in data:
        for k in DCF_VALUATION_REQUIRED:
            if k not in data["valuation"]:
                errs.append(f"valuation 缺少: {k}")
    return errs


def check_financials(data: dict) -> List[str]:
    """检查 /api/financials 响应结构。"""
    errs = []
    if not isinstance(data, dict):
        return ["响应不是对象"]
    for key in FINANCIALS_REQUIRED:
        if key not in data:
            errs.append(f"缺少顶层键: {key}")
    if "chart" in data and isinstance(data["chart"], dict):
        for k in FINANCIALS_CHART_REQUIRED:
            if k not in data["chart"]:
                errs.append(f"chart 缺少: {k}")
        if "income_statement" in data["chart"]:
            stmt = data["chart"]["income_statement"]
            for k in INCOME_STMT_REQUIRED:
                if k not in stmt:
                    errs.append(f"chart.income_statement 缺少: {k}")
    return errs


def check_pepb(data: dict) -> List[str]:
    """检查 /api/pepb-band 响应结构。"""
    errs = []
    if not isinstance(data, dict):
        return ["响应不是对象"]
    for key in PEPB_REQUIRED:
        if key not in data:
            errs.append(f"缺少顶层键: {key}")
    if "chart" in data and isinstance(data["chart"], dict):
        for k in PEPB_CHART_REQUIRED:
            if k not in data["chart"]:
                errs.append(f"chart 缺少: {k}")
        if "pe_band" in data["chart"]:
            pb = data["chart"]["pe_band"]
            for k in PE_BAND_REQUIRED:
                if k not in pb:
                    errs.append(f"chart.pe_band 缺少: {k}")
    return errs


def run_tests(base_url: str, symbol: str, market: str) -> List[dict]:
    """对给定 symbol/market 请求三个接口并校验。"""
    base = base_url.rstrip("/")
    results = []

    # /api/dcf
    url = f"{base}/api/dcf?symbol={urllib.parse.quote(symbol)}&market={urllib.parse.quote(market)}"
    status, data, err = get(url)
    dcf_ok = status == 200 and data is not None and len(check_dcf(data)) == 0
    results.append({
        "name": "/api/dcf",
        "ok": dcf_ok,
        "status": status,
        "errors": check_dcf(data) if data else [err or f"HTTP {status}"],
        "preview": _preview_dcf(data) if data else None,
    })

    # /api/financials
    url = f"{base}/api/financials?symbol={urllib.parse.quote(symbol)}&market={urllib.parse.quote(market)}"
    status, data, err = get(url)
    fin_ok = status == 200 and data is not None and len(check_financials(data)) == 0
    results.append({
        "name": "/api/financials",
        "ok": fin_ok,
        "status": status,
        "errors": check_financials(data) if data else [err or f"HTTP {status}"],
        "preview": _preview_financials(data) if data else None,
    })

    # /api/pepb-band
    url = f"{base}/api/pepb-band?symbol={urllib.parse.quote(symbol)}&market={urllib.parse.quote(market)}"
    status, data, err = get(url)
    pepb_ok = status == 200 and data is not None and len(check_pepb(data)) == 0
    results.append({
        "name": "/api/pepb-band",
        "ok": pepb_ok,
        "status": status,
        "errors": check_pepb(data) if data else [err or f"HTTP {status}"],
        "preview": _preview_pepb(data) if data else None,
    })

    return results


def _preview_dcf(data: dict) -> str:
    if not data:
        return ""
    raw = data.get("raw") or {}
    val = data.get("valuation") or {}
    return f"股价={raw.get('current_price')} {raw.get('currency')} 内在价值={val.get('intrinsic_value')} 建议={val.get('recommendation')}"


def _preview_financials(data: dict) -> str:
    if not data:
        return ""
    stmt = (data.get("chart") or {}).get("income_statement") or {}
    labels = stmt.get("labels") or []
    datasets = stmt.get("datasets") or []
    return f"labels={len(labels)} datasets={len(datasets)}"


def _preview_pepb(data: dict) -> str:
    if not data:
        return ""
    pb = (data.get("chart") or {}).get("pe_band") or {}
    labels = pb.get("labels") or []
    datasets = pb.get("datasets") or []
    return f"labels={len(labels)} datasets={len(datasets)}"


def main():
    parser = argparse.ArgumentParser(description="财务看板接口测试（/api/dcf, /api/financials, /api/pepb-band）")
    parser.add_argument("--base", default="http://127.0.0.1:8001", help="B 服务 base URL")
    parser.add_argument("--symbol", default="0700.HK", help="股票代码，如 0700.HK 或 AAPL")
    parser.add_argument("--market", default="hk", help="市场：hk / us")
    args = parser.parse_args()

    print("=== 财务看板接口测试 ===\n")
    print(f"Base URL: {args.base}")
    print(f"Symbol:   {args.symbol}  Market: {args.market}\n")

    results = run_tests(args.base, args.symbol, args.market)

    for r in results:
        status = "通过" if r["ok"] else "失败"
        print(f"[{status}] {r['name']}  (HTTP {r['status']})")
        if r.get("preview"):
            print(f"       {r['preview']}")
        if not r["ok"] and r.get("errors"):
            for e in r["errors"]:
                print(f"       - {e}")
        print()

    ok_count = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"--- 结果: {ok_count}/{total} 通过 ---")
    if ok_count < total:
        print("请确认：B 已启动（./start.sh），且能访问行情源（港/美股经 A 代理或直连）。")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
