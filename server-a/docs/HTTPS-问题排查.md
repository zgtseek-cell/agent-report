# Server A 启用 HTTPS 时可能存在的问题

## 一、证书与脚本

| 问题 | 原因 | 处理 |
|------|------|------|
| 未找到 ssl/ 证书，将仅启用 HTTP | `server-a/nginx/ssl/` 下没有证书/私钥，或文件名不匹配 | 将 Cloudflare Origin 证书与私钥放入 `nginx/ssl/`，命名为 `origin_certificate.pem` + `private_key.pem`（或 README 中其它组合），然后重新执行 `./setup.sh` |
| 证书或私钥格式无效 | 非 PEM、含 BOM、Windows 换行 | 确保首行为 `-----BEGIN CERTIFICATE-----` / `-----BEGIN PRIVATE KEY-----`，无前导空格；用 `dos2unix` 转成 Unix 换行 |
| SSL 加载失败，切换为仅 HTTP | Nginx 无法加载 PEM（路径/权限/格式） | 查看 `sudo nginx -t` 和 `/var/log/nginx/error.log`（如 PEM_read_bio_X509_AUX failed）；确认 `/etc/nginx/ssl/stock-advisor/` 下证书与私钥存在且权限正确（私钥 600） |

## 二、Cloudflare 与源站

| 问题 | 原因 | 处理 |
|------|------|------|
| 521 Web server is down | Cloudflare 无法连上源站 443（或 80） | 1）云主机安全组/防火墙放通 **443**（和 80）<br>2）Cloudflare SSL/TLS 模式设为 **Full** 或 **Full (strict)**<br>3）源站使用 **Cloudflare Origin 证书** 时选 Full (strict) |
| 526 Invalid SSL certificate | 源站证书不被 Cloudflare 信任 | 使用 Cloudflare 控制台生成的 **Origin Certificate** 部署在 A 上；若用 Let’s Encrypt 等公网证书，需在 Cloudflare 用 Full（非 strict）或换回 Origin 证书 |
| 用户访问 http 未跳 https | 未配置 80→443 重定向 | 使用带 HTTPS 的配置（`stock-advisor.conf`）时，已包含 80 重定向到 443；确认生效的是该配置而非 http-only |

## 三、网络与权限

| 问题 | 原因 | 处理 |
|------|------|------|
| 本机 curl https://127.0.0.1/health 失败 | Nginx 未监听 443 或证书错误 | `ss -tlnp | grep 443` 确认 Nginx 监听；`sudo nginx -t` 无报错；查看 `error_log` |
| 外网无法访问 443 | 防火墙/安全组未放行 | 云控制台放行 TCP 443；必要时本机 `firewall-cmd` 或 iptables 放行 |
| 证书复制后 Nginx 仍报错 | 目标路径无读权限或 SELinux | `sudo chown -R nginx:nginx /etc/nginx/ssl/stock-advisor`（或 root）；SELinux 环境下可 `sudo restorecon -R /etc/nginx/ssl` |

## 四、与 B 的配合

| 问题 | 原因 | 处理 |
|------|------|------|
| 前端请求 API 被混用协议拦截 | 页面是 https 但请求写死 http | 确保 B 或前端根据 `X-Forwarded-Proto` 生成链接为 `https://`（当前 A 已传该头） |
| B 的 CORS 拒绝 | B 的 allow_origins 未包含 https 域名 | 在 B 的 CORS 配置中加入 `https://visestock.com`、`https://www.visestock.com` |

## 五、建议自检顺序

1. 在 A 上执行：`sudo nginx -t` → 无报错  
2. 在 A 上执行：`curl -vk https://127.0.0.1/health` → 返回 200 且证书链正常  
3. Cloudflare：SSL/TLS 模式 = Full (strict)，并确认 DNS 指向 A 的公网 IP  
4. 云控制台：安全组放行 80、443  
5. 浏览器访问 `https://visestock.com`，确认无 521/526，且 HTTP 自动跳 HTTPS  
