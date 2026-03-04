# 「连接分析服务器失败」与超时排查

## 1. 本仓库用哪个接口做分析？

- **分析流式接口**：`GET /api/analyze_sse?company_name=...&market=...`（EventSource）
- 本仓库**没有** `/api/sse/monitor`。若控制台出现对 ` /api/sse/monitor` 的超时或错误，说明页面上有**其他脚本或另一套前端**在请求该地址，不是本仓库的分析接口。

## 2. 若看到「连接分析服务器失败」

请按下面顺序排查：

1. **确认访问的是本仓库的前端**
   - 在浏览器 Network 里看：点击分析后是否有一条 **`/api/analyze_sse?...`** 的请求（EventSource）。
   - 若只有 `/api/sse/monitor` 或其它地址，说明当前页面可能不是本仓库构建的 frontend-react，需部署本仓库的 dist 并确保访问的是该页面。

2. **确认 B 已启动且 A 能访问 B**
   - 在 Server A 上执行：`curl -s -o /dev/null -w "%{http_code}" "http://__B的IP__:8001/health"`（将 B 的 IP 换成 .env 里 SERVER_B_HOST），应得到 200。
   - 若 A 访问 B 超时或失败，检查 B 进程、防火墙、安全组。

3. **确认 A 的 Nginx 对 SSE 已加长超时**
   - 本仓库已在 A 的 Nginx 模板里为 **`/api/analyze_sse`** 单独配置：`proxy_read_timeout 600s`、`proxy_send_timeout 600s`。
   - 在 A 上执行 `./setup.sh` 更新配置后，执行 `sudo nginx -s reload`。

4. **看 B 端日志**
   - 点击分析时，B 上应有 `[analyze_sse_request]` 等日志；若没有，说明请求没到 B（被 A 或中间网络拦截/超时）。

## 3. 本仓库已做的防断连

- 后端在拉行情期间每约 8 秒向 SSE 流发送 keepalive（` : keepalive`），避免代理因「长时间无数据」关闭连接。
- A 的 Nginx 对 `location = /api/analyze_sse` 使用 600 秒读写超时，减少因代理超时导致的断开。

## 4. 若仍超时

- 检查用户到 A、A 到 B 的网络是否稳定（丢包、长延迟会导致超时）。
- 在 B 上执行：`python scripts/test_market_data.py --quick`，确认 B 拉行情是否正常；若 B 拉行情就很慢，分析整体会变慢并更容易在中间环节超时。
