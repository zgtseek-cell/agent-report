## 项目速览（供 AI/Agent 使用）

- **项目名**：股票智能顾问（Stock Advisor）
- **核心功能**：给定公司名称/市场/仓位等信息，获取行情和部分财务数据，调用 DeepSeek LLM 生成价值投资视角的分析报告，并提供 DCF / PE Band 等可视化看板。
- **部署形态**：Server A（公网代理 + Nginx） + Server B（核心业务 + 前端），推荐一键脚本 `./deploy.sh` 启动两端，或参见 `DEPLOYMENT.md`。

---

## 架构总览

- **Server A（仅代理，公网）**
  - 位置：`server-a/`
  - 职责：
    - 公网 Nginx：对外唯一入口（80/443），把 `/` 与 `/api/*` 反向代理到 Server B，仅 `/api/proxy/extern` 反向代理到本机 8000。
    - 本机 FastAPI（8000）：只提供：
      - `GET /health`：健康检查。
      - `POST /api/proxy/extern`：外网代理接口（服务 B 调用，用于访问 yfinance 等，带域名白名单和 API token 鉴权）。
    - 可选：端口代理模式（`PROXY_PORT`）——启动 HTTP(S) 代理，Server B 可通过 `HTTP_PROXY/HTTPS_PROXY` 使用。

- **Server B（核心业务 + 前端）**
  - 位置：`server-b/`
  - 职责：
    - FastAPI 后端：
      - `/api/analyze_sse`：主分析接口（SSE），调用 DeepSeek 流式返回 Markdown 报告，同时发送 meta 信息（标的、市场等）。
      - 价格服务：`/api/price`、`/api/price/batch` 等，A 股用本地 akshare，港/美股经 Server A 代理访问 yfinance，并带缓存与交易日回退逻辑。
      - 财务/估值接口：`/api/financials`、`/api/dcf`、`/api/pepb-band`，为前端财务看板提供数据。
      - 其它：反馈、PDF 导出、健康检查等（都在 `backend/main.py`）。
    - React 前端（Vite）：
      - 单页三视图：输入表单（InputForm）→ 分析报告（ReportView，SSE）→ 财务看板（FinancialDashboard）。
      - 构建产物 `frontend-react/dist` 由 FastAPI 挂载在 `/`，通过 Server A 的 Nginx 对外暴露。

---

## 关键请求链路（一次分析）

1. **打开页面**
   - 浏览器 `GET /` →
   - Server A · Nginx `location /` → `proxy_pass` 到 B（8001） →
   - Server B 返回前端静态资源（`frontend-react/dist`）→ 浏览器渲染 `App.jsx`（默认视图为 `InputForm`）。

2. **提交分析**
   - 前端 `InputForm` 收集：`companyName`, `market`, `symbol`, `position`, `extraPrompt`。
   - 点击“开始分析”：
     - 未确认风险 → 弹 `RiskModal`，确认后写 `localStorage` 标记。
     - 已确认 → `App` 设置 `analysisState`，切换 `view='report'`，挂载 `ReportView`。

3. **前端 SSE 连接**
   - `ReportView` 构造 `EventSource(apiUrl('/api/analyze_sse?...'))`。
   - 请求同源发往 Server A → Nginx `/api/analyze_sse` → 反向代理到 Server B（8001）。

4. **Server B 后端逻辑（简化版）**
   - 解析公司名 → `resolve_company`（有限缓存 + LLM 解析 + `_map_to_symbol` 兜底）。
   - 通过 `price.fetch_single_price_with_fallback(market, symbol)` 获取价格：
     - A 股：本地 akshare。
     - 港/美股：优先用 Server A 海外接口（yfinance，经 `/api/proxy/extern` 或端口代理），失败则本地 yfinance。
     - 使用 Redis + SQLite 做缓存，并自动处理非交易日（回退到最近交易日，最多多次回退）。
   - 将结果组装为 `internal_market_data`。
   - 使用 `SYSTEM_PROMPT`（“顶级价值投资分析师”）与 `build_user_prompt` 构造 Prompt。
   - 调用 DeepSeek（`OpenAI` 兼容库，`client.chat.completions.create(..., stream=True)`）。
   - 通过 SSE 向前端依次推送：
     - `{"type": "status", ...}`：阶段性状态文本。
     - `{"type": "meta", ...}`：标的元信息（写入历史记录 & 财务看板入口）。
     - Markdown 正文 chunk。
     - 结束标记：`[DONE]`。

5. **Server A Nginx 转发 SSE**
   - 按 chunk 原样转发 B 的 SSE 响应（需要关闭缓冲并拉长 `proxy_read_timeout`）。

6. **前端渲染与后续看板**
   - `ReportView`：
     - 解析 status/meta 事件，动态更新状态条和历史记录。
     - 将 Markdown 内容累积到 `reportContent`，通过 `marked + DOMPurify` 渲染。
     - 接收到 meta 时允许用户点击“财务看板”进入后续界面。
   - `FinancialDashboard`：
     - 从 meta 或 `analysisState` 提取 `symbol/market`。
     - 并行请求 `/api/financials`、`/api/dcf`、`/api/pepb-band`。
     - 使用 ECharts 展示营收/利润趋势、DCF 现金流、PE Band 等。

---

## 目录与文件速查

- **根目录**
  - `DEPLOYMENT.md`：完整部署说明（含 docker-compose）。
  - `deploy.sh` / `stop_all.sh`：一键启动/停止 A+B。
  - `docs/用户请求页面整体流程.md`：端到端流程图，是理解架构的首选文档。
  - `重构报告.md`：记录从旧架构到“Server A 仅代理 + Server B 合并核心逻辑”的重构要点。

- **Server A（`server-a/`）**
  - `backend/main.py`：仅代理后端；定义 `/api/proxy/extern` 与 `PROXY_PORT` 端口代理。
  - `nginx/conf.d/stock-advisor.conf`：公网 Nginx 配置（/ 与 /api/* 转发到 B，静态资源缓存，/health 等）。
  - `start.sh` / `stop.sh` / `setup.sh`：启动代理服务、生成并应用 Nginx 配置。
  - `.env.example`：示例变量（`SERVER_B_HOST`, `SERVER_B_PORT`, `API_TOKEN`, `ALLOWED_DOMAINS`, `PROXY_PORT` 等）。

- **Server B（`server-b/`）**
  - `backend/main.py`：核心 API（/api/analyze_sse、价格接口、财务接口、反馈等）。
  - `backend/price.py`：价格拆分逻辑 + Server A 代理适配 + Redis/SQLite 缓存 + 交易日日历。
  - `backend/config.py`：统一配置中心，从 `config.yaml` + 环境变量加载 DeepSeek、Server A、Redis、价格等配置。
  - 其它 backend 模块：公司解析缓存、Redis 封装、财务与估值计算等。
  - `frontend-react/`：
    - `App.jsx`：视图切换与全局状态管理。
    - `components/InputForm.jsx`：首页表单与历史记录。
    - `components/ReportView.jsx`：SSE 连接与分析报告渲染。
    - `components/FinancialDashboard.jsx`：财务可视化看板。
    - `FRONTEND-OVERVIEW.md`：前端架构说明，包含 API 调用和常见问题排查。

---

## 配置要点（环境变量/配置）

- **Server A `.env`**
  - `SERVER_B_HOST`, `SERVER_B_PORT`：指向 Server B。
  - `API_TOKEN`：Server B 调 `/api/proxy/extern` 的鉴权 token。
  - `ALLOWED_DOMAINS`：yfinance 域名白名单。
  - `PROXY_PORT`, `PROXY_HOST`（可选）：启用端口代理时使用。

- **Server B `.env` / `config.yaml`**
  - DeepSeek：
    - `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `DEEPSEEK_TIMEOUT`。
  - 价格服务：
    - `PRICE_SPLIT_ENABLED=true`：开启 A 股本地 + 港/美股经 A 拆分。
    - `OVERSEA_PRICE_API_ENABLED=true`：启用基于 Server A 的海外价格接口。
  - Server A：
    - `SERVER_A_HOST`, `SERVER_A_PORT`, `SERVER_A_API_TOKEN`。
    - `USE_HTTP_PROXY` + `SERVER_A_PROXY_PORT`：若使用端口代理模式。
  - 缓存：
    - `REDIS_ENABLED` + `REDIS_HOST/PORT/DB/...`，以及价格缓存 DB 路径 `PRICE_CACHE_DB_PATH`。

---

## 给后续 AI/Agent 的使用建议

- **想快速理解整体架构**：先读本文件，再看 `docs/用户请求页面整体流程.md` 与 `server-b/frontend-react/FRONTEND-OVERVIEW.md`。
- **想改动分析逻辑**：定位到 `server-b/backend/main.py`（LLM 调用与 Prompt）、`price.py`（行情与缓存）、相关估值模块。
- **想排查“无法连接分析服务/SSE 中断”**：重点检查：
  - Nginx 是否正确将 `/api/analyze_sse` 代理到 B，超时时间是否足够；
  - B 端 `/api/analyze_sse` 是否正常启动、是否在长时间等待行情；
  - A 的 `/api/proxy/extern` 与 B 的价格服务是否工作正常。
- **想扩展财务看板或分析维度**：先改 Server B 的相应 API，再在 `FinancialDashboard.jsx` 或新的前端组件中消费这些数据。

