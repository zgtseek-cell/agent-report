#!/usr/bin/env python3
"""
拉行情功能测试脚本（Server B）
- 测试 fetch_single_price_with_fallback（港/美股经 A 代理，A 股本地 akshare）
- 测试 _fetch_market_data（公司名解析 + 价格拉取）

运行方式（任选其一）：
  A) 与后端同环境：在 server-b 下先执行 ./start.sh 或激活 venv 并 pip install -r requirements.txt，
     再执行：python scripts/test_market_data.py
  B) 通过已启动的 B 服务 HTTP 测试：python scripts/test_market_data.py --http [--base http://127.0.0.1:8001]
  C) 快速测试（仅港股腾讯，约 1 分钟内）：python scripts/test_market_data.py --quick
"""

import argparse
import json
import os
import sys
from pathlib import Path

SERVER_B_ROOT = Path(__file__).resolve().parent.parent


def run_http_tests(base_url: str) -> list:
    """通过 HTTP 调用 B 的 /api/analyze_sse，解析首条事件判断是否有行情（或连接成功）"""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/analyze_sse?company_name=腾讯&market=hk",
            headers={"Accept": "text/event-stream"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=65) as resp:
            chunk = resp.read(4096).decode("utf-8", errors="replace")
    except Exception as e:
        return [{"ok": False, "error": str(e)}]
    # 检查是否收到 SSE 数据（含 data: 或 [DONE] 等）
    if "data:" in chunk or "[DONE]" in chunk or "event:" in chunk:
        return [{"ok": True, "message": "SSE 流已建立，拉行情流程可触发"}]
    return [{"ok": False, "error": "未收到有效 SSE 内容", "preview": chunk[:200]}]


def run_direct_tests(quick: bool = False) -> list:
    """直接导入 backend 调用价格与拉行情接口。quick=True 时仅测港股腾讯。"""
    os.chdir(SERVER_B_ROOT)
    if str(SERVER_B_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_B_ROOT))

    from dotenv import load_dotenv
    load_dotenv(SERVER_B_ROOT / ".env")

    from backend.price import fetch_single_price_with_fallback
    from backend.main import _fetch_market_data
    from backend.config import PRICE_SPLIT_ENABLED, OVERSEA_PRICE_API_ENABLED, SERVER_A_HOST, SERVER_A_PORT

    def test_single_price(market: str, symbol: str) -> dict:
        print(f"  [单价格] market={market}, symbol={symbol} ... ", end="", flush=True)
        out = fetch_single_price_with_fallback(market, symbol)
        price = out.get("price")
        err = out.get("error")
        if price and not err:
            print(f"OK price={price} {out.get('currency','')} source={out.get('source','')}")
            return {"ok": True, "price": price, "currency": out.get("currency"), "source": out.get("source")}
        print(f"FAIL error={err or 'no price'}")
        return {"ok": False, "error": err or "no price"}

    def test_fetch_market_data(company_name: str, market: str, symbol: str | None = None) -> dict:
        print(f"  [拉行情] company={company_name}, market={market}, symbol={symbol or ''} ... ", end="", flush=True)
        out = _fetch_market_data(company_name, market, symbol)
        if out and out.get("current_price"):
            print(f"OK current_price={out['current_price']} {out.get('currency','')} symbol={out.get('symbol','')}")
            return {"ok": True, "data": out}
        print("FAIL empty or no current_price")
        return {"ok": False, "data": out or {}}

    print("=== 拉行情功能测试 (Server B) ===\n")
    print(f"PRICE_SPLIT_ENABLED={PRICE_SPLIT_ENABLED}, OVERSEA_PRICE_API_ENABLED={OVERSEA_PRICE_API_ENABLED}")
    print(f"SERVER_A={SERVER_A_HOST}:{SERVER_A_PORT}\n")

    results = []

    print("1. 港股 腾讯 (0700.HK)")
    results.append(test_single_price("hk", "0700.HK"))
    results.append(test_fetch_market_data("腾讯", "hk", None))
    if quick:
        return results

    print("\n2. A股 贵州茅台 (600519)")
    results.append(test_single_price("cn", "600519"))
    results.append(test_fetch_market_data("贵州茅台", "cn", None))

    print("\n3. 美股 AAPL")
    results.append(test_single_price("us", "AAPL"))
    results.append(test_fetch_market_data("Apple", "us", "AAPL"))

    return results


def main():
    parser = argparse.ArgumentParser(description="拉行情功能测试")
    parser.add_argument("--http", action="store_true", help="通过 HTTP 调用已启动的 B 服务测试")
    parser.add_argument("--base", default="http://127.0.0.1:8001", help="B 服务 base URL（与 --http 同用）")
    parser.add_argument("--quick", action="store_true", help="仅测港股腾讯（约 1 分钟内完成）")
    args = parser.parse_args()

    if args.http:
        print("=== 拉行情 HTTP 测试 (Server B 需已启动) ===\n")
        print(f"Base URL: {args.base}\n")
        results = run_http_tests(args.base)
    else:
        results = run_direct_tests(quick=args.quick)

    ok_count = sum(1 for r in results if r.get("ok"))
    total = len(results)
    print(f"\n--- 结果: {ok_count}/{total} 通过 ---")
    if ok_count == 0:
        print("全部失败，请检查：")
        print("  - 港股/美股：B 能否访问 A（SERVER_A_HOST:PORT），A 能否访问 Yahoo")
        print("  - A 股：本机是否安装 akshare、网络是否可用")
        print("  - 使用 --http 时请确保 B 已启动：./start.sh")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
