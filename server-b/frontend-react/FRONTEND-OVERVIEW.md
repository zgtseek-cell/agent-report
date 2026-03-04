# 前端展示与交互逻辑说明（供 AI/开发者快速定位问题）

本文档描述 **server-b/frontend-react** 的页面结构、组件职责、状态流、API 调用与样式约定，便于快速理解与排查问题。

---

## 1. 技术栈与入口

- **框架**: React 18，无路由（单页三视图切换）
- **构建**: Vite
- **样式**: Tailwind CSS + 少量 `@layer components` 类（见 `index.css`）
- **图标**: lucide-react
- **图表**: echarts-for-react（仅财务看板）
- **Markdown 渲染**: marked + DOMPurify（分析报告正文）
- **入口**: `main.jsx` → `App.jsx`，根节点 id=`root`

---

## 2. 整体视图与状态（App.jsx）

### 2.1 视图状态

- **`view`**: `'form'` | `'report'` | `'dashboard'`
  - **form**: 首页，输入公司/市场/仓位并「开始分析」
  - **report**: 分析结果流式展示页（SSE）
  - **dashboard**: 财务可视化看板（需从 report 页通过「财务看板」进入，会带 meta 数据）

### 2.2 主要状态

| 状态 | 类型 | 说明 |
|------|------|------|
| `analysisState` | object | 当前分析请求参数：`companyName`, `market`, `symbol`, `position`, `extraPrompt`；从表单提交或历史选择写入，report/dashboard 只读使用 |
| `reportContent` | string | 分析报告正文（Markdown 原文），由 ReportView 通过 SSE 追加，用于展示与下载 |
| `marketData` | object \| null | 从 report 页点「财务看板」时传入的 meta（含 `market`, `symbol` 等），dashboard 用其与 `analysisState` 一起取 symbol/market |
| `history` | array | 历史记录（localStorage `stock_advisor_history`），最多 20 条，按 market+symbol 去重 |
| `showRiskModal` | boolean | 是否显示风险确认弹窗；首次点「开始分析」未确认过则弹出 |

### 2.3 关键交互流

1. **开始分析**: 用户点「开始分析」 → 若未确认风险则 `setShowRiskModal(true)`，否则 `startAnalysis(data)` → `setAnalysisState(data)`、`setView('report')`、清空 `reportContent` 与 `marketData`。
2. **返回**: 任意非 form 视图下点「返回」 → `setView('form')`，清空 report/dashboard 相关状态。
3. **进入财务看板**: 仅在 `view === 'report'` 且已有 `metaInfo` 时显示「财务看板」按钮；点击 → `onShowDashboard(metaInfo)` → `setMarketData(metaInfo)`、`setView('dashboard')`。dashboard 的 symbol/market 来自 `marketData || analysisState`。
4. **历史记录**: 表单内「历史查询」下拉选择一条 → `onSelectHistory(item)` → `setAnalysisState(item)` 并 `startAnalysis(item)`，即用历史参数直接进入 report 并重新发起 SSE。

### 2.4 全局 UI

- **Header**: 固定顶部；form 时显示标题「股票智能顾问」；非 form 时显示「返回」；report 且已有 marketData 时显示「财务看板」。
- **RiskModal**: 风险提示弹窗，确认后写 localStorage `stock_advisor_risk_ack`，之后不再弹出。
- **ErrorBoundary**: 包住整棵 App 树，未捕获错误时展示「页面加载异常」+ 错误信息 + 重试按钮，避免整页空白。

---

## 3. 组件说明

### 3.1 InputForm（首页表单）

- **文件**: `components/InputForm.jsx`
- **Props**: `history`, `onStartAnalysis`, `onSelectHistory`
- **本地状态**: `companyName`, `market`, `symbol`, `position`, `extraPrompt`；输入公司名时清空 symbol。
- **表单项**:
  - 公司名称（必填）、历史查询（下拉）、市场（auto/hk/us/cn）、股票代码、当前仓位（0–100 滑块）、补充要求（文本框 + 快捷标签）。
- **提交**: `onStartAnalysis({ companyName, market, symbol, position, extraPrompt })`；公司名为空不提交。
- **样式**: `glass-panel` 容器，`input-glow` 输入框，`btn-primary` 提交按钮；底部免责小字。

### 3.2 ReportView（分析结果流式页）

- **文件**: `components/ReportView.jsx`
- **Props**: `analysisState`, `reportContent`, `setReportContent`, `onShowDashboard`, `onSaveHistory`
- **本地状态**: `isLoading`, `isStreaming`, `statusText`, `metaInfo`, `autoScroll`；ref：`outputRef`（滚动容器）、`eventSourceRef`（EventSource 实例）。
- **SSE 连接**: 挂载时用 `apiUrl(\`/api/analyze_sse?${params}\`)` 创建 EventSource，params 来自 `analysisState`（company_name, market, symbol, extra_prompt, position）。依赖变更会重新挂载并重连。
- **SSE 事件处理**:
  - `data === '[DONE]'`: 结束，关闭连接，状态「分析完成 ✅」。
  - JSON 且 `type === 'status'`: 更新 `statusText` 为 `data.message`（如「正在获取行情…」）。
  - JSON 且 `type === 'meta'`: 存 `metaInfo`，调用 `onSaveHistory` 写历史，状态「正在获取公司信息…」。
  - JSON 且 `type === 'metrics'`: 预留，当前仅忽略。
  - 其他: 当作 Markdown 正文追加到 `reportContent`；首段正文到达时设为「正在深度分析中…」。
- **onerror**: 关闭连接，状态「分析中断，请重试」，并在正文后追加「[错误] 连接分析服务失败，请稍后重试。」。
- **展示**: 顶部显示「分析结果」+ meta 的 market/symbol + statusText；右侧按钮「财务看板」（需 metaInfo）、「保存」；正文区域用 `markdown-body` + `dangerouslySetInnerHTML` 渲染 DOMPurify(marked(reportContent))；流式时若用户上滑则显示「自动滚动」按钮。
- **下载**: 将 `reportContent` 以 Markdown 文件下载，文件名含公司名与日期。

**排查「连接分析服务失败」时**：确认 Network 里是否有对 **`/api/analyze_sse?...`** 的请求（EventSource），以及该请求是否超时/4xx/5xx；本仓库没有 `/api/sse/monitor` 等其它 SSE 路径。

### 3.3 FinancialDashboard（财务看板）

- **文件**: `components/FinancialDashboard.jsx`
- **Props**: `marketData`, `analysisState`；用 `symbol` / `market` = `marketData?.symbol` 等 ?? `analysisState?.symbol` 等。
- **本地状态**: `financialData`, `dcfData`, `pepbData`（三个 API 的响应），`loading`，`activeTab`（`'overview'` | `'dcf'` | `'pepb'`）。
- **数据请求**: 当存在 `symbol` 时，`useEffect` 中并行请求三个接口（同源通过 `apiUrl()`）：
  - `GET /api/financials?symbol=...&market=...` → `financialData`（利润表图表）
  - `GET /api/dcf?symbol=...&market=...` → `dcfData`（当前价、内在价值、安全边际、建议、DCF 图与参数）
  - `GET /api/pepb-band?symbol=...&market=...` → `pepbData`（PE Band 图）
- **Tab**:
  - **概览**: 4 张 KpiCard（当前股价、内在价值、安全边际、建议）+ 财务趋势图（营收/净利润/EBITDA，来自 financialData）。
  - **DCF 估值**: 估值参数卡片 + DCF 现金流图（dcfData）。
  - **PE/PB Band**: 单图 peChartOption（pepbData）。
- **空数据**: 接口失败或返回 0 时，KPI 显示「—」，图表不渲染或显示「暂无数据」；有「刷新数据」按钮可重新请求。
- **子组件**: `KpiCard({ title, value, icon, color })`，color 取 emerald/blue/green/yellow/red/slate 对应不同前景色。

**排查看板全空时**：查 Network 里上述三个 API 是否 200、响应体是否含 `chart`/`raw`/`valuation` 等约定字段；若 404 则后端未实现或路径不一致。

### 3.4 RiskModal（风险确认弹窗）

- **文件**: `components/RiskModal.jsx`
- **Props**: `isOpen`, `onClose`, `onConfirm`
- **行为**: 遮罩 + 居中玻璃卡片；内容为免责与风险条款；「取消」调用 onClose，「我已了解并同意」调用 onConfirm（App 里会写 risk_ack 并关弹窗）。

---

## 4. API 与同源

- **基址**: `api.js` 中 `apiUrl(path)` = `window.location.origin + path`，保证与页面同源、同协议（避免 HTTPS 页请求 HTTP 被拦截）。
- **实际请求**:
  - **SSE**: `GET /api/analyze_sse?company_name=...&market=...&symbol=...&extra_prompt=...&position=...`（EventSource）
  - **REST**: `GET /api/financials?...`、`GET /api/dcf?...`、`GET /api/pepb-band?...`（fetch）
- 无单独 baseURL 配置；部署在 A 后面时，浏览器请求的 origin 为 A 的域名，/api 由 A 的 Nginx 转发到 B。

---

## 5. 样式与设计约定

### 5.1 Tailwind 扩展色（tailwind.config.js）

- `slate-dark`: #0D1117（页面底）
- `slate-panel`: rgba(22,27,34,0.95)（玻璃面板底）
- `emerald-theme`: #10B981（主色）
- `emerald-hover`: #34D399（主色悬停）

### 5.2 通用组件类（index.css @layer components）

- **.glass-panel**: 深色半透明底 + 白边 + 圆角 + 内边距，用于卡片/区块。
- **.input-glow**: 输入框，聚焦时 emerald 边框与 ring。
- **.btn-primary**: 主按钮（emerald 背景），disabled 时半透明。
- **.btn-secondary**: 次要按钮（描边、悬停 emerald）。
- **.markdown-body**: 报告正文的标题/段落/列表/代码块/引用等样式，与 slate 系文字色一致。

### 5.3 布局与响应

- 主内容区 `max-w-6xl`（form 内表单 `max-w-2xl`，report `max-w-4xl`，dashboard `max-w-5xl`）。
- 移动端：index.css 内对 body 做了 safe-area-inset 适配。

---

## 6. 常见问题定位表

| 现象 | 建议排查位置 |
|------|----------------|
| 点击「开始分析」一直「正在连接分析服务…」 | ReportView：SSE 是否建立；Network 中 `/api/analyze_sse` 是否发出、状态码与是否被截断/超时；A 的 Nginx 对 analyze_sse 的 proxy_read_timeout 是否足够 |
| 分析中途出现「连接分析服务失败」 | 同上 + B 端是否在拉行情阶段长时间无输出（可查 B 是否已发 keepalive）；代理/浏览器是否因空闲关闭连接 |
| 财务看板全部「—」、无图 | FinancialDashboard：三个 GET 是否 200；响应结构是否含 dcfData.raw/valuation、financialData.chart.income_statement、pepbData.chart.pe_band |
| 页面空白 / 白屏 | ErrorBoundary 是否捕获错误；Console 是否有未捕获异常；是否访问到正确前端（本仓库 dist）而非其他站点 |
| 历史记录不显示或错误 | App 中 history 来自 localStorage `stock_advisor_history`；ReportView 收到 meta 时调用 onSaveHistory 写入 |
| 点「财务看板」无反应或缺数据 | 仅当 report 页已收到 meta 后才会显示按钮；dashboard 的 symbol 来自 marketData（即 meta）或 analysisState，缺 symbol 不会发请求 |

---

## 7. 文件与职责速查

- `App.jsx`: 视图切换、全局状态、Header、ErrorBoundary、RiskModal
- `components/InputForm.jsx`: 表单、历史选择、开始分析
- `components/ReportView.jsx`: SSE 连接、状态文案、报告 Markdown 渲染、下载、财务看板入口
- `components/FinancialDashboard.jsx`: 三 API 请求、概览/DCF/PE 三 Tab、ECharts 与 KpiCard
- `components/RiskModal.jsx`: 风险确认弹窗
- `api.js`: apiUrl(path) 同源 API 基址
- `index.css`: Tailwind + glass/input/btn/markdown 组件类
- `tailwind.config.js`: slate-dark/panel、emerald-theme/hover 扩展色
