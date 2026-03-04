"""
Server A - HTTP(S) 端口代理
- 监听独立端口（如 8080），供 Server B 配置 HTTP_PROXY/HTTPS_PROXY 使用
- 仅允许 ALLOWED_DOMAINS 内的域名（yfinance 相关）
- 支持 CONNECT（HTTPS）与 GET 绝对 URL（HTTP）
- 可选 Proxy-Authorization 鉴权（与 API_TOKEN 一致）
"""

import asyncio
import base64
import sys
from urllib.parse import urlparse

# 由 main 注入
ALLOWED_DOMAINS: list = []
API_TOKEN: str = ""


def _check_host(host: str) -> bool:
    """检查主机是否在白名单（支持 host:port 形式）"""
    if not host:
        return False
    host = host.split(":")[0].strip().lower()
    return host in ALLOWED_DOMAINS


def _check_auth(headers: list[tuple[str, str]]) -> bool:
    """检查 Proxy-Authorization：Basic base64(user:pass)，user 等于 API_TOKEN 即通过"""
    if not API_TOKEN:
        return True
    for k, v in headers:
        if k.strip().lower() == "proxy-authorization" and v.strip().lower().startswith("basic "):
            try:
                decoded = base64.b64decode(v[6:].strip()).decode("utf-8", errors="replace")
                user = (decoded.split(":", 1) or [""])[0]
                return user == API_TOKEN
            except Exception:
                pass
    return False


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, label: str):
    """双向转发直到任一端关闭"""
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    except Exception as e:
        print(f"[Proxy] {label} relay error: {e}", file=sys.stderr)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_proxy_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
):
    """处理单次代理连接：解析首行与头，CONNECT 建隧道或 GET 转发"""
    remote_reader = remote_writer = None
    try:
        # 读首行
        first_line = (await client_reader.readline()).decode("utf-8", errors="replace").strip()
        if not first_line:
            return
        parts = first_line.split()
        if len(parts) < 2:
            return
        method, target = parts[0].upper(), parts[1]

        # 读头（直到 \r\n\r\n）
        headers: list[tuple[str, str]] = []
        while True:
            line = (await client_reader.readline()).decode("utf-8", errors="replace").strip()
            if not line:
                break
            if ":" in line:
                k, _, v = line.partition(":")
                headers.append((k.strip(), v.strip()))

        # 鉴权
        if not _check_auth(headers):
            client_writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            await client_writer.drain()
            return

        if method == "CONNECT":
            # CONNECT host:port
            host_port = target
            if ":" in host_port:
                host, port_s = host_port.rsplit(":", 1)
                try:
                    port = int(port_s)
                except ValueError:
                    port = 443
            else:
                host = host_port
                port = 443
            if not _check_host(host):
                print(f"[Proxy] CONNECT blocked: {host}", file=sys.stderr)
                client_writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                await client_writer.drain()
                return
            try:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=30.0,
                )
            except Exception as e:
                print(f"[Proxy] CONNECT to {host}:{port} failed: {e}", file=sys.stderr)
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_writer.drain()
                return
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
            # 双向转发
            t1 = asyncio.create_task(_relay(client_reader, remote_writer, "client->remote"))
            t2 = asyncio.create_task(_relay(remote_reader, client_writer, "remote->client"))
            await asyncio.gather(t1, t2)
            return

        if method == "GET" and (target.startswith("http://") or target.startswith("https://")):
            # 绝对 URL：用 httpx 请求并回写（仅 HTTP 常用，HTTPS 一般走 CONNECT）
            parsed = urlparse(target)
            host = (parsed.netloc or "").split(":")[0]
            if not _check_host(host):
                print(f"[Proxy] GET blocked: {host}", file=sys.stderr)
                client_writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                await client_writer.drain()
                return
            try:
                import httpx
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp = await client.get(target)
                status = resp.status_code
                body = resp.content
                head = f"HTTP/1.1 {status} {resp.reason_phrase}\r\n"
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        head += f"{k}: {v}\r\n"
                head += "Connection: close\r\n\r\n"
                client_writer.write(head.encode("utf-8") + body)
                await client_writer.drain()
            except Exception as e:
                print(f"[Proxy] GET {target} failed: {e}", file=sys.stderr)
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_writer.drain()
            return

        client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
        await client_writer.drain()
    except Exception as e:
        print(f"[Proxy] handle error: {e}", file=sys.stderr)
    finally:
        try:
            client_writer.close()
            await client_writer.wait_closed()
        except Exception:
            pass
        if remote_writer:
            try:
                remote_writer.close()
                await remote_writer.wait_closed()
            except Exception:
                pass


async def run_proxy_server(host: str, port: int):
    """在指定地址启动代理服务器（需在 main 中注入 ALLOWED_DOMAINS / API_TOKEN 后调用）"""
    server = await asyncio.start_server(handle_proxy_connection, host, port)
    print(f"[Proxy] HTTP(S) proxy listening on {host}:{port}", file=sys.stderr)
    async with server:
        await server.serve_forever()
