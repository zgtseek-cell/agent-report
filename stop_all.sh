#!/bin/bash
# 停止 Server A 与 Server B

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "========================================="
echo "   停止全部服务 (A + B)"
echo "========================================="
echo ""

if [ -d "server-a" ] && [ -x "server-a/stop.sh" ]; then
    echo ">>> 停止 Server A..."
    (cd server-a && ./stop.sh)
    echo ""
fi

if [ -d "server-b" ] && [ -x "server-b/stop.sh" ]; then
    echo ">>> 停止 Server B..."
    (cd server-b && ./stop.sh)
    echo ""
fi

echo "========================================="
echo "   全部已停止"
echo "========================================="
