#!/bin/bash
# Server A 公网 Nginx 配置
# 前端在 B；本脚本仅配置 Nginx：/ 及 /api/* 转发到 B，/api/proxy 转本机 8000
# 若 B 在另一台机器，请先修改 nginx/conf.d/*.conf 中 upstream backend_b 的 server 地址

set -e
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_DIR"

NGINX_ONLY=false
[ "$1" = "--nginx-only" ] && NGINX_ONLY=true

NGINX_DIR="$DEPLOY_DIR/nginx"
SSL_SRC="$NGINX_DIR/ssl"
SSL_DEST="/etc/nginx/ssl/stock-advisor"
CONF_FULL="$NGINX_DIR/conf.d/stock-advisor.conf"
CONF_HTTP_ONLY="$NGINX_DIR/conf.d/stock-advisor-http-only.conf"
CONF_DEST="/etc/nginx/conf.d/00-stock-advisor.conf"

echo "=== Server A 公网 Nginx 部署（A、B 为不同服务器）==="
echo "部署目录: $DEPLOY_DIR"

# 从 .env 读取 B 的地址（Nginx 转发目标）
if [ -f "$DEPLOY_DIR/.env" ]; then
    set -a
    source "$DEPLOY_DIR/.env" 2>/dev/null || true
    set +a
fi
SERVER_B_HOST="${SERVER_B_HOST:-}"
SERVER_B_PORT="${SERVER_B_PORT:-8001}"
if [ -z "$SERVER_B_HOST" ]; then
    echo ""
    echo "错误：请在 .env 中配置 SERVER_B_HOST（服务器 B 的 IP 或域名）"
    echo "  例: SERVER_B_HOST=192.168.1.100  或  SERVER_B_HOST=b.example.com"
    exit 1
fi

if ! command -v nginx &>/dev/null; then
    echo ""
    echo "错误：未检测到 Nginx，请先安装："
    echo "  CentOS/阿里云: sudo yum install -y nginx"
    echo "  Ubuntu/Debian: sudo apt install -y nginx"
    exit 1
fi

if [ "$NGINX_ONLY" = false ]; then
    echo ""
    echo "=== 1. 检查 A 代理服务 (8000) ==="
    if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
        echo "  A 代理已运行"
    else
        echo "  警告：请先执行 ./start.sh 启动 A 代理"
    fi
    echo "  转发目标 B: $SERVER_B_HOST:$SERVER_B_PORT"
fi

SSL_OK=false
if [ "$NGINX_ONLY" = true ]; then
    [ -f "$SSL_DEST/origin_certificate.pem" ] && [ -f "$SSL_DEST/private_key.pem" ] && SSL_OK=true
else
    CERT_FILE="" KEY_FILE=""
    for cert in origin_certificate.pem fullchain.pem cert.pem certificate.pem; do
        for key in private_key.pem privkey.pem key.pem; do
            if [ -f "$SSL_SRC/$cert" ] && [ -f "$SSL_SRC/$key" ]; then
                CERT_FILE="$cert"; KEY_FILE="$key"
                break 2
            fi
        done
    done
    if [ -n "$CERT_FILE" ] && [ -n "$KEY_FILE" ]; then
        if grep -q "BEGIN.*CERTIFICATE" "$SSL_SRC/$CERT_FILE" 2>/dev/null && grep -q "BEGIN.*PRIVATE KEY" "$SSL_SRC/$KEY_FILE" 2>/dev/null; then
            echo ""
            echo "=== 2. 部署 SSL 证书 ==="
            sudo mkdir -p "$SSL_DEST"
            sudo cp "$SSL_SRC/$CERT_FILE" "$SSL_DEST/origin_certificate.pem"
            sudo cp "$SSL_SRC/$KEY_FILE" "$SSL_DEST/private_key.pem"
            sudo chmod 600 "$SSL_DEST/private_key.pem"
            SSL_OK=true
        else
            echo "警告：证书或私钥格式无效，将仅启用 HTTP"
        fi
    else
        echo "未找到 ssl/ 证书，将仅启用 HTTP"
    fi
fi

echo ""
echo "=== 3. 配置 Nginx ==="
[ -f /etc/nginx/conf.d/default.conf ] && sudo mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak 2>/dev/null || true
sudo rm -f /etc/nginx/conf.d/stock-advisor.conf 2>/dev/null || true
sudo mkdir -p "$(dirname "$CONF_DEST")"
# 将 B 的地址写入 Nginx 配置
if [ "$SSL_OK" = true ]; then
    echo "安装配置（HTTP + HTTPS），转发到 B: $SERVER_B_HOST:$SERVER_B_PORT"
    sed -e "s/__SERVER_B_HOST__/$SERVER_B_HOST/g" -e "s/__SERVER_B_PORT__/$SERVER_B_PORT/g" "$CONF_FULL" | sudo tee "$CONF_DEST" >/dev/null
else
    echo "安装配置（仅 HTTP），转发到 B: $SERVER_B_HOST:$SERVER_B_PORT"
    sed -e "s/__SERVER_B_HOST__/$SERVER_B_HOST/g" -e "s/__SERVER_B_PORT__/$SERVER_B_PORT/g" "$CONF_HTTP_ONLY" | sudo tee "$CONF_DEST" >/dev/null
fi
if ! sudo nginx -t 2>&1; then
    echo "SSL 加载失败，切换为仅 HTTP"
    sed -e "s/__SERVER_B_HOST__/$SERVER_B_HOST/g" -e "s/__SERVER_B_PORT__/$SERVER_B_PORT/g" "$CONF_HTTP_ONLY" | sudo tee "$CONF_DEST" >/dev/null
    sudo nginx -t || { echo "Nginx 配置失败"; exit 1; }
fi
sudo nginx -s reload

echo ""
echo "=== 部署完成 ==="
[ "$NGINX_ONLY" = true ] && echo "（仅更新 Nginx）"
echo "用户访问本机 80/443 时：/ 与 /api/* 转发到 B，/api/proxy 转发到本机 8000"
echo "A 健康: curl http://127.0.0.1:8000/health"
echo "Nginx 健康: curl http://localhost/health"
echo "日志: tail -f $DEPLOY_DIR/logs/run.log"
echo "停止 A: $DEPLOY_DIR/stop.sh"
