#!/bin/bash
# 一键部署并启动 Server A、Server B（或仅启动其一）
# 用法: ./deploy.sh [all|a|b]  默认 all

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

MODE="${1:-all}"

echo "========================================="
echo "   股票智能顾问 - 一键部署启动"
echo "   模式: $MODE"
echo "========================================="
echo ""

start_a() {
    if [ ! -d "server-a" ]; then
        echo "错误: 未找到 server-a 目录"
        return 1
    fi
    echo ">>> 启动 Server A..."
    (cd server-a && chmod +x start.sh 2>/dev/null; ./start.sh)
    echo ""
}

start_b() {
    if [ ! -d "server-b" ]; then
        echo "错误: 未找到 server-b 目录"
        return 1
    fi
    echo ">>> 启动 Server B..."
    (cd server-b && chmod +x start.sh 2>/dev/null; ./start.sh)
    echo ""
}

case "$MODE" in
    all)
        start_a
        start_b
        echo "========================================="
        echo "   全部启动完成"
        echo "   A: http://127.0.0.1:8000  B: http://127.0.0.1:8001"
        echo "   停止全部: $ROOT/stop_all.sh"
        echo "========================================="
        ;;
    a|A|server-a)
        start_a
        echo "停止 A: $ROOT/server-a/stop.sh"
        ;;
    b|B|server-b)
        start_b
        echo "停止 B: $ROOT/server-b/stop.sh"
        ;;
    *)
        echo "用法: $0 [all|a|b]"
        echo "  all  默认，先启动 A 再启动 B"
        echo "  a    仅启动 Server A (端口 8000)"
        echo "  b    仅启动 Server B (端口 8001)"
        exit 1
        ;;
esac
