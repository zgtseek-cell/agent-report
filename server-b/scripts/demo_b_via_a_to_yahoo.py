#!/usr/bin/env python3
"""
最小 Demo：验证 B 通过 A 的代理获取 Yahoo（yfinance）数据是否通。
- 不依赖 backend 包，仅需：pip install httpx（或 python -m pip install httpx）
- 步骤 1：GET A 的 /health，确认 B→A 可达
- 步骤 2：POST A 的 /api/proxy/extern，body 与 B 端 price 模块一致，确认 A→Yahoo→A→B 通

用法（在 server-b 目录或任意目录）：
  export SERVER_A_HOST=8.219.73.160 SERVER_A_PORT=8000   # 可选，默认即此
  python scripts/demo_b_via_a_to_yahoo.py

若在 server-b 下且有 .env，可从 .env 读 SERVER_A_*（本脚本不依赖 dotenv，需手动 source .env 或 export）。
"""

import json
import os
import sys
from datetime import datetime, timedelta

try:
    import httpx
except ImportError:
    print("请先安装 httpx: pip install httpx")
    sys.exit(1)

SERVER_A_HOST = os.environ.get("SERVER_A_HOST", "8.219.73.160")
SERVER_A_PORT = os.environ.get("SERVER_A_PORT", "8000")
SERVER_A_API_TOKEN = os.environ.get("SERVER_A_API_TOKEN", "")
BASE = f"http://{SERVER_A_HOST}:{SERVER_A_PORT}"


def main():
    print("=== Demo: B 经 A 代理访问 Yahoo（yfinance 同款请求）===\n")
    print(f"A 地址: {BASE}")
    print(f"Token: {'已配置' if SERVER_A_API_TOKEN else '未配置'}\n")

    # Step 1: B → A 健康检查
    print("[1] B → A 健康检查 GET /health (timeout 10s) ...")
    try:
        r = httpx.get(f"{BASE}/health", timeout=10.0)
        print(f"    状态: {r.status_code},  body: {r.text.strip()}")
        if r.status_code != 200:
            print("    失败: A 未返回 200，请检查 A 是否启动、端口与防火墙")
            sys.exit(1)
    except Exception as e:
        print(f"    失败: {e}")
        print("")
        print("  【B 无法访问 A 时排查清单】")
        print("  1. 在 A 上确认后端已启动: curl -s http://127.0.0.1:8000/health")
        print("  2. A 的 uvicorn 需监听 0.0.0.0:8000（不能只监听 127.0.0.1）")
        print("  3. A 服务器/云安全组：放行入站 TCP 8000，来源为 B 的 IP 或 0.0.0.0/0")
        print("  4. A 本机防火墙（firewalld/iptables）：放行 8000 端口")
        print("  5. 在 B 上测试: curl -v --connect-timeout 5 http://<A公网IP>:8000/health")
        sys.exit(1)
    print("    OK B→A 可达\n")

    # Step 2: B → A → Yahoo（与 price._fetch_from_oversea_api 完全一致的 body）
    trade_date = datetime.now().strftime("%Y-%m-%d")
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_date = int(dt.timestamp())
    end_date = int((dt + timedelta(days=1)).timestamp())
    yfinance_url = "https://query1.finance.yahoo.com/v8/finance/chart/0700.HK"
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
    proxy_url = f"{BASE}/api/proxy/extern"
    if SERVER_A_API_TOKEN:
        from urllib.parse import quote
        proxy_url = f"{proxy_url}?token={quote(SERVER_A_API_TOKEN, safe='')}"

    print("[2] B → A → Yahoo  POST /api/proxy/extern (timeout 45s) ...")
    try:
        r = httpx.post(
            proxy_url,
            json=proxy_request,
            headers={"Content-Type": "application/json"},
            timeout=45.0,
        )
        print(f"    状态: {r.status_code}")
        if r.status_code != 200:
            print(f"    body: {r.text[:500]}")
            print("    失败: A 代理返回非 200（可能是 A 鉴权、域名白名单或 A→Yahoo 失败）")
            sys.exit(1)
        data = r.json()
        status_code = data.get("status_code")
        content = data.get("content", "")
        print(f"    上游 status_code: {status_code}, content 长度: {len(content)}")
        if status_code != 200:
            print(f"    content 前 300 字: {content[:300]}")
            print("    说明: A 已收到 B 的请求并转发，但 Yahoo 返回非 200")
            sys.exit(1)
        # 解析是否含 chart.result（与 price 模块一致）
        try:
            j = json.loads(content)
            if "chart" in j and "result" in j["chart"] and len(j["chart"]["result"]) > 0:
                meta = j["chart"]["result"][0].get("meta", {})
                price = meta.get("regularMarketPrice")
                print(f"    解析成功: regularMarketPrice = {price}")
                print("    OK B→A→Yahoo 全链路通，yfinance 可通过 A 获取数据")
            else:
                print(f"    content 前 200 字: {content[:200]}")
                print("    说明: Yahoo 返回 200 但结构无 chart.result，可能被限流或格式变化")
        except json.JSONDecodeError as e:
            print(f"    content 前 200 字: {content[:200]}")
            print(f"    解析 JSON 失败: {e}")
    except httpx.TimeoutException as e:
        print(f"    失败: 超时 {e}")
        print("    说明: B→A 或 A→Yahoo 在 45s 内未返回，请检查 A 到 Yahoo 的网络或增大 timeout")
        sys.exit(1)
    except Exception as e:
        print(f"    失败: {e}")
        sys.exit(1)
    print("")
    sys.exit(0)


if __name__ == "__main__":
    main()
