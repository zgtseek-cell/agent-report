#!/bin/bash
# 快速同步文件到远程服务器
# 用法: ./sync.sh <user@host> [remote_path]

set -e

if [ $# -lt 1 ]; then
    echo "用法: $0 <user@host> [remote_path]"
    echo ""
    echo "示例:"
    echo "  $0 user@192.168.1.100"
    echo "  $0 user@192.168.1.100 /opt/stock-advisor"
    echo ""
    echo "其他方式:"
    echo "  - 使用 rsync: rsync -avz --delete ./ user@host:/path/"
    echo "  - 使用 scp:   scp -r ./ user@host:/path/"
    echo "  - 使用 git:   git push && ssh user@host 'cd /path && git pull'"
    exit 1
fi

REMOTE_HOST="$1"
REMOTE_PATH="${2:-/opt/stock-advisor}"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================="
echo "  同步文件到远程服务器"
echo "  本地: $LOCAL_DIR"
echo "  远程: $REMOTE_HOST:$REMOTE_PATH"
echo "========================================="
echo ""

# 检查是否可以连接
echo ">>> 检查远程连接..."
if ! ssh "$REMOTE_HOST" "test -d \"$REMOTE_PATH\" || mkdir -p \"$REMOTE_PATH\""; then
    echo "错误: 无法连接到远程服务器或创建目录"
    exit 1
fi

echo ""
echo ">>> 使用 rsync 同步 (增量同步, 最快)..."
echo "    注意: 会删除远程端不存在于本地的文件 (--delete)"
echo ""
read -p "确认继续? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 执行同步 - 排除不需要的文件
rsync -avz --delete \
    --exclude '.git/' \
    --exclude '.gitignore' \
    --exclude '.claude/' \
    --exclude '.env' \
    --exclude '*.log' \
    --exclude 'logs/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'venv/' \
    --exclude '.venv/' \
    --exclude 'node_modules/' \
    --exclude 'dist/' \
    --exclude 'price_cache.db' \
    --exclude 'company_cache.json' \
    --exclude 'feedback/' \
    "$LOCAL_DIR/" \
    "$REMOTE_HOST:$REMOTE_PATH/"

echo ""
echo "========================================="
echo "  同步完成!"
echo "  下一步:"
echo "    1. ssh $REMOTE_HOST"
echo "    2. cd $REMOTE_PATH"
echo "    3. 配置 .env 文件"
echo "    4. ./deploy.sh"
echo "========================================="
