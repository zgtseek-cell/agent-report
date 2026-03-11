from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, AsyncIterator
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ..config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
)
from .state import AgentState
from .tools import (
    get_company_financial_health_snapshot,
    get_company_valuation_metrics,
)

TOOLS = [
    get_company_valuation_metrics,
    get_company_financial_health_snapshot,
]


# region agent log
def _graph_ndjson_log(message: str, data: dict | None = None, hypothesis_id: str = "G?") -> None:
    try:
        payload = {
            "id": f"log_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "location": "backend/agent_core/graph.py",
            "message": message,
            "data": data or {},
            "runId": "pre-fix-2",
            "hypothesisId": hypothesis_id,
        }
        log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# endregion agent log


def _build_llm(model_name: str | None = None, temperature: float = 0.1) -> ChatOpenAI:
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY 未配置，无法运行 LangGraph 投资代理。")

    return ChatOpenAI(
        model=model_name or DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        timeout=DEEPSEEK_TIMEOUT,
        temperature=temperature,
        streaming=True,
    )


def _safe_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)


def _summarize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for idx, message in enumerate(messages):
        tool_calls = getattr(message, "tool_calls", None)
        summary.append(
            {
                "idx": idx,
                "type": message.__class__.__name__,
                "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
                "tool_call_ids": [
                    str(item.get("id"))
                    for item in (tool_calls or [])
                    if isinstance(item, dict) and item.get("id") is not None
                ],
                "tool_name": getattr(message, "name", None),
                "tool_call_id": getattr(message, "tool_call_id", None),
                "content_preview": str(getattr(message, "content", ""))[:120],
            }
        )
    return summary


def _coerce_tool_content(content: Any) -> Any:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, default=str))
            else:
                parts.append(str(item))
        joined = "\n".join(parts).strip()
        if not joined:
            return {}
        try:
            return json.loads(joined)
        except Exception:
            return {"raw_text": joined}
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {"raw_text": text}
    return {"raw_value": str(content)}


def _extract_intrinsic_value(toolkit_data: dict[str, Any]) -> float | None:
    valuation = toolkit_data.get("valuation") or {}
    intrinsic = valuation.get("intrinsic_value") or {}
    value = intrinsic.get("intrinsic_value")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _compute_margin_of_safety(current_price: float | None, intrinsic_value: float | None) -> float | None:
    if current_price is None or intrinsic_value is None or intrinsic_value <= 0:
        return None
    return round((intrinsic_value - current_price) / intrinsic_value * 100, 2)


def _merge_toolkit_data(state: AgentState) -> dict[str, Any]:
    toolkit_data = dict(state.get("toolkit_data") or {})
    raw_tool_outputs = dict(toolkit_data.get("raw_tool_outputs") or {})

    for message in state.get("messages") or []:
        if not isinstance(message, ToolMessage):
            continue
        payload = _coerce_tool_content(message.content)
        tool_name = getattr(message, "name", "") or f"tool_{len(raw_tool_outputs) + 1}"
        raw_tool_outputs[tool_name] = payload
        if tool_name == "get_company_valuation_metrics":
            toolkit_data["valuation"] = payload
        elif tool_name == "get_company_financial_health_snapshot":
            toolkit_data["financial_health"] = payload

    toolkit_data["raw_tool_outputs"] = raw_tool_outputs

    current_price = (state.get("user_context") or {}).get("current_price")
    try:
        current_price_value = float(current_price) if current_price is not None else None
    except Exception:
        current_price_value = None

    intrinsic_value = _extract_intrinsic_value(toolkit_data)
    derived_metrics = dict(toolkit_data.get("derived_metrics") or {})
    derived_metrics["current_price"] = current_price_value
    derived_metrics["intrinsic_value"] = intrinsic_value
    derived_metrics["margin_of_safety_pct"] = _compute_margin_of_safety(current_price_value, intrinsic_value)
    toolkit_data["derived_metrics"] = derived_metrics
    return toolkit_data


def _build_quant_context(state: AgentState, toolkit_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_system_date": datetime.now().strftime("%Y年%m月%d日"),
        "symbol": state.get("symbol", ""),
        "market": state.get("market", ""),
        "user_context": dict(state.get("user_context") or {}),
        "toolkit_data": toolkit_data,
    }


def _build_writer_context(state: AgentState, toolkit_data: dict[str, Any]) -> dict[str, Any]:
    # 【核心新增】：ADR 毒数据物理隔离墙 (Data Masking)
    # 检查是否同时存在 yfinance 数据，且价格币种与财报币种错配（ADR 特征）
    valuation = toolkit_data.get("valuation") or {}
    yf_snapshot = valuation.get("yfinance_snapshot") or {}
    price_curr = yf_snapshot.get("price_currency")
    fin_curr = yf_snapshot.get("financial_currency")

    if price_curr and fin_curr and price_curr != fin_curr:
        # 1. 彻底斩断 intrinsic_value 里的底稿污染
        intrinsic_data = valuation.get("intrinsic_value", {})
        if isinstance(intrinsic_data, dict):
            intrinsic_data.pop("inputs", None)
            intrinsic_data.pop("raw", None)

        # 2. 全地图 AOE 清洗：遍历 raw_tables 下的【所有表格】，无死角追杀毒数据
        raw_tables = valuation.get("raw_tables", {})
        if isinstance(raw_tables, dict):
            # 扩大黑名单，屏蔽一切受美元市值污染的绝对值和比率
            toxic_keywords = [
                "price",
                "market cap",
                "enterprise value",
                "ev-",
                "ev to",
                "earnings yield",
                "dividend yield",
                "free cash flow yield",
                "fcf yield",
            ]

            for table_name, table_data in raw_tables.items():
                if isinstance(table_data, dict):
                    keys_to_delete = [
                        k
                        for k in list(table_data.keys())
                        if any(toxic in str(k).lower() for toxic in toxic_keywords)
                    ]
                    for k in keys_to_delete:
                        table_data.pop(k, None)

            print("[Data Masking] 跨国 ADR 全地图清洗完毕，已彻底抹除所有错误市值与衍生比率。")

    # 终极探针：打印即将喂给大模型的干净上下文
    import json as _json_debug

    try:
        final_context_str = _json_debug.dumps(toolkit_data, ensure_ascii=False, default=str)
        print("===" * 20)
        print(f"[DEBUG] 喂给 CIO 的最终上下文是否包含 80.91: {'80.91' in final_context_str}")
        print(f"[DEBUG] 是否还残留 Yield 关键字: {'yield' in final_context_str.lower()}")
        print("===" * 20)
    except Exception as _e:
        print(f"[DEBUG] writer_context dump failed: {_e}")

    return {
        "current_system_date": datetime.now().strftime("%Y年%m月%d日"),
        "symbol": state.get("symbol", ""),
        "market": state.get("market", ""),
        "user_context": dict(state.get("user_context") or {}),
        "toolkit_data": toolkit_data,
    }


async def quant_researcher(state: AgentState, config: RunnableConfig) -> AgentState:
    toolkit_data = _merge_toolkit_data(state)
    # region agent log
    _graph_ndjson_log(
        "quant_researcher_enter",
        {
            "symbol": state.get("symbol"),
            "market": state.get("market"),
            "has_valuation": bool(toolkit_data.get("valuation")),
            "has_financial_health": bool(toolkit_data.get("financial_health")),
        },
        "G1",
    )
    # endregion agent log

    # 强制使用 deepseek-chat，稳定支持 Tool Calling，避免 reasoner 报错
    llm = _build_llm(model_name="deepseek-chat", temperature=0.0).bind_tools(TOOLS)

    system_message = SystemMessage(
        content=(
            "你是一位擅长本杰明·格雷厄姆风格的量化分析师。\n"
            "你的首要任务是使用提供的工具收集公司的核心估值指标和财务健康度。\n"
            "【防死循环最高指令】：\n"
            "1. 请仔细检查对话历史。如果你发现工具【已经】被调用过，并且成功返回了数据，绝对不要再次调用相同的工具。\n"
            "2. 当数据收集完毕后，请直接输出一段简短的纯文本总结（如：'数据收集完毕，交由CIO处理'），让工作流结束工具调用阶段。"
        )
    )
    human_message = HumanMessage(content=_safe_json_dumps(_build_quant_context(state, toolkit_data)))

    # 关键修复：必须把状态里的 messages 传给模型，让它知道自己已经调用过哪些工具
    messages_to_pass = [system_message, human_message] + (state.get("messages") or [])
    # region agent log
    _graph_ndjson_log(
        "quant_researcher_outgoing_messages",
        {
            "messages": _summarize_messages(messages_to_pass),
        },
        "G4",
    )
    # endregion agent log

    response_chunks: list[Any] = []
    chunk_count = 0
    # region agent log
    _graph_ndjson_log("quant_researcher_astream_start", {"config_present": config is not None}, "G7")
    # endregion agent log
    async for chunk in llm.astream(messages_to_pass, config=config):
        chunk_count += 1
        response_chunks.append(chunk)
    # region agent log
    _graph_ndjson_log("quant_researcher_astream_end", {"chunk_count": chunk_count}, "G7")
    # endregion agent log

    if not response_chunks:
        raise ValueError("LLM returned empty stream in quant_researcher")

    response = response_chunks[0]
    for chunk in response_chunks[1:]:
        response += chunk  # AIMessageChunk 支持相加，会自动合并 tool_calls

    # region agent log
    _graph_ndjson_log(
        "quant_researcher_response",
        {
            "type": response.__class__.__name__,
            "tool_call_count": len(getattr(response, "tool_calls", None) or []),
            "content_preview": str(getattr(response, "content", ""))[:120],
        },
        "G5",
    )
    # endregion agent log

    return {
        "messages": [response],
        "toolkit_data": toolkit_data,
    }


async def cio_writer(state: AgentState, config: RunnableConfig) -> AgentState:
    toolkit_data = _merge_toolkit_data(state)
    # region agent log
    _graph_ndjson_log(
        "cio_writer_enter",
        {
            "symbol": state.get("symbol"),
            "market": state.get("market"),
            "has_valuation": bool(toolkit_data.get("valuation")),
            "has_financial_health": bool(toolkit_data.get("financial_health")),
        },
        "G2",
    )
    # endregion agent log
    # 【终极防幻觉纪律】：强制使用 V3 (deepseek-chat) 替代 R1，并彻底锁死温度
    # V3 在遵循极其严格的 System Prompt（如绝对不准使用某些数据）时，表现远比爱发散的 R1 听话。
    llm = _build_llm(
        model_name="deepseek-chat",
        temperature=0.01,  # 降至冰点，彻底抹杀创造性幻觉
    )

    current_date = datetime.now().strftime("%Y年%m月%d日")
    system_message = SystemMessage(
        content=(
            f"你是一位顶级的华尔街价值投资首席投资官（CIO）。今天是系统真实日期：{current_date}。\n\n"
            "【专业纪律严禁词库】：绝对不准输出'null'、'缺失'、'模型输出为'等抱怨词汇。\n\n"
            "【⚠️ 致命错误警告：货币汇率错配 (Currency Mismatch) ⚠️】：\n"
            "当你分析中概股（如阿里巴巴 BABA）或 ADR 时，请检查 user_context 中的 price_currency。其市场股价通常为【美元 (USD)】，但底层的 EPS 和 BVPS 数据通常为【人民币 (CNY)】。\n"
            "最高红线：**绝对严禁将美元股价直接除以人民币 EPS/BVPS！**这会导致算出来的 PE/PB 极度缩水（例如 PE 变成荒谬的 2 倍）。\n"
            "遇到此类跨币种情况，你必须：\n"
            "1. 优先引用历史平均估值中枢（历史 PE/PB 均值是无量纲的，绝对安全）。\n"
            "2. 在估值部分明确指出：“因股价（美元）与财报（人民币）存在币种差异，本备忘录核心参考相对估值历史百分位”。\n"
            "3. 绝对不要在报告中展示你用错误币种直接相除得出的静态绝对估值！\n\n"
            "【报告深度与篇幅要求】：\n"
            "你必须输出一份详尽、硬核、具备机构级专业度的深度投资备忘录（不少于1500字）。要求：\n"
            "1. 数据驱动：大量引用具体的财务比率、绝对金额和历史百分位。\n"
            "2. 逻辑严密：使用杜邦分析法思维、自由现金流质地分析等专业框架。\n"
            "3. 层次分明：多用加粗、列表、分段，增强可读性。\n\n"
            "【强制输出机构级长篇模板】（必须严格按此结构，每个模块必须进行长篇深度展开）：\n\n"
            "### 深度投资备忘录：[股票名称] ([股票代码])\n"
            f"> **发布日期：** {current_date} | **首席投资官：** 价值投资 AI 核心\n"
            "> **当前市价：** [当前价格] [price_currency] | **用户当前仓位：** [当前仓位]\n"
            "> \n"
            "> **【⚠️ 核心数据状态说明】：** (指令：你必须在此处、正文开始前，用 1-2 句话交代清楚当前的数据底座！如果 API 额度耗尽/缺少历史百分位，或者存在 ADR 跨币种情况，必须在此处进行全局声明！绝对不准漏掉这一段！)\n\n"
            "#### 一、 核心投资结论 (Executive Summary)\n"
            "(用3-4个带有加粗标题的要点，简明扼要概括结论)\n\n"
            "#### 二、 估值与安全边际深度拆解 (Valuation Deep Dive)\n"
            "- **相对估值纵向对比：** (防范跨币种陷阱，深度对比当前与过去5年均值)\n"
            "- **现金流与收益率视角：** (深度分析 FCF Yield 趋势)\n"
            "- **安全边际定性评估：** (深度论述当前价格的赔率与安全边际)\n\n"
            "#### 三、 财务质地与护城河分析 (Fundamentals & Moat)\n"
            "- **盈利能力与资本回报：** (深挖 ROE、毛利率等趋势)\n"
            "- **资产负债与流动性：** (分析债务结构与抗风险能力)\n"
            "- **现金流转化质量：** (分析利润向现金流的转化效率)\n\n"
            "#### 四、 关键风险提示 (Risk Factors)\n"
            "(深入剖析至少3个具体核心风险)\n\n"
            "#### 五、 机构级交易与操作计划 (Actionable Trading Plan)\n"
            "(结合仓位给出明确、可执行的量化操作策略与目标建仓/止盈区间)\n\n"
            "---\n"
            "*免责声明：本报告基于 AI 量化与价值投资逻辑生成，仅供参考，不构成实质性投资建议。*"
        )
    )
    human_message = HumanMessage(content=_safe_json_dumps(_build_writer_context(state, toolkit_data)))
    response_chunks: list[Any] = []
    chunk_count = 0
    # region agent log
    _graph_ndjson_log("cio_writer_astream_start", {"config_present": config is not None}, "G8")
    # endregion agent log
    async for chunk in llm.astream([system_message, human_message], config=config):
        chunk_count += 1
        response_chunks.append(chunk)
    # region agent log
    _graph_ndjson_log("cio_writer_astream_end", {"chunk_count": chunk_count}, "G8")
    # endregion agent log

    if not response_chunks:
        raise ValueError("LLM returned empty stream in cio_writer")

    response = response_chunks[0]
    for chunk in response_chunks[1:]:
        response += chunk
    final_report = response.content if isinstance(response.content, str) else _safe_json_dumps(response.content)
    return {
        "messages": [response],
        "toolkit_data": toolkit_data,
        "final_report": final_report,
    }


def _route_quant_researcher(state: AgentState) -> str:
    route = tools_condition(state)
    # region agent log
    _graph_ndjson_log(
        "route_quant_researcher",
        {
            "route": route,
            "messages": _summarize_messages(state.get("messages") or []),
        },
        "G6",
    )
    # endregion agent log
    if route == "tools":
        return "tools"
    return "cio_writer"


def build_investment_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("quant_researcher", quant_researcher)
    workflow.add_node("tools", ToolNode(tools=TOOLS))
    workflow.add_node("cio_writer", cio_writer)
    workflow.add_edge(START, "quant_researcher")
    workflow.add_conditional_edges(
        "quant_researcher",
        _route_quant_researcher,
        {
            "tools": "tools",
            "cio_writer": "cio_writer",
        },
    )
    workflow.add_edge("tools", "quant_researcher")
    workflow.add_edge("cio_writer", END)
    return workflow.compile()


async def run_investment_agent(
    ticker: str,
    market: str,
    price: float | None = None,
    position: float | None = None,
    extra_prompt: str | None = None,
    company_name: str | None = None,
    model_name: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if not ticker or not ticker.strip():
        raise ValueError("ticker 不能为空")
    if not market or not market.strip():
        raise ValueError("market 不能为空")

    graph = build_investment_graph()
    initial_state: AgentState = {
        "messages": [],
        "symbol": ticker.strip().upper(),
        "market": market.strip().lower(),
        "user_context": {
            "position": position,
            "extraPrompt": extra_prompt or "",
            "companyName": company_name or "",
            "current_price": price,
            "price_currency": None,
            "requested_model": model_name or DEEPSEEK_MODEL,
        },
        "toolkit_data": {},
        "final_report": "",
    }
    # region agent log
    _graph_ndjson_log(
        "run_investment_agent_start",
        {
            "ticker": initial_state["symbol"],
            "market": initial_state["market"],
            "has_price": price is not None,
        },
        "G3",
    )
    # endregion agent log
    async for event in graph.astream_events(initial_state, version="v2"):
        yield event
