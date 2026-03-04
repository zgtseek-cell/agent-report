# Server B - 前端 + 业务（股票智能顾问）

**部署约定**：A 服务器部署 **server-a** 目录内容；B 服务器部署 **server-b** 目录内容。

基于 DeepSeek 的股票分析，支持港股/美股/A 股。  
**前端与业务 API 均在 B**：公网用户经 A 的 Nginx 访问，Nginx 将请求转发到 B（本机 8001）。

## 目录结构

```
server-b/
├── backend/           # FastAPI：分析、价格、反馈等 API
├── frontend-react/    # 前端源码，构建后由 B 提供
│   ├── src/
│   ├── package.json
│   └── dist/         # 构建产物（start.sh 可自动构建）
├── logs/
├── feedback/
├── .env.example
├── start.sh           # 一键部署并启动（含前端构建）
├── stop.sh
└── README.md
```

## 快速开始

```bash
cp .env.example .env
# 编辑 .env：DEEPSEEK_API_KEY、SERVER_A_HOST、SERVER_A_PORT 等
chmod +x start.sh stop.sh
./start.sh
```

详见 [DEPLOY.md](DEPLOY.md)。
