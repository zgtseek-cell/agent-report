from __future__ import annotations

from typing import Any, TypedDict, Annotated

from langgraph.graph.message import add_messages


class UserContext(TypedDict, total=False):
    """与当前前端/接口命名保持兼容的用户上下文。"""

    position: float
    extraPrompt: str
    companyName: str
    current_price: float
    requested_model: str


class ToolkitData(TypedDict, total=False):
    """工具产出的结构化结果。"""

    valuation: dict[str, Any]
    financial_health: dict[str, Any]
    derived_metrics: dict[str, Any]
    raw_tool_outputs: dict[str, Any]


class AgentState(TypedDict, total=False):
    """LangGraph 全局状态。"""

    messages: Annotated[list[Any], add_messages]
    symbol: str
    market: str
    user_context: dict[str, Any]
    toolkit_data: dict[str, Any]
    final_report: str
