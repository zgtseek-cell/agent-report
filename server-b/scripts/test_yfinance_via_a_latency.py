#!/usr/bin/env python3
"""
测试 B 通过 A 获取行情数据的耗时（与后端拉价逻辑一致，走 Chart API，避免 Quote API 限流）

后端对港/美股使用 _fetch_from_oversea_api → Yahoo Chart API (/v8/finance/chart) 经 A 代理；
yfinance 的 tk.info 走 Quote Summary API，易被 Yahoo 429 限流，故本脚本默认测前者。

运行方式（需在 server-b 目录，且已安装依赖）：
  cd server-b && python scripts/test_yfinance_via_a_latency.py [--symbol 0700.HK] [--market hk] [--rounds 3]
  可选 --yf-info：改为测 yf.Ticker().info（易 429，仅用于对比）
"""

import argparse
import os
import sys
import time
from pathlib import Path

SERVER_B_ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="B 经 A 拉取行情耗时测试（默认与后端一致：Chart API）")
    parser.add_argument("--symbol", default="0700.HK", help="股票代码，如 0700.HK / AAPL")
    parser.add_argument("--market", default="hk", help="市场：hk / us（仅用于 Chart 路径）")
    parser.add_argument("--rounds", type=int, default=3, help="重复次数")
    parser.add_argument("--delay", type=float, default=1.0, help="每轮间隔秒数，默认 1")
    parser.add_argument("--yf-info", action="store_true", help="改用 yf.Ticker().info 测耗时（易 429）")
    args = parser.parse_args()

    os.chdir(SERVER_B_ROOT)
    if str(SERVER_B_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_B_ROOT))

    from dotenv import load_dotenv
    load_dotenv(SERVER_B_ROOT / ".env")

    if args.yf_info:
        # 原逻辑：yfinance tk.info（Quote API，易 429）
        try:
            import backend.price  # noqa: F401
            import yfinance as yf
            from yfinance.exceptions import YFRateLimitError
        except ImportError as e:
            print("请先安装依赖: pip install -r requirements.txt")
            print(f"错误: {e}")
            return 1
        use_http = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if use_http:
            print(f"代理: HTTP_PROXY -> {use_http[:50]}...")
        else:
            from backend.config import SERVER_A_HOST, SERVER_A_PORT
            print(f"代理: urlopen -> A ({SERVER_A_HOST}:{SERVER_A_PORT})")
        print(f"模式: yf.Ticker().info（Quote API，易 429）  标的: {args.symbol}  轮数: {args.rounds}\n")
        times = []
        for i in range(args.rounds):
            if i > 0:
                time.sleep(args.delay)
            try:
                tk = yf.Ticker(args.symbol)
                t0 = time.perf_counter()
                info = tk.info
                t1 = time.perf_counter()
                times.append(t1 - t0)
                has = info and (info.get("currentPrice") or info.get("regularMarketPrice"))
                print(f"  第{i+1}轮: {t1-t0:.2f}s  {'(有价格)' if has else '(无)'}")
            except Exception as e:
                print(f"  第{i+1}轮: 失败 - {e}")
                if "YFRateLimitError" in type(e).__name__ or "429" in str(e):
                    print("  (Quote API 限流，建议用默认模式：不传 --yf-info)")
                return 1
        if times:
            print(f"\n  统计: min={min(times):.2f}s  avg={sum(times)/len(times):.2f}s  max={max(times):.2f}s")
        print("\n--- 完成 ---")
        return 0

    # 默认：与后端一致，测 fetch_single_price_with_fallback（Chart API 经 A）
    try:
        from backend.price import fetch_single_price_with_fallback
        from backend.config import SERVER_A_HOST, SERVER_A_PORT
    except ImportError as e:
        print("请先安装依赖并在 server-b 目录运行")
        print(f"错误: {e}")
        return 1

    market = args.market.lower() if args.market else "hk"
    if market not in ("hk", "us"):
        print("--market 需为 hk 或 us（Chart 路径仅用于港/美股）")
        return 1

    print(f"代理: A 的 /api/proxy/extern ({SERVER_A_HOST}:{SERVER_A_PORT})")
    print(f"模式: fetch_single_price_with_fallback（Yahoo Chart API，与后端一致）")
    print(f"标的: {args.symbol}  market={market}  轮数: {args.rounds}  间隔: {args.delay}s\n")

    times = []
    ok_count = 0
    for i in range(args.rounds):
        if i > 0:
            time.sleep(args.delay)
        t0 = time.perf_counter()
        out = fetch_single_price_with_fallback(market, args.symbol)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        times.append(elapsed)
        price = out.get("price")
        err = out.get("error")
        src = out.get("source", "")
        if price and not err:
            ok_count += 1
            print(f"  第{i+1}轮: {elapsed:.2f}s  price={price} {out.get('currency','')}  source={src}")
        else:
            print(f"  第{i+1}轮: {elapsed:.2f}s  失败 - {err or 'no price'}")

    if times:
        print(f"\n  统计: min={min(times):.2f}s  avg={sum(times)/len(times):.2f}s  max={max(times):.2f}s")
    print("\n--- 完成 ---")
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
