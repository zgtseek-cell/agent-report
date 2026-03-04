#!/bin/bash
# =============================================================================
# 服务器 B 专用 · 启动脚本
# =============================================================================
# 部署方式：将【整个 server-b 目录】上传到服务器 B，在该目录下执行：
#   chmod +x start.sh stop.sh
#   ./start.sh
# 本脚本仅在此目录内生效，不依赖项目根目录或 server-a。
# 首次运行前请在 .env 中配置 DEEPSEEK_API_KEY（可复制 .env.example 为 .env 后修改）。
# =============================================================================

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "========================================="
echo "   服务器 B · 一键部署并启动"
echo "   目录: $ROOT"
echo "========================================="
echo ""

echo "[0/6] 停止已运行的服务..."
[ -x "$ROOT/stop.sh" ] && "$ROOT/stop.sh" 2>/dev/null || true
echo ""

echo "[1/6] 创建目录 (logs, feedback)..."
mkdir -p logs feedback
echo ""

echo "[2/6] 准备 Python 环境..."
if command -v conda &>/dev/null; then
    if ! conda info --envs 2>/dev/null | grep -q "stock-advisor"; then
        echo "  创建 conda 环境: stock-advisor (python=3.10)"
        conda create -n stock-advisor python=3.10 -y
    fi
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate stock-advisor
else
    VENV_DIR=""
    for d in .venv venv; do [ -d "$d" ] && { VENV_DIR="$d"; break; }; done
    if [ -z "$VENV_DIR" ]; then
        echo "  创建 venv..."
        python3 -m venv venv
        VENV_DIR=venv
    fi
    source "$VENV_DIR/bin/activate"
fi
echo ""

echo "[3/6] 安装/更新依赖..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo ""

echo "[4/6] 配置 .env..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "  已从 .env.example 复制，请编辑 .env 填写 DEEPSEEK_API_KEY 和 SERVER_A_*"
    else
        echo "  警告: 未找到 .env，请手动创建并配置 DEEPSEEK_API_KEY、SERVER_A_HOST、SERVER_A_PORT 等"
    fi
else
    echo "  使用现有 .env"
fi
set -a
source .env 2>/dev/null || true
set +a

if [ -z "$DEEPSEEK_API_KEY" ] || [ "$DEEPSEEK_API_KEY" = "your_deepseek_api_key_here" ]; then
    echo ""
    echo "========================================="
    echo "   错误: 请先配置 DEEPSEEK_API_KEY"
    echo "========================================="
    echo "  编辑 $ROOT/.env，设置有效的 DEEPSEEK_API_KEY 后重新执行: ./start.sh"
    echo ""
    exit 1
fi
echo "  API Key 已配置"
echo ""

# echo "[5/6] 前端构建..."
# FRONTEND="$ROOT/frontend-react"
# if [ -d "$FRONTEND" ] && [ -f "$FRONTEND/package.json" ]; then
#     if command -v npm &>/dev/null; then
#         if [ "${SKIP_FRONTEND_BUILD:-0}" = "1" ]; then
#             echo "  已设置 SKIP_FRONTEND_BUILD=1，跳过前端构建"
#         else
#             if [ -d "$FRONTEND/node_modules" ]; then
#                 echo "  检测到 node_modules，跳过 npm install"
#             else
#                 echo "  首次安装依赖..."
#                 (cd "$FRONTEND" && npm install --silent)
#             fi
#             echo "  使用低内存模式构建前端..."
#             # 允许构建失败但不中断整个脚本
#             set +e
#             (cd "$FRONTEND" && npm run build:server)
#             BUILD_EXIT=$?
#             set -e
#             if [ $BUILD_EXIT -ne 0 ]; then
#                 echo "  [警告] 前端构建失败(exit=$BUILD_EXIT)，继续使用现有 dist 启动后端"
#             else
#                 echo "  前端已构建完成（低内存模式）"
#             fi
#         fi
#     else
#         echo "  跳过前端构建（未安装 npm），请在本机构建后上传 frontend-react/dist"
#     fi
# else
#     echo "  无 frontend-react，跳过"
# fi
# echo ""

echo "[6/6] 启动后端 (端口 8001)..."
# 为避免系统级代理影响 DeepSeek/yfinance，启动前清理 HTTP(S) 代理环境变量
unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY ALL_PROXY
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 1 \
    >> logs/run.log 2>&1 &
echo $! > logs/server-b.pid
echo "  PID: $(cat logs/server-b.pid)"

sleep 2
if curl -sf http://127.0.0.1:8001/health >/dev/null; then
    echo "  健康检查: 通过"
else
    echo "  健康检查: 未通过，请查看 tail -f logs/run.log"
fi

echo ""
echo "========================================="
echo "   服务器 B 启动完成"
echo "========================================="
echo "  本地: http://127.0.0.1:8001"
echo "  健康: curl http://127.0.0.1:8001/health"
echo "  日志: tail -f $ROOT/logs/run.log"
echo "  停止: $ROOT/stop.sh"
echo ""
