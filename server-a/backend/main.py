"""
Server A 后端 - 代理服务器 + 价格/财报数据 API
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Dict, Any
from urllib.parse import urlparse

import httpx
import yfinance as yf
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# 加载环境变量
load_dotenv()

from .config import (
    CORS_ORIGINS,
    FMP_API_KEY,
    PROXY_EXTERN_TIMEOUT,
)
from .finance_logic import (
    get_company_financial_health_snapshot as get_agent_health_snapshot,
    get_company_valuation_metrics as get_agent_valuation_metrics,
)
from .price import fetch_single_price, fetch_batch_prices, fetch_single_price_with_fallback
from .financials import _get_dcf_payload, _get_financials_payload, _get_pepb_payload, _ticker_for_symbol

# API 鉴权配置（可选，防止外网滥用）
API_TOKEN = os.getenv("API_TOKEN", "")

# 允许代理的域名白名单（仅允许 yfinance 相关域名）
ALLOWED_DOMAINS = os.getenv("ALLOWED_DOMAINS", "query1.finance.yahoo.com,query2.finance.yahoo.com,finance.yahoo.com,s.yimg.com,image.yahoo.com").split(",")
ALLOWED_DOMAINS = [domain.strip() for domain in ALLOWED_DOMAINS if domain.strip()]

# 端口代理：非 0 时在 PROXY_PORT 上启动 HTTP(S) 代理，B 可设 HTTP_PROXY/HTTPS_PROXY 使用
PROXY_PORT = int(os.getenv("PROXY_PORT", "0"))
PROXY_HOST = os.getenv("PROXY_HOST", "0.0.0.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时可选启动端口代理；关闭时清理"""
    # region agent log
    try:
        import json, time
        payload = {
            "sessionId": "2eeba5",
            "runId": "run1",
            "hypothesisId": "H1",
            "location": "server-a/backend/main.py:lifespan",
            "message": "lifespan_start",
            "data": {"proxy_port": PROXY_PORT},
            "timestamp": int(time.time() * 1000),
        }
        with open("/home/zgt/agent/agent-prompt-v2-cusor/.cursor/debug-2eeba5.log", "a") as f:
            f.write(json.dumps(payload) + "\\n")
    except Exception:
        pass
    # endregion agent log
    proxy_task = None
    if PROXY_PORT > 0:
        import backend.proxy_server as proxy_server
        proxy_server.ALLOWED_DOMAINS = ALLOWED_DOMAINS
        proxy_server.API_TOKEN = API_TOKEN
        proxy_task = asyncio.create_task(
            proxy_server.run_proxy_server(PROXY_HOST, PROXY_PORT)
        )
    yield
    if proxy_task and not proxy_task.done():
        proxy_task.cancel()
        try:
            await proxy_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="股票智能顾问 - Server A (Proxy + Data APIs)", lifespan=lifespan)


def _rate_limit_key(request: Request) -> str:
    """限流键：优先使用 X-Forwarded-For（反向代理场景），否则用 client IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """添加安全响应头"""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ========== 通用外网代理接口 ==========

class ProxyRequest(BaseModel):
    """代理请求模型"""
    url: str
    method: str = "GET"
    headers: Dict[str, str] = {}
    params: Dict[str, Any] = {}
    data: Dict[str, Any] = {}
    json: Dict[str, Any] = {}


@app.post("/api/proxy/extern")
async def proxy_external(
    request: ProxyRequest,
    token: str = Query("", description="API 鉴权 token"),
):
    """
    通用外网代理接口
    - 接收 Server B 的请求参数
    - 验证请求域名是否在白名单内
    - 转发请求到目标域名并返回响应
    - 支持 API token 鉴权
    """
    # 鉴权检查
    if API_TOKEN and token != API_TOKEN:
        raise HTTPException(status_code=401, detail="无效的 API token")

    # 验证请求域名是否在白名单内
    parsed_url = urlparse(request.url)
    if parsed_url.netloc not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=403, detail=f"禁止代理该域名: {parsed_url.netloc}")

    # 代理请求外网超时，避免 A 无限等待导致 B 一直 timed out
    proxy_timeout = float(os.getenv("PROXY_EXTERN_TIMEOUT", "25"))
    try:
        # 转发请求
        import sys
        print(f"[Proxy] Request: url={request.url}, method={request.method}, timeout={proxy_timeout}s", file=sys.stderr)
        async with httpx.AsyncClient(follow_redirects=True, timeout=proxy_timeout) as client:
            # 构建请求参数
            req_kwargs = {}
            if request.headers:
                req_kwargs["headers"] = request.headers
            if request.params:
                req_kwargs["params"] = request.params
            if request.data:
                req_kwargs["data"] = request.data
            if request.json:
                req_kwargs["json"] = request.json

            # 发送请求
            if request.method.upper() == "GET":
                response = await client.get(request.url, **req_kwargs)
            elif request.method.upper() == "POST":
                response = await client.post(request.url, **req_kwargs)
            elif request.method.upper() == "PUT":
                response = await client.put(request.url, **req_kwargs)
            elif request.method.upper() == "DELETE":
                response = await client.delete(request.url, **req_kwargs)
            else:
                raise HTTPException(status_code=405, detail=f"不支持的请求方法: {request.method}")

            print(f"[Proxy] Response: status={response.status_code}, headers={dict(response.headers)}, content={response.text[:200]}", file=sys.stderr)
            # 返回响应
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "content": response.text
            }
    except Exception as e:
        import sys
        print(f"[Proxy] Error: {str(e)}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=f"代理请求失败: {str(e)}")


# ========== 健康检查 ==========

@app.get("/health")
@limiter.exempt
async def health():
    """健康检查"""
    # region agent log
    try:
        import json, time
        payload = {
            "sessionId": "2eeba5",
            "runId": "run1",
            "hypothesisId": "H1",
            "location": "server-a/backend/main.py:health",
            "message": "health_called",
            "data": {},
            "timestamp": int(time.time() * 1000),
        }
        with open("/home/zgt/agent/agent-prompt-v2-cusor/.cursor/debug-2eeba5.log", "a") as f:
            f.write(json.dumps(payload) + "\\n")
    except Exception:
        pass
    # endregion agent log
    return {"status": "ok", "server": "A"}


# ========== 价格查询接口 ==========

class PriceBatchItem(BaseModel):
    market: str = Field(..., max_length=10)
    symbol: str = Field(..., max_length=20)
    trade_date: str = Field(..., max_length=12)


class PriceBatchRequest(BaseModel):
    items: list[PriceBatchItem] = Field(..., max_length=20)


@app.get("/api/price")
@limiter.limit("60/minute")
async def get_price(
    request: Request,
    market: str = Query(..., max_length=10),
    symbol: str = Query(..., max_length=20),
    trade_date: str = Query(..., max_length=12),
):
    """单条价格查询"""
    result = fetch_single_price(market, symbol, trade_date)
    if result.get("error") and result.get("price", 0) == 0:
        status = 404 if "未查询到" in (result.get("error") or "") else 400
        return JSONResponse({"error": result["error"]}, status_code=status)
    return result


@app.post("/api/price/batch")
@limiter.limit("30/minute")
async def get_price_batch(request: Request, body: PriceBatchRequest):
    """批量价格查询"""
    items = [{"market": i.market, "symbol": i.symbol, "trade_date": i.trade_date} for i in body.items]
    results = fetch_batch_prices(items)
    return {"items": results}


@app.get("/api/stock/{ticker}")
@limiter.limit("60/minute")
async def get_stock(request: Request, ticker: str):
    """基础股票查询"""
    if len(ticker) > 20:
        return JSONResponse({"error": "股票代码过长"}, status_code=400)
    # 规范化 ticker
    normalized = _ticker_for_symbol(ticker, "us")
    try:
        tk = yf.Ticker(normalized)
        info = tk.info
    except Exception:
        return JSONResponse(
            {"error": "无法获取该股票数据，请检查代码是否正确。"},
            status_code=400,
        )

    if not info:
        return JSONResponse(
            {"error": "无法获取该股票数据，请检查代码是否正确。"},
            status_code=404,
        )

    try:
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        pe = info.get("trailingPE") or info.get("forwardPE")
        eps = info.get("trailingEps") or info.get("forwardEps")
        market_cap = info.get("marketCap")
        summary = info.get("longBusinessSummary") or ""

        if price is None and pe is None and eps is None and market_cap is None and not summary:
            raise ValueError("empty info")

        return {
            "ticker": normalized,
            "price": price,
            "pe": pe,
            "eps": eps,
            "market_cap": market_cap,
            "summary": summary,
        }
    except Exception:
        return JSONResponse(
            {"error": "无法获取该股票数据，请检查代码是否正确。"},
            status_code=500,
        )


# ========== 财报与估值接口 ==========

@app.get("/api/dcf")
@limiter.limit("30/minute")
async def get_dcf(
    request: Request,
    symbol: str = Query(..., max_length=20),
    market: str = Query("us", max_length=10),
):
    """DCF 估值数据，供财务看板概览与 DCF 页使用"""
    ticker = _ticker_for_symbol(symbol, market)
    if not ticker:
        return JSONResponse({"error": "缺少或无效的 symbol"}, status_code=400)
    try:
        tk = yf.Ticker(ticker)
        info = getattr(tk, "info", None) or {}
        payload = _get_dcf_payload(tk, info)
        return payload
    except Exception as e:
        # 仍返回约定结构，避免前端全空；估值字段用 0 与「暂无数据」
        try:
            return {
                "raw": {"current_price": 0, "currency": "USD"},
                "valuation": {
                    "intrinsic_value": 0,
                    "margin_of_safety": 0,
                    "recommendation": "暂无数据",
                },
                "chart": {"labels": [], "datasets": []},
                "parameters": {"growth_rate": 0.08, "terminal_growth": 0.02, "discount_rate": 0.10, "years": 5},
            }
        except Exception:
            return JSONResponse(
                {"error": f"获取 DCF 数据失败：{str(e)}"},
                status_code=500,
            )


@app.get("/api/financials")
@limiter.limit("30/minute")
async def get_financials(
    request: Request,
    symbol: str = Query(..., max_length=20),
    market: str = Query("us", max_length=10),
):
    """财务趋势（利润表）数据，供财务看板营收/净利润图使用"""
    ticker = _ticker_for_symbol(symbol, market)
    if not ticker:
        return JSONResponse({"error": "缺少或无效的 symbol"}, status_code=400)
    try:
        tk = yf.Ticker(ticker)
        payload = _get_financials_payload(tk)
        return payload
    except Exception:
        return {"chart": {"income_statement": {"labels": [], "datasets": []}}}


@app.get("/api/pepb-band")
@limiter.limit("30/minute")
async def get_pepb_band(
    request: Request,
    symbol: str = Query(..., max_length=20),
    market: str = Query("us", max_length=10),
):
    """PE Band 数据，供财务看板 PE/PB 页使用"""
    ticker = _ticker_for_symbol(symbol, market)
    if not ticker:
        return JSONResponse({"error": "缺少或无效的 symbol"}, status_code=400)
    try:
        tk = yf.Ticker(ticker)
        info = getattr(tk, "info", None) or {}
        payload = _get_pepb_payload(tk, info)
        return payload
    except Exception:
        return {"chart": {"pe_band": {"labels": [], "datasets": []}}}


@app.get("/api/agent-data/valuation")
@limiter.limit("60/minute")
async def get_agent_valuation_data(
    request: Request,
    ticker: str = Query(..., max_length=20),
):
    """供 Server B Agent 调用的估值数据接口。"""
    _ = FMP_API_KEY
    return get_agent_valuation_metrics(ticker)


@app.get("/api/agent-data/health")
@limiter.limit("60/minute")
async def get_agent_health_data(
    request: Request,
    ticker: str = Query(..., max_length=20),
):
    """供 Server B Agent 调用的财务健康度接口。"""
    _ = FMP_API_KEY
    return get_agent_health_snapshot(ticker)


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def root_hint():
    """
    直接访问 8000 端口时提示：请通过网站主入口（80/443）访问。
    正常用户应经 Nginx(80/443) 访问，Nginx 将 / 转发到 B。
    """
    return """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>提示</title></head><body>
<p>本端口仅用于代理服务，不提供前端页面。</p>
<p>请通过<strong>网站主入口</strong>访问：<code>http://本机IP/</code> 或 <code>https://本机域名/</code>（端口 80 或 443），不要直接访问 8000 端口。</p>
<p>若您已使用主入口仍看到此页，请检查 Nginx 是否已启动并执行过 <code>./setup.sh</code>。</p>
</body></html>
"""


# 前端与业务 API 均在 B；公网 Nginx 将 / 及 /api/* 转发到 B，仅 /api/proxy/extern 由 Nginx 转到本机 8000

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
