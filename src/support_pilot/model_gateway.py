from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from support_pilot.config import Settings, get_settings
from support_pilot.schemas import Citation, RouteDecision


ORDER_PATTERN = re.compile(r"\bA\d{4,}\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


class ModelGateway:
    """LLM routing/generation with a deterministic offline fallback."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.validate_api_credentials(embedding=False)
        self.model: ChatOpenAI | None = None
        if self.settings.llm_enabled:
            self.model = ChatOpenAI(
                model=self.settings.chat_model,
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url or None,
                temperature=0,
                timeout=30,
                max_retries=1,
            )

    @staticmethod
    def heuristic_route(message: str, last_order_id: str | None = None) -> RouteDecision:
        order_match = ORDER_PATTERN.search(message.upper())
        order_id = order_match.group(0).upper() if order_match else last_order_id
        create_words = ("创建工单", "新建工单", "建个工单", "提交工单", "生成工单")
        knowledge_words = (
            "政策",
            "规则",
            "补偿",
            "退款",
            "退货",
            "换货",
            "保修",
            "售后",
            "能否",
            "是否",
            "几天",
        )
        business_words = ("订单", "客户", "物流", "状态", "历史工单", "已有工单")
        wants_create = any(word in message for word in create_words)
        needs_knowledge = any(word in message for word in knowledge_words)
        needs_business = bool(order_match) or any(word in message for word in business_words)
        if wants_create:
            route = "create_ticket" if order_id else "clarify"
        elif needs_knowledge and needs_business and order_id:
            route = "combined"
        elif needs_business:
            route = "business"
        else:
            route = "knowledge"
        return RouteDecision(route=route, order_id=order_id, reason="heuristic")

    async def route(self, message: str, last_order_id: str | None = None) -> RouteDecision:
        fallback = self.heuristic_route(message, last_order_id)
        # Explicit write intent is a safety boundary, not a probabilistic model
        # decision. Keep creation/clarification deterministic so an LLM cannot
        # accidentally skip the approval workflow or lose the current order.
        if fallback.route in {"create_ticket", "clarify"}:
            return fallback
        if self.model is None or not self.settings.model_routing_enabled:
            return fallback
        router = self.model.with_structured_output(RouteDecision)
        try:
            decision = await router.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是售后 Agent 路由器。knowledge=只需查政策文档；business=只查订单/"
                            "客户/工单；combined=同时查文档和订单；create_ticket=用户明确要求新建"
                            "工单；clarify=执行所需订单号缺失。不要执行任何工具。"
                        )
                    ),
                    HumanMessage(
                        content=f"最近订单号: {last_order_id or '无'}\n用户消息: {message}"
                    ),
                ]
            )
            if decision.order_id is None:
                decision.order_id = fallback.order_id
            return decision
        except Exception as exc:
            logger.warning("LLM routing failed; using deterministic fallback: %s", exc)
            return fallback

    async def answer(
        self,
        question: str,
        citations: list[Citation],
        business_data: dict[str, Any] | list[dict[str, Any]] | None,
        history: list[dict[str, str]],
    ) -> str:
        if self.model is None:
            return self._offline_answer(question, citations, business_data)
        context = "\n\n".join(
            f"[{item.source}#P{item.page or 1}] {item.content}" for item in citations
        )
        prompt = (
            f"用户问题：{question}\n\n知识库片段：\n{context or '无'}\n\n"
            f"业务系统数据：\n{json.dumps(business_data, ensure_ascii=False) if business_data else '无'}\n\n"
            "只根据给定信息回答。知识性结论使用 [来源: 文件名#P页码] 引用。资料不足时明确说明。"
        )
        messages = [
            SystemMessage(content="你是谨慎的企业售后助手，不编造政策或业务状态。"),
            *[
                HumanMessage(content=item["content"])
                for item in history[-4:]
                if item.get("role") == "user"
            ],
            HumanMessage(content=prompt),
        ]
        try:
            response = await self.model.ainvoke(messages)
            return str(response.content)
        except Exception as exc:
            logger.warning("LLM answer failed; using offline fallback: %s", exc)
            return self._offline_answer(question, citations, business_data)

    @staticmethod
    def _offline_answer(
        question: str,
        citations: list[Citation],
        business_data: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> str:
        source = citations[0] if citations else None
        source_label = f"[来源: {source.source}#P{source.page or 1}]" if source else ""
        if isinstance(business_data, dict) and business_data.get("found"):
            order_id = business_data.get("id")
            delay = int(business_data.get("delay_days", 0))
            tier = str(business_data.get("customer_tier", "standard"))
            if citations and any(word in question for word in ("补偿", "政策", "是否", "能否")):
                if 3 <= delay <= 6:
                    amount = 50 if tier in {"gold", "vip"} else 30
                    return (
                        f"订单 {order_id} 延迟 {delay} 天，客户等级为 {tier}，符合 3–6 天配送延迟"
                        f"补偿条件，建议补偿 {amount} 元代金券。创建补偿工单前仍需用户确认。{source_label}"
                    )
                if delay >= 7:
                    return (
                        f"订单 {order_id} 延迟 {delay} 天，已达到 7 天补偿档位，可选择退还运费或"
                        f"领取 80 元代金券；执行前需核验例外情况并确认。{source_label}"
                    )
                return f"订单 {order_id} 延迟 {delay} 天，尚未达到 3 天补偿门槛。{source_label}"
            return (
                f"订单 {order_id} 当前状态为 {business_data.get('status')}，商品为"
                f"“{business_data.get('product')}”，延迟 {delay} 天，客户等级为 {tier}。"
            )
        if isinstance(business_data, list):
            if not business_data:
                return "该订单目前没有关联工单。"
            ids = "、".join(str(item.get("id")) for item in business_data)
            return f"查询到 {len(business_data)} 条关联工单：{ids}。"
        if isinstance(business_data, dict):
            if business_data.get("error"):
                return f"业务系统返回：{business_data['error']}。"
            if business_data.get("id", "").startswith("C"):
                return (
                    f"客户 {business_data['id']}：{business_data.get('name')}，等级"
                    f" {business_data.get('tier')}。"
                )
        if source:
            excerpt = source.content.replace("\n", " ")[:260]
            return f"根据知识库：{excerpt}{'…' if len(source.content) > 260 else ''} {source_label}"
        return "当前知识库和业务系统中没有足够信息，建议补充订单号或转人工处理。"
