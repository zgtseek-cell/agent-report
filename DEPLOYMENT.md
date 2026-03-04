# 部署指南

本项目已重构为 Server A（代理）和 Server B（核心业务）两部分，以下是部署步骤。

## 一键部署与停止（推荐）

### 一键启动（A + B）

在项目根目录执行（自动创建 venv/conda、安装依赖、生成 .env、启动服务）：

```bash
chmod +x deploy.sh stop_all.sh server-a/start.sh server-a/stop.sh server-b/start.sh server-b/stop.sh
./deploy.sh
```

- `./deploy.sh` 或 `./deploy.sh all`：先启动 Server A (8000)，再启动 Server B (8001)
- `./deploy.sh a`：仅启动 Server A
- `./deploy.sh b`：仅启动 Server B

**首次运行前**：在 `server-b/.env` 中配置 `DEEPSEEK_API_KEY`（若从 `.env.example` 复制后未改，B 启动会报错并提示）。

### 一键停止

```bash
./stop_all.sh
```

或分别停止：

```bash
./server-a/stop.sh
./server-b/stop.sh
```

### 单机部署 A 或 B

```bash
# 仅 A（代理 + 前端）
cd server-a && ./start.sh

# 仅 B（核心分析）
cd server-b && ./start.sh
```

停止：在对应目录执行 `./stop.sh`。

## 环境要求

- Python 3.8+
- pip
- Redis（可选，用于缓存）

## 部署前准备

### 1. 安装依赖

```bash
# Server A
cd server-a
pip install -r requirements.txt

# Server B
cd server-b
pip install -r requirements.txt
```

### 2. 配置环境变量

#### Server A
创建 `.env` 文件，内容如下：
```env
# Server B 配置
SERVER_B_HOST=127.0.0.1
SERVER_B_PORT=8001

# API 鉴权配置（可选，防止外网滥用）
API_TOKEN=your_token

# 允许代理的域名白名单（仅允许 yfinance 相关域名）
ALLOWED_DOMAINS=query1.finance.yahoo.com,query2.finance.yahoo.com,finance.yahoo.com,s.yimg.com,image.yahoo.com

# 端口代理（可选）：非 0 时在 PROXY_PORT 上启动 HTTP(S) 代理，B 可设 HTTP_PROXY 使用，yfinance 逻辑在 B、外网经 A
# PROXY_PORT=8080
# PROXY_HOST=0.0.0.0
```

#### Server B
创建 `.env` 文件，内容如下：
```env
# DeepSeek API 配置（必填）
DEEPSEEK_API_KEY=your_deepseek_api_key

# 价格服务拆分配置
PRICE_SPLIT_ENABLED=true
OVERSEA_PRICE_API_ENABLED=true
SERVER_A_HOST=127.0.0.1
SERVER_A_PORT=8000

# Server A 代理配置（可选）
SERVER_A_API_TOKEN=your_token

# 端口代理模式（可选）：A 开启 PROXY_PORT 时，B 设 USE_HTTP_PROXY=true、SERVER_A_PROXY_PORT=8080，外网经 A 端口代理
# USE_HTTP_PROXY=true
# SERVER_A_PROXY_PORT=8080

# Redis 配置（可选）
REDIS_ENABLED=true
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

## 启动服务器

### Linux/macOS（推荐：一键脚本）

```bash
# 项目根目录一键启动 A+B
./deploy.sh

# 或分别启动
cd server-a && ./start.sh   # 端口 8000
cd server-b && ./start.sh   # 端口 8001，需先配置 DEEPSEEK_API_KEY
```

### Windows 系统

在 `server-a` 或 `server-b` 目录下用 Python 直接启动（需先安装依赖并配置 .env）：

```cmd
cd server-a
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

cd server-b
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

### 仅前台运行（不推荐生产）

```bash
# Server A
cd server-a && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Server B
cd server-b && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

## 验证部署

### 检查服务器是否正常运行

```bash
# Server A 健康检查
curl http://127.0.0.1:8000/health

# Server B 健康检查
curl http://127.0.0.1:8001/health
```

### 测试价格查询接口

```bash
# 测试 Server B 的价格查询接口（美国市场 Apple 股票）
curl "http://127.0.0.1:8001/api/price?market=us&symbol=AAPL&trade_date=2024-10-24"
```

### 测试 SSE 分析接口

```bash
# 测试 Server A 的 SSE 分析接口（代理到 Server B）
curl "http://127.0.0.1:8000/api/analyze_sse?company_name=Apple"
```

## 部署方式

### 方式一：直接运行（开发环境）

按照上述启动步骤直接运行即可。

### 方式二：使用 systemd（Linux 生产环境）

#### Server A
创建 `/etc/systemd/system/server-a.service` 文件：
```ini
[Unit]
Description=Stock Advisor Server A
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/server-a
ExecStart=/usr/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### Server B
创建 `/etc/systemd/system/server-b.service` 文件：
```ini
[Unit]
Description=Stock Advisor Server B
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/server-b
ExecStart=/usr/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --log-level info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
# 启动 Server A
sudo systemctl start server-a
sudo systemctl enable server-a

# 启动 Server B
sudo systemctl start server-b
sudo systemctl enable server-b

# 查看日志
sudo journalctl -u server-a -f
sudo journalctl -u server-b -f
```

### 方式三：使用 Docker（推荐）

#### Server A
创建 `Dockerfile`：
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
```

#### Server B
创建 `Dockerfile`：
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
```

创建 `docker-compose.yml`：
```yaml
version: '3'
services:
  server-a:
    build: ./server-a
    ports:
      - "8000:8000"
    environment:
      - SERVER_B_HOST=server-b
      - SERVER_B_PORT=8001
      - API_TOKEN=your_token
    networks:
      - stock-advisor-network

  server-b:
    build: ./server-b
    ports:
      - "8001:8001"
    environment:
      - DEEPSEEK_API_KEY=your_deepseek_api_key
      - PRICE_SPLIT_ENABLED=true
      - OVERSEA_PRICE_API_ENABLED=true
      - SERVER_A_HOST=server-a
      - SERVER_A_PORT=8000
      - SERVER_A_API_TOKEN=your_token
    networks:
      - stock-advisor-network

  redis:
    image: redis:latest
    ports:
      - "6379:6379"
    networks:
      - stock-advisor-network

networks:
  stock-advisor-network:
    driver: bridge
```

启动服务：
```bash
docker-compose up -d
```

## 常见问题

### 1. 端口被占用

如果端口 8000 或 8001 被占用，可以通过以下方式解决：

```bash
# 查找占用端口的进程
lsof -i :8000  # Linux/macOS
netstat -ano | findstr :8000  # Windows

# 终止进程
kill -9 <PID>  # Linux/macOS
taskkill /PID <PID> /F  # Windows
```

### 2. 价格查询接口返回错误

如果价格查询接口返回"指定日期未查询到价格"，可能是以下原因：
- 日期不是交易日
- 股票代码错误
- 网络连接问题
- Server A 代理接口未正常工作

### 3. 分析接口返回错误

如果分析接口返回错误，可能是以下原因：
- DeepSeek API 密钥无效
- Server A 代理接口未正常工作
- Server B 未正常运行

## 监控和日志

### Server A 日志
存储在 `server-a/logs/` 目录下。

### Server B 日志
存储在 `server-b/logs/` 目录下。

## 故障排除

如果遇到问题，可以查看服务器日志，并参考常见问题部分。
