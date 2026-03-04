# Server A - 仅代理（公网 Nginx + 外网代理）

**部署约定**：A 服务器部署 **server-a** 目录内容；B 服务器部署 **server-b** 目录内容。

**A、B 为不同服务器**。A 部署在公网，只做两件事：  
1. **Nginx**：接收用户请求，将 `/` 与 `/api/*` 转发到 **服务器 B**（前端与业务在 B），仅 `/api/proxy` 转发到本机 8000。  
2. **本机 8000**：提供 `/health`、`/api/proxy/extern`，供 B 访问外网（如 yfinance）。

前端在 B，A 不提供静态页面。

## 目录结构

```
server-a/
├── backend/           # 仅代理：/health、/api/proxy/extern
├── nginx/             # Nginx 配置（/ → B，/api/proxy → 本机 8000）
├── logs/
├── .env.example
├── start.sh           # 启动本机代理 (8000)
├── stop.sh
├── setup.sh           # 配置 Nginx（需先启动 B，并确认 nginx 中 B 地址）
└── README.md
```

## 快速开始

1. **上传** server-a 到服务器 A。  
2. **配置**：`cp .env.example .env`，**必须填写** `SERVER_B_HOST`（服务器 B 的 IP 或域名）、`SERVER_B_PORT`（默认 8001），按需改 `API_TOKEN`。  
3. **启动 A 代理**：`chmod +x start.sh stop.sh && ./start.sh`。  
4. **确认 B 已启动**（B 在另一台机器，提供前端与 API）。  
5. **配置 Nginx**：`chmod +x setup.sh && ./setup.sh`（会从 .env 读取 B 地址并写入 Nginx）。

## 管理命令

```bash
./start.sh              # 启动代理
./stop.sh               # 停止
./setup.sh              # 配置 Nginx
./setup.sh --nginx-only # 仅更新 Nginx 配置
tail -f logs/run.log    # 日志
curl http://127.0.0.1:8000/health  # 健康检查
```

## 健康检查

- 本机代理：`curl http://127.0.0.1:8000/health`
- Nginx：`curl http://localhost/health`
