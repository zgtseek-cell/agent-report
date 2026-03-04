#!/bin/bash
# =============================================================================
# 服务器 B 专用 · 停止脚本
# =============================================================================
# 在 server-b 目录下执行: ./stop.sh
# =============================================================================

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "停止服务器 B 后端..."

if [ -f "logs/server-b.pid" ]; then
    PID=$(cat logs/server-b.pid 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "  终止 PID=$PID"
        kill "$PID" 2>/dev/null || true
        sleep 2
        kill -9 "$PID" 2>/dev/null || true
    fi
    rm -f logs/server-b.pid
fi

if command -v pgrep &>/dev/null; then
    PIDS=$(pgrep -f "uvicorn.*backend.main:app.*8001" 2>/dev/null || true)
    [ -z "$PIDS" ] && PIDS=$(pgrep -f "uvicorn.*backend.main:app" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  终止 uvicorn: $PIDS"
        kill $PIDS 2>/dev/null || true
        sleep 2
        kill -9 $PIDS 2>/dev/null || true
    fi
fi

if command -v ss &>/dev/null; then
    PIDS=$(ss -tlnp 2>/dev/null | grep ":8001 " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | tr '\n' ' ')
    if [ -n "$PIDS" ]; then
        for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done
    fi
fi

echo "服务器 B 已停止"
