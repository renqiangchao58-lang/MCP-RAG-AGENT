from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from support_pilot.business import BusinessGateway, MCPBusinessGateway
from support_pilot.knowledge import KnowledgeService
from support_pilot.model_gateway import ModelGateway
from support_pilot.schemas import ChatResponse, Citation, PendingAction, ToolTrace


class AgentState(TypedDict, total=False):
    user_message: str
    history: list[dict[str, str]]
    last_order_id: str | None
    route: str
    order_id: str | None
    citations: list[dict[str, Any]]
    business_data: dict[str, Any] | list[dict[str, Any]] | None
    tool_traces: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    answer: str


@dataclass
class SessionState:
    history: list[dict[str, str]] = field(default_factory=list)
    last_order_id: str | None = None
    pending_action: PendingAction | None = None


class AgentService:
    """LangGraph workflow joining RAG and MCP business tools."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        business: BusinessGateway | None = None,
        model: ModelGateway | None = None,
    ):
        self.knowledge = knowledge
        self.business = business or MCPBusinessGateway(knowledge.settings)
        self.model = model or ModelGateway(knowledge.settings)
        self.sessions: dict[str, SessionState] = {}
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("route", self._route)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("business_lookup", self._business_lookup)
        graph.add_node("synthesize", self._synthesize)
        graph.add_node("prepare_ticket", self._prepare_ticket)
        graph.add_node("clarify", self._clarify)
        graph.add_edge(START, "route")
        graph.add_conditional_edges("route", self._after_route)
        graph.add_conditional_edges("retrieve", self._after_retrieve)
        graph.add_edge("business_lookup", "synthesize")
        graph.add_edge("synthesize", END)
        graph.add_edge("prepare_ticket", END)
        graph.add_edge("clarify", END)
        return graph.compile()

    async def _route(self, state: AgentState) -> dict[str, Any]:
        decision = await self.model.route(state["user_message"], state.get("last_order_id"))
        return {"route": decision.route, "order_id": decision.order_id}

    @staticmethod
    def _after_route(
        state: AgentState,
    ) -> Literal["retrieve", "business_lookup", "prepare_ticket", "clarify"]:
        route = state["route"]
        if route in {"knowledge", "combined"}:
            return "retrieve"
        if route == "business":
            return "business_lookup"
        if route == "create_ticket":
            return "prepare_ticket"
        return "clarify"

    @staticmethod
    def _after_retrieve(state: AgentState) -> Literal["business_lookup", "synthesize"]:
        return "business_lookup" if state["route"] == "combined" else "synthesize"

    async def _retrieve(self, state: AgentState) -> dict[str, Any]:
        citations = self.knowledge.retrieve(state["user_message"])
        return {"citations": [item.model_dump() for item in citations]}

    async def _business_lookup(self, state: AgentState) -> dict[str, Any]:
        message = state["user_message"]
        order_id = state.get("order_id")
        customer_match = re.search(r"\bC\d{3,}\b", message.upper())
        traces = list(state.get("tool_traces", []))
        try:
            if customer_match:
                customer_id = customer_match.group(0)
                result = await self.business.get_customer(customer_id)
                name, arguments = "get_customer", {"customer_id": customer_id}
            elif order_id and any(word in message for word in ("历史工单", "已有工单", "工单列表")):
                result = await self.business.list_tickets(order_id)
                name, arguments = "list_tickets", {"order_id": order_id}
            elif order_id:
                result = await self.business.get_order(order_id)
                name, arguments = "get_order", {"order_id": order_id}
            else:
                return {
                    "business_data": None,
                    "answer": "请提供订单号（例如 A1024）或客户编号（例如 C003）。",
                }
            traces.append(
                ToolTrace(name=name, arguments=arguments, result=result).model_dump()
            )
            return {"business_data": result, "tool_traces": traces}
        except Exception as exc:
            traces.append(
                ToolTrace(
                    name="business_lookup",
                    arguments={"order_id": order_id},
                    result=str(exc),
                    status="error",
                ).model_dump()
            )
            return {
                "business_data": None,
                "tool_traces": traces,
                "answer": "业务系统暂时不可用，请稍后重试或转人工处理。",
            }

    async def _synthesize(self, state: AgentState) -> dict[str, Any]:
        if state.get("answer") and not state.get("business_data") and not state.get("citations"):
            return {"answer": state["answer"]}
        citations = [Citation.model_validate(item) for item in state.get("citations", [])]
        answer = await self.model.answer(
            state["user_message"],
            citations,
            state.get("business_data"),
            state.get("history", []),
        )
        return {"answer": answer}

    async def _prepare_ticket(self, state: AgentState) -> dict[str, Any]:
        order_id = state.get("order_id")
        if not order_id:
            return {"answer": "创建工单前需要订单号，例如 A1024。", "route": "clarify"}
        traces = list(state.get("tool_traces", []))
        try:
            order = await self.business.get_order(order_id)
            traces.append(
                ToolTrace(
                    name="get_order", arguments={"order_id": order_id}, result=order
                ).model_dump()
            )
        except Exception as exc:
            traces.append(
                ToolTrace(
                    name="get_order",
                    arguments={"order_id": order_id},
                    result=str(exc),
                    status="error",
                ).model_dump()
            )
            return {"answer": "业务系统不可用，暂时无法创建工单。", "tool_traces": traces}
        if not order.get("found"):
            return {"answer": f"订单 {order_id} 不存在，无法创建工单。", "tool_traces": traces}

        delay = int(order.get("delay_days", 0))
        ticket_type = "配送延迟补偿" if delay >= 3 else "售后咨询"
        priority = "high" if delay >= 7 else "normal"
        action = PendingAction(
            id=str(uuid4()),
            arguments={
                "order_id": order_id,
                "ticket_type": ticket_type,
                "reason": state["user_message"],
                "priority": priority,
            },
            summary=f"为订单 {order_id} 创建“{ticket_type}”工单，优先级 {priority}",
        )
        return {
            "pending_action": action.model_dump(),
            "tool_traces": traces,
            "answer": f"待确认：{action.summary}。确认后才会写入业务系统。",
        }

    @staticmethod
    async def _clarify(state: AgentState) -> dict[str, Any]:
        return {"answer": "请补充订单号（例如 A1024），我才能继续查询或创建工单。"}

    def _session(self, thread_id: str) -> SessionState:
        return self.sessions.setdefault(thread_id, SessionState())

    async def chat(self, thread_id: str, message: str) -> ChatResponse:
        session = self._session(thread_id)
        if session.pending_action and message.strip().lower() in {"确认", "确定", "执行", "yes"}:
            return await self.confirm_action(thread_id, session.pending_action.id)
        if session.pending_action and message.strip().lower() in {"取消", "不要", "no"}:
            return self.reject_action(thread_id, session.pending_action.id)

        result = await self.graph.ainvoke(
            {
                "user_message": message,
                "history": session.history,
                "last_order_id": session.last_order_id,
                "citations": [],
                "tool_traces": [],
            }
        )
        if result.get("order_id"):
            session.last_order_id = result["order_id"]
        pending = (
            PendingAction.model_validate(result["pending_action"])
            if result.get("pending_action")
            else None
        )
        session.pending_action = pending
        answer = result.get("answer", "暂时无法生成回答。")
        session.history.extend(
            [{"role": "user", "content": message}, {"role": "assistant", "content": answer}]
        )
        return ChatResponse(
            thread_id=thread_id,
            answer=answer,
            route=result.get("route", "unknown"),
            citations=[Citation.model_validate(item) for item in result.get("citations", [])],
            tool_traces=[ToolTrace.model_validate(item) for item in result.get("tool_traces", [])],
            pending_action=pending,
        )

    async def confirm_action(self, thread_id: str, action_id: str) -> ChatResponse:
        session = self._session(thread_id)
        action = session.pending_action
        if action is None or action.id != action_id:
            raise ValueError("待确认操作不存在或已经处理")
        try:
            result = await self.business.create_ticket(**action.arguments)
            trace = ToolTrace(
                name="create_ticket", arguments=action.arguments, result=result
            )
        except Exception as exc:
            trace = ToolTrace(
                name="create_ticket",
                arguments=action.arguments,
                result=str(exc),
                status="error",
            )
            answer = "业务系统暂时不可用，工单尚未创建；你可以稍后重试或取消。"
            session.history.append({"role": "assistant", "content": answer})
            return ChatResponse(
                thread_id=thread_id,
                answer=answer,
                route="create_ticket",
                tool_traces=[trace],
                pending_action=action,
            )
        if not result.get("created"):
            answer = f"工单创建失败：{result.get('error', '未知错误')}。"
        else:
            answer = f"工单已创建，编号 {result['ticket_id']}，状态为 {result['status']}。"
            session.pending_action = None
        session.history.append({"role": "assistant", "content": answer})
        return ChatResponse(
            thread_id=thread_id,
            answer=answer,
            route="create_ticket",
            tool_traces=[trace],
        )

    def reject_action(self, thread_id: str, action_id: str) -> ChatResponse:
        session = self._session(thread_id)
        action = session.pending_action
        if action is None or action.id != action_id:
            raise ValueError("待确认操作不存在或已经处理")
        session.pending_action = None
        answer = "已取消，本次没有执行任何写操作。"
        session.history.append({"role": "assistant", "content": answer})
        return ChatResponse(thread_id=thread_id, answer=answer, route="create_ticket")
