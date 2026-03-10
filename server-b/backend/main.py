"""
Server B 后端 - 重构版
- 新 System Prompt：顶级价值投资分析师
- 新增参数：position（当前仓位）、market_data（来自 Server A 的硬核计算）
- 输出格式：核心观点、估值偏差分析、基于仓位的操作建议
"""

import os
import json
import uuid
import asyncio
from datetime import datetime
from typing import AsyncGenerator, Optional, Dict, Any

from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .config import (
    CORS_ORIGINS,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    DEBUG_LOG_PATH,
    LOG_PATH,
    FEEDBACK_DIR,
)
from .price import fetch_single_price_with_fallback
from .company_cache import resolve_company
from .agent_core.graph import run_investment_agent

os.makedirs(Path(LOG_PATH).parent, exist_ok=True)
os.makedirs(Path(DEBUG_LOG_PATH).parent, exist_ok=True)


def _debug_log(message: str, data: dict | None = None, hypothesis_id: str = "H?"):
    """写入 debug NDJSON 日志"""
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": "backend/main.py",
            "message": message,
            "data": data or {},
            "timestamp": int(datetime.now().timestamp() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


_debug_log("module imported", {}, hypothesis_id="H0")


# ========== 调试模式 NDJSON 日志（写入工作区 .cursor/debug.log）==========
def _agent_ndjson_log(message: str, data: dict | None = None, hypothesis_id: str = "H?"):
    """
    调试专用：将关键节点写入 /home/zgt/agent/agent-prompt-v2-cusor/.cursor/debug.log（NDJSON）
    - 不包含 sessionId（由调试系统统一管理）
    """
    try:
        import time as _time
        import json as _json

        # 工程根目录：/home/zgt/agent/agent-prompt-v2-cusor
        # main.py 位于 server-b/backend/main.py，因此 parents[2] 即为工程根
        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
        payload = {
            "id": f"log_{int(_time.time() * 1000)}",
            "timestamp": int(_time.time() * 1000),
            "location": "backend/main.py:analyze_sse",
            "message": message,
            "data": data or {},
            "runId": "pre-fix-1",
            "hypothesisId": hypothesis_id,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # 调试日志失败不能影响主流程
        pass


_agent_ndjson_log("server_b_main_imported_with_langgraph", {}, "H0")


client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    timeout=DEEPSEEK_TIMEOUT,
)


def _rate_limit_key(request: Request) -> str:
    """限流键：优先使用 X-Forwarded-For（反向代理场景），否则用 client IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=_rate_limit_key)
app = FastAPI(title="Stock Advisor with DeepSeek - 重构版")
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


# ========== 请求模型 ==========

class AnalyzeRequest(BaseModel):
    """分析请求（新版）"""
    company_name: str = Field(..., min_length=1, max_length=100)
    market: str = Field(..., min_length=1, max_length=10)
    symbol: str | None = Field(None, max_length=20)
    extra_prompt: str | None = Field(None, max_length=500)
    position: float | None = Field(None, ge=0, le=100, description="当前仓位百分比，0-100")
    market_data: Dict[str, Any] | None = Field(None, description="来自 Server A 的硬核财务数据")


class ExportRequest(BaseModel):
    """导出 PDF 的请求体"""
    content: str = Field(..., max_length=500_000)


class FeedbackRequest(BaseModel):
    """意见反馈请求体"""
    rating: int = Field(0, ge=0, le=5)
    content: str = Field("", max_length=2000)


# ========== System Prompt（新版） ==========

SYSTEM_PROMPT = """你是一位顶级价值投资分析师，拥有 20 年以上的全球市场投资经验，深度信仰格雷厄姆与巴菲特的价值投资哲学。

你的核心原则：
1. 安全边际：始终强调买入价格相对于内在价值的折扣
2. 能力圈：诚实地说明哪些行业/公司超出分析范围
3. 长期视角：关注 3-5 年的价值实现，而非短期波动
4. 保守主义：估值时采用偏保守的假设，对乐观情景保持警惕

你的任务是：
1. 基于提供的财务数据和市场数据，进行严谨的估值分析
2. 明确指出当前价格与内在价值的偏差程度
3. 结合用户当前的仓位情况，给出体系化的操作建议

重要要求：
- 禁止模糊表述，所有结论必须有数据支撑
- 如果关键数据缺失，必须明确指出
- 严禁给出保证收益或承诺性质的表述
- 必须以「风险提示」和「不构成投资建议」收尾
"""


# ========== 辅助函数 ==========

def _map_to_symbol(company_name: str, market: str) -> str | None:
    """兜底映射：仅针对少量常见标的硬编码"""
    name = company_name.strip().lower()
    m = market.lower()

    if ("泡泡玛特" in name or "泡泡瑪特" in name or "pop mart" in name) and m == "hk":
        return "9992.HK"
    if ("腾讯控股" in name or "騰訊控股" in name or "腾讯" in name or "tencent" in name) and m == "hk":
        return "700"
    if ("apple" in name or "苹果" in name) and m == "us":
        return "AAPL"
    if ("microsoft" in name or "微软" in name) and m == "us":
        return "MSFT"
    if ("阿里巴巴" in name or "alibaba" in name) and m in ("us", "auto"):
        return "BABA"
    if ("阿里巴巴" in name or "alibaba" in name) and m == "hk":
        return "9988"

    return None


def _fetch_market_data(company_name: str, market: str, symbol: str | None = None) -> dict:
    """获取市场数据"""
    raw_market = (market or "").strip().lower()
    user_symbol = (symbol or "").strip()
    resolved_symbol = ""
    resolved_market: str | None = None

    if company_name and company_name.strip():
        info = resolve_company(company_name.strip(), raw_market or "auto")
        if info and info.get("symbol"):
            resolved_symbol = (info["symbol"] or "").strip()
            if info.get("market"):
                resolved_market = str(info["market"]).strip().lower()
        if not resolved_symbol:
            resolved_symbol = _map_to_symbol(company_name, raw_market or "auto") or ""

    if not resolved_symbol and user_symbol:
        resolved_symbol = user_symbol
        if raw_market in ("cn", "hk", "us"):
            resolved_market = raw_market
        else:
            sym_upper = user_symbol.upper()
            if sym_upper.endswith(".HK"):
                resolved_market = "hk"
            elif sym_upper.isdigit():
                if len(sym_upper) == 6:
                    resolved_market = "cn"
                elif len(sym_upper) <= 4:
                    resolved_market = "hk"
            else:
                resolved_market = "us"

    if not resolved_symbol:
        return {}

    use_market = resolved_market or (raw_market if raw_market in ("cn", "hk", "us") else "")
    if use_market not in ("cn", "hk", "us"):
        return {}

    try:
        price_info = fetch_single_price_with_fallback(use_market, resolved_symbol)
        price = price_info.get("price")
        if price_info.get("error") or not price:
            return {}

        currency = price_info.get("currency") or (
            "HKD" if use_market == "hk" else ("CNY" if use_market == "cn" else "USD")
        )
        as_of = price_info.get("date") or datetime.now().strftime("%Y-%m-%d")

        result = {
            "market": price_info.get("market") or use_market,
            "symbol": price_info.get("symbol") or resolved_symbol,
            "current_price": float(price),
            "previous_close": None,
            "currency": currency,
            "high_52w": None,
            "low_52w": None,
            "as_of": as_of,
        }

        return result
    except Exception as e:
        return {}


def build_user_prompt(
    company_name: str,
    market: str,
    extra_prompt: str | None = None,
    position: float | None = None,
    market_data: Dict[str, Any] | None = None,
    internal_market_data: Dict[str, Any] | None = None,
) -> str:
    """构建用户 Prompt（新版）"""

    today = datetime.now().strftime("%Y-%m-%d")
    m = market.lower()

    if m == "hk":
        market_label = "港股"
    elif m == "us":
        market_label = "美股"
    elif m == "cn":
        market_label = "A股"
    else:
        market_label = "股票"

    base_prompt = ""

    # 整合所有市场数据（优先使用来自 Server A 的硬核数据）
    combined_market_data = market_data or internal_market_data or {}

    if combined_market_data:
        base_prompt += "【系统提供的市场数据】（请务必严格以此为准）\n"
        symbol = combined_market_data.get("symbol", "")
        cp = combined_market_data.get("current_price")
        cur = combined_market_data.get("currency", "USD")
        as_of = combined_market_data.get("as_of", today)

        if symbol:
            base_prompt += f"- 股票代码：{symbol}\n"
        if cp is not None:
            base_prompt += f"- 当前股价：{cp:.2f} {cur}（数据截至 {as_of}）\n"
        else:
            base_prompt += "- 当前股价：未能获取\n"

        # 如果有来自 Server A 的财务数据，也展示出来
        if "raw" in combined_market_data or "valuation" in combined_market_data:
            base_prompt += "\n【硬核财务分析数据】（来自 Server A 的计算结果）\n"
            if "valuation" in combined_market_data:
                val = combined_market_data["valuation"]
                if "intrinsic_value" in val:
                    base_prompt += f"- DCF 内在价值：{val['intrinsic_value']:.2f} {cur}\n"
                if "margin_of_safety" in val:
                    base_prompt += f"- 安全边际：{val['margin_of_safety']:.1f}%\n"
                if "recommendation" in val:
                    base_prompt += f"- 估值建议：{val['recommendation']}\n"
            base_prompt += "\n"

    position_display = f"{position:.1f}%" if position is not None else "未提供"
    if position is not None:
        base_prompt += f"【用户当前仓位】\n"
        base_prompt += f"- 当前持仓比例：{position_display}\n"
        base_prompt += "\n"

    base_prompt += f"""
分析目标公司：{company_name}（{market_label}）
分析日期：{today}

请你作为顶级价值投资分析师，完成一份专业的投资分析报告。

【要求结构】

## 一、核心观点
用 3-5 句话清晰阐述你的核心结论：
- 公司的商业模式是否可靠？
- 当前估值处于什么水平？
- 作为价值投资者，你对这只股票的整体态度是什么？

## 二、估值偏差分析
1. 内在价值评估
   - 你认为该公司的合理内在价值区间是多少？
   - 给出关键假设：未来 3 年收入增速、稳态净利率、折现率等
   - 说明你选择的估值方法及理由

2. 价格偏差分析
   - 当前价格相对于内在价值的偏差程度（溢价/折价/合理）
   - 结合 PE/PB Band（如有）说明当前估值在历史中的位置
   - 分析造成当前估值水平的原因

## 三、基于仓位的操作建议
结合用户当前 {position_display} 的仓位情况，给出体系化的操作指导：

### 情景 1：当前空仓/轻仓（< 30%）
- 建议建仓区间
- 建议分批买入策略
- 首次买入比例建议

### 情景 2：当前中等仓位（30%-70%）
- 是否建议加仓？在什么价格加仓？
- 是否建议减仓？在什么价格减仓？
- 总体持有策略

### 情景 3：当前重仓（> 70%）
- 是否需要降低仓位？
- 建议的减仓节奏和目标仓位
- 止盈策略和点位

## 四、风险提示
罗列至少 3-5 条主要风险，并说明对投资决策的影响。

【格式要求】
- 使用 Markdown 格式，标题用 ## 或 ###
- 文风专业但务实，用数据说话
- 在报告正文的第一行，你必须先输出一行快览指标（用于前端展示），格式严格如下，不要换行、不要多余字符：
  METRICS_JSON:{{"revenue_growth":"X%","cashflow_score":"良好/一般/较差","risk_level":"高/中/低","valuation_status":"低估/合理/高估","position_recommendation":"买入/持有/减持"}}
- 紧接着在下一行输出一个 Markdown 一级标题，标题内容为：
  # {company_name} 在 {today} 的分析

最后以一段话做总结：重申这是基于公开信息的个人分析，不构成任何形式的投资建议。
"""

    if extra_prompt:
        base_prompt += f"\n\n用户补充要求：{extra_prompt}\n"

    return base_prompt.strip()


def write_log(entry: dict) -> None:
    entry_with_time = {
        "time": datetime.utcnow().isoformat(),
        **entry,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry_with_time, ensure_ascii=False) + "\n")


def _build_metrics_payload_from_toolkit(toolkit_data: dict | None) -> dict | None:
    if not toolkit_data:
        return None

    valuation = toolkit_data.get("valuation") or {}
    financial_health = toolkit_data.get("financial_health") or {}
    derived_metrics = toolkit_data.get("derived_metrics") or {}

    valuation_metrics = valuation.get("valuation_metrics") or {}
    profitability_metrics = valuation.get("profitability_metrics") or {}
    health_metrics = financial_health.get("metrics") or {}

    pe_latest = ((valuation_metrics.get("pe") or {}).get("latest"))
    pe_mean = ((valuation_metrics.get("pe") or {}).get("historical_mean"))
    pb_latest = ((valuation_metrics.get("pb") or {}).get("latest"))
    roe_latest = ((profitability_metrics.get("roe") or {}).get("latest"))
    margin_of_safety = derived_metrics.get("margin_of_safety_pct")

    debt_to_equity = ((health_metrics.get("debt_to_equity") or {}).get("latest"))
    current_ratio = ((health_metrics.get("current_ratio") or {}).get("latest"))

    if margin_of_safety is None:
        valuation_status = "合理"
    elif margin_of_safety >= 20:
        valuation_status = "低估"
    elif margin_of_safety >= 0:
        valuation_status = "合理"
    else:
        valuation_status = "高估"

    if debt_to_equity is None and current_ratio is None:
        risk_level = "中"
    elif debt_to_equity is not None and debt_to_equity > 2:
        risk_level = "高"
    elif current_ratio is not None and current_ratio < 1:
        risk_level = "高"
    elif roe_latest is not None and roe_latest >= 0.15:
        risk_level = "低"
    else:
        risk_level = "中"

    if roe_latest is None:
        cashflow_score = "一般"
    elif roe_latest >= 0.15:
        cashflow_score = "良好"
    elif roe_latest >= 0.08:
        cashflow_score = "一般"
    else:
        cashflow_score = "较差"

    if valuation_status == "低估":
        position_recommendation = "买入"
    elif valuation_status == "高估":
        position_recommendation = "减持"
    else:
        position_recommendation = "持有"

    revenue_growth = "待补充"
    if pe_latest is not None and pe_mean is not None:
        revenue_growth = f"PE当前{pe_latest:.2f}/历史均值{pe_mean:.2f}"

    return {
        "type": "metrics",
        "revenue_growth": revenue_growth,
        "cashflow_score": cashflow_score,
        "risk_level": risk_level,
        "valuation_status": valuation_status,
        "position_recommendation": position_recommendation,
        "pe_latest": pe_latest,
        "pe_historical_mean": pe_mean,
        "pb_latest": pb_latest,
        "roe_latest": roe_latest,
        "margin_of_safety_pct": margin_of_safety,
    }


# ========== API 端点 ==========

@app.get("/health")
@limiter.exempt
async def health():
    _debug_log("health endpoint called", {}, hypothesis_id="H1")
    return {"status": "ok"}


@app.get("/api/resolve_company")
@limiter.limit("20/minute")
async def resolve_company_api(
    request: Request,
    company_name: str,
    market: str = "auto",
):
    """
    解析公司名称，返回真正的公司全称和股票代码
    - 优先使用缓存
    - 缓存未命中时调用大模型
    """
    _debug_log("resolve_company called", {"company_name": company_name, "market": market}, hypothesis_id="H2")

    info = resolve_company(company_name, market)
    if not info:
        return JSONResponse(
            {"error": "无法解析该公司名称"},
            status_code=404,
        )

    return {
        "company_name": info.get("company_name", company_name),
        "market": info.get("market", market),
        "symbol": info.get("symbol", ""),
        "official_name": info.get("official_name", company_name),
        "source": info.get("source", "unknown"),
    }


@app.post("/api/export")
@limiter.limit("10/minute")
async def export_pdf(request: Request, body: ExportRequest):
    """导出 PDF"""
    if not body.content.strip():
        return JSONResponse({"error": "内容为空，无法导出 PDF。"}, status_code=400)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    text = c.beginText(40, height - 40)
    text.setFont("Helvetica", 10)

    for line in body.content.splitlines():
        text.textLine(line)

    c.drawText(text)
    c.showPage()
    c.save()
    buffer.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="analysis_report.pdf"'
    }
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


def _save_feedback(rating: int, content: str) -> Path | None:
    """保存反馈"""
    try:
        now = datetime.now()
        subdir = FEEDBACK_DIR / now.strftime("%Y-%m")
        subdir.mkdir(parents=True, exist_ok=True)
        fname = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
        filepath = subdir / fname
        data = {
            "rating": rating,
            "content": (content or "").strip(),
            "created_at": now.isoformat(),
            "id": fname.replace(".json", ""),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath
    except Exception as e:
        write_log({"type": "feedback_save_error", "error": str(e)})
        return None


@app.post("/api/feedback")
@limiter.limit("20/minute")
async def submit_feedback(request: Request, body: FeedbackRequest):
    """提交反馈"""
    path = _save_feedback(body.rating, body.content)
    if path is None:
        return JSONResponse({"error": "保存反馈失败，请稍后重试。"}, status_code=500)
    return {"ok": True, "message": "感谢您的反馈！"}


# region agent log helper (debug session 986d0a)
def _agent_debug_log(message: str, data: dict | None = None, hypothesis_id: str = "H?"):
    """调试模式专用日志：写入 .cursor/debug-986d0a.log（NDJSON）"""
    try:
        import time as _time
        import json as _json

        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug-986d0a.log"
        payload = {
            "sessionId": "986d0a",
            "runId": "pre-fix-1",
            "hypothesisId": hypothesis_id,
            "location": "backend/main.py:analyze_sse",
            "message": message,
            "data": data or {},
            "timestamp": int(_time.time() * 1000),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # 调试日志失败不能影响主流程
        pass
# endregion





def _agent_log(msg: str, data: dict, hypothesis_id: str = "H?"):
    try:
        _lp = Path(__file__).resolve().parent.parent.parent / ".cursor" / "debug-d13ca2.log"
        import time
        with open(_lp, "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "d13ca2", "location": "analyze_sse", "message": msg, "data": data, "timestamp": int(time.time() * 1000), "hypothesisId": hypothesis_id}, ensure_ascii=False) + "\n")
    except Exception:
        pass


@app.get("/api/analyze_sse")
@limiter.limit("30/minute")
async def analyze_sse(
    request: Request,
    company_name: str,
    market: str,
    symbol: str | None = None,
    extra_prompt: str | None = None,
    position: float | None = None,
):
    _agent_ndjson_log(
        "analyze_sse_enter",
        {
            "company_name": company_name,
            "market": market,
            "symbol": symbol,
            "position": position,
        },
        "H1",
    )
    _agent_debug_log(
        "enter_analyze_sse",
        {
            "company_name": company_name,
            "market": market,
            "symbol": symbol,
            "position": position,
        },
        "H1",
    )
    _agent_log("analyze_sse_entered", {"company_name": company_name, "market": market}, "H1")
    if not DEEPSEEK_API_KEY:
        _debug_log("DEEPSEEK_API_KEY missing (sse)", {}, hypothesis_id="H3")
        _agent_log("analyze_sse_key_missing", {}, "H2")
        _agent_debug_log("deepseek_api_key_missing", {}, "H1")
        return JSONResponse(
            {"error": "DEEPSEEK_API_KEY 未配置，请在环境变量中设置。"},
            status_code=500,
        )

    req_id = str(uuid.uuid4())
    client_host = request.client.host if request.client else "unknown"
    print(f"[analyze_sse_request] id={req_id} company={company_name} market={market} position={position}")
    write_log(
        {
            "request_id": req_id,
            "ip": client_host,
            "company_name": company_name,
            "market": market,
            "extra_prompt_len": len(extra_prompt or ""),
            "symbol": (symbol or "").strip(),
            "position": position,
            "type": "request_sse_v3_langgraph",
        }
    )

    _FETCH_MARKET_TIMEOUT = 55

    async def sse_stream() -> AsyncGenerator[bytes, None]:
        internal_market_data: Dict[str, Any] = {}
        meta_info: dict | None = None
        metrics_sent = False
        final_toolkit_data: dict | None = None
        first_cio_chunk_logged = False

        def _to_sse_data(text: str) -> bytes:
            safe = (text or "").replace("\r", "").replace("\n", "\\n")
            return f"data: {safe}\n\n".encode("utf-8")

        def _to_sse_json(payload: dict) -> bytes:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

        try:
            _agent_debug_log("sse_stream_started", {}, "H2")
            _agent_ndjson_log("sse_stream_started", {}, "H2")
            status_payload = {"type": "status", "message": "正在获取行情…"}
            _agent_ndjson_log("sse_first_status", status_payload, "H2")
            yield _to_sse_json(status_payload)

            _agent_log("fetch_market_data_before", {}, "H4")
            loop = asyncio.get_event_loop()
            fetch_task = loop.run_in_executor(None, lambda: _fetch_market_data(company_name, market, symbol))
            keepalive_interval = 8.0
            remaining = _FETCH_MARKET_TIMEOUT

            try:
                while remaining > 0:
                    wait_sec = min(keepalive_interval, remaining)
                    try:
                        internal_market_data = await asyncio.wait_for(
                            asyncio.shield(fetch_task),
                            timeout=wait_sec,
                        )
                        break
                    except asyncio.TimeoutError:
                        remaining -= wait_sec
                        if remaining > 0:
                            yield b": keepalive\n\n"
                        else:
                            fetch_task.cancel()
                            try:
                                await fetch_task
                            except (asyncio.CancelledError, Exception):
                                pass
                            _agent_log("fetch_market_data_timeout", {"timeout_sec": _FETCH_MARKET_TIMEOUT}, "H4")
                            internal_market_data = {}
                            break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _agent_log("fetch_market_data_error", {"error": str(e)}, "H4")
                internal_market_data = {}

            _agent_log("fetch_market_data_done", {"has_data": bool(internal_market_data)}, "H4")
            _agent_ndjson_log(
                "fetch_market_data_done",
                {
                    "has_data": bool(internal_market_data),
                },
                "H3",
            )

            if internal_market_data:
                meta_info = {
                    "market": internal_market_data.get("market") or market,
                    "symbol": internal_market_data.get("symbol") or (symbol or ""),
                }
            elif not (symbol or "").strip():
                info = resolve_company(company_name, market)
                if info and info.get("symbol") and info.get("market"):
                    meta_info = {
                        "market": str(info["market"]).strip().lower(),
                        "symbol": (info["symbol"] or "").strip(),
                    }
            elif (symbol or "").strip() and market.lower() in ("cn", "hk", "us"):
                meta_info = {"market": market.lower(), "symbol": (symbol or "").strip()}

            if meta_info:
                meta_payload = {
                    "type": "meta",
                    "company_name": company_name,
                    "market": meta_info["market"],
                    "symbol": meta_info["symbol"],
                    "price_unavailable": not internal_market_data,
                    "position": position,
                }
                _agent_ndjson_log("meta_sent", meta_payload, "H3")
                yield _to_sse_json(meta_payload)

            ticker = (
                (meta_info or {}).get("symbol")
                or internal_market_data.get("symbol")
                or (symbol or "").strip()
            )
            graph_market = (
                (meta_info or {}).get("market")
                or internal_market_data.get("market")
                or market
            )
            current_price = internal_market_data.get("current_price")

            if not ticker:
                _agent_ndjson_log("ticker_missing_after_resolution", {"company_name": company_name}, "H6")
                yield _to_sse_data("[错误] 无法确定股票代码，无法启动智能分析。")
                yield b"data: [DONE]\n\n"
                return

            # region agent log
            _agent_ndjson_log(
                "langgraph_started",
                {
                    "ticker": ticker,
                    "market": graph_market,
                    "has_price": current_price is not None,
                },
                "H6",
            )
            # endregion
            yield _to_sse_json({"type": "status", "message": "正在启动多智能体量化分析…"})

            async for event in run_investment_agent(
                ticker=ticker,
                market=graph_market,
                price=current_price,
                position=position,
                extra_prompt=extra_prompt,
                company_name=company_name,
            ):
                event_type = event.get("event", "")
                event_name = event.get("name", "unknown")
                metadata = event.get("metadata") or {}
                node_name = metadata.get("langgraph_node") or metadata.get("graph_node") or event_name
                data = event.get("data") or {}

                # 【底层事件探针】观察 LangGraph / LLM 流式行为
                if event_type in ["on_chat_model_stream", "on_chain_start", "on_chain_end", "on_tool_start"]:
                    print(f"👉 [Event Probe] type: {event_type} | node: {node_name} | name: {event_name}")
                if event_type == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    content_preview = ""
                    reasoning_preview = ""
                    if chunk is not None:
                        try:
                            content_preview = str(getattr(chunk, "content", ""))[:20]
                        except Exception:
                            content_preview = "<content_error>"
                        try:
                            add_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
                            reasoning_preview = str(add_kwargs.get("reasoning_content", ""))[:20]
                        except Exception:
                            reasoning_preview = "<reasoning_error>"
                    print(f"   [Stream Data] content: '{content_preview}...', reasoning: '{reasoning_preview}...'")

                if event_type == "on_tool_start":
                    tool_name = event_name or metadata.get("tool_name") or "unknown_tool"
                    # region agent log
                    _agent_ndjson_log(
                        "langgraph_tool_start",
                        {"tool_name": tool_name, "node_name": node_name},
                        "H7",
                    )
                    # endregion
                    yield _to_sse_json(
                        {
                            "type": "status",
                            "message": f"正在执行量化分析：{tool_name}",
                        }
                    )
                    continue

                if event_type in ("on_chain_end", "on_tool_end"):
                    output = data.get("output")
                    if isinstance(output, dict) and output.get("toolkit_data"):
                        final_toolkit_data = output.get("toolkit_data") or final_toolkit_data

                if event_type == "on_chat_model_stream" and node_name == "cio_writer":
                    chunk = data.get("chunk")
                    content = getattr(chunk, "content", "")

                    if isinstance(content, list):
                        content = "".join(
                            part.get("text", "") if isinstance(part, dict) else str(part)
                            for part in content
                        )

                    if content:
                        if not first_cio_chunk_logged:
                            # region agent log
                            _agent_ndjson_log(
                                "cio_writer_first_chunk",
                                {"chunk_len": len(content)},
                                "H8",
                            )
                            # endregion
                            first_cio_chunk_logged = True
                        yield _to_sse_data(content)
                    continue

                if event_type == "on_chain_end" and node_name == "cio_writer" and not metrics_sent:
                    output = data.get("output") or {}
                    if isinstance(output, dict) and output.get("toolkit_data"):
                        final_toolkit_data = output.get("toolkit_data") or final_toolkit_data

                    metrics_payload = _build_metrics_payload_from_toolkit(final_toolkit_data)
                    if metrics_payload:
                        # region agent log
                        _agent_ndjson_log("metrics_built", metrics_payload, "H9")
                        # endregion
                        yield _to_sse_json(metrics_payload)
                        metrics_sent = True

            if not metrics_sent:
                metrics_payload = _build_metrics_payload_from_toolkit(final_toolkit_data)
                if metrics_payload:
                    _agent_ndjson_log("metrics_built_fallback", metrics_payload, "H9")
                    yield _to_sse_json(metrics_payload)

            _agent_ndjson_log("langgraph_stream_done", {"ticker": ticker}, "H10")
            yield b"data: [DONE]\n\n"

        except Exception as e:
            _agent_log("sse_stream_exception", {"error": str(e)}, "H3")
            _agent_ndjson_log("sse_stream_exception", {"error": str(e)}, "H5")
            yield _to_sse_data(f"\n[错误] {str(e)}")
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ========== 保持兼容性的旧接口 ==========

@app.post("/api/analyze")
@limiter.limit("3/minute")
async def analyze_compat(request: Request, body: AnalyzeRequest):
    """兼容旧版的非流式分析（仅用于过渡）"""
    return JSONResponse(
        {"error": "请使用 /api/analyze_sse 接口"},
        status_code=410,
    )


# 前端静态资源（与 A 公网 Nginx 配合：Nginx 将 / 转发到 B，B 提供前端 + API）
# 必须从 server-b 目录启动 (python -m uvicorn backend.main:app)，否则 _PROJECT_ROOT 会指向错误路径
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_DIST = _PROJECT_ROOT / "frontend-react" / "dist"

if _FRONTEND_DIST.exists() and _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
else:
    import sys
    print(f"[WARN] frontend dist 不存在，根路径 / 将 404: {_FRONTEND_DIST}", file=sys.stderr)
