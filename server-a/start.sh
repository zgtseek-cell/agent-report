#!/bin/bash
# =============================================================================
# 服务器 A 专用 · 启动脚本
# =============================================================================
# 部署方式：将【整个 server-a 目录】上传到服务器 A，在该目录下执行：
#   chmod +x start.sh stop.sh
#   ./start.sh
# 本脚本仅在此目录内生效，不依赖项目根目录或 server-b。
# =============================================================================

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "========================================="
echo "   服务器 A · 一键部署并启动"
echo "   目录: $ROOT"
echo "========================================="
echo ""

echo "[0/5] 停止已运行的服务..."
[ -x "$ROOT/stop.sh" ] && "$ROOT/stop.sh" 2>/dev/null || true
echo ""

echo "[1/5] 创建目录 (logs)..."
mkdir -p logs
echo ""

echo "[2/5] 准备 Python 环境..."
if command -v conda &>/dev/null; then
    if ! conda info --envs 2>/dev/null | grep -q "stock-advisor"; then
        echo "  创建 conda 环境: stock-advisor (python=3.10)"
        conda create -n stock-advisor python=3.10 -y
    fi
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate stock-advisor
else
    [ ! -d "venv" ] && { echo "  创建 venv..."; python3 -m venv venv; }
    source venv/bin/activate
fi
echo ""

echo "[3/5] 安装/更新依赖..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo ""

echo "[4/5] 配置 .env..."
if [ ! -f ".env" ]; then
    if [ -f ".env.deployment" ]; then
        cp .env.deployment .env
        echo "  已从 .env.deployment 复制"
    elif [ -f ".env.example" ]; then
        cp .env.example .env
        echo "  已从 .env.example 复制，请按需修改 .env（API_TOKEN、ALLOWED_DOMAINS 等）"
    else
        echo "  警告: 未找到 .env，请手动创建并配置"
    fi
else
    echo "  使用现有 .env"
fi
echo ""

echo "[5/5] 启动代理服务 (端口 8000)..."
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1 \
    >> logs/run.log 2>&1 &
echo $! > logs/server-a.pid
echo "  PID: $(cat logs/server-a.pid)"

sleep 2
if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "  健康检查: 通过"
else
    echo "  健康检查: 未通过，请查看 tail -f logs/run.log"
fi

echo ""
echo "========================================="
echo "   服务器 A 启动完成"
echo "========================================="
echo "  代理: http://127.0.0.1:8000（/health、/api/proxy/extern）"
echo "  健康: curl http://127.0.0.1:8000/health"
echo "  日志: tail -f $ROOT/logs/run.log"
echo "  停止: $ROOT/stop.sh"
echo "  公网: 配置 Nginx 后执行 $ROOT/setup.sh（将 / 转发到 B，/api/proxy 转本机）"
echo ""
