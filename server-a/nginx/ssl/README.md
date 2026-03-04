# SSL 证书目录

将证书和私钥放入本目录，执行 `../setup.sh` 时自动部署并启用 HTTPS（443）。

**格式要求**：标准 PEM 格式
- 证书：首行含 `-----BEGIN CERTIFICATE-----` 或 `-----BEGIN TRUSTED CERTIFICATE-----`
- 私钥：首行含 `-----BEGIN PRIVATE KEY-----` 或 `-----BEGIN RSA PRIVATE KEY-----`
- 若格式无效，脚本会自动回退为仅 HTTP，并提示检查文件

**支持的命名（任选其一）**：

| 证书文件 | 私钥文件 |
|----------|----------|
| `origin_certificate.pem` | `private_key.pem` |
| `fullchain.pem` | `privkey.pem` |
| `cert.pem` | `key.pem` |

**Cloudflare**：SSL/TLS → Origin Server → 创建证书，下载后放入本目录即可。

---

**出现 "no start line" 或 "PEM_read_bio_X509_AUX failed" 时**：

1. 检查文件首行是否为 `-----BEGIN CERTIFICATE-----`，前面不能有空格或 BOM
2. 转换为 Unix 换行：`dos2unix origin_certificate.pem private_key.pem`
3. 或临时绕过：删除 ssl/ 下证书文件，setup.sh 将自动使用仅 HTTP 模式
