from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source: str
    page: int | None = None
    chunk_id: str
    content: str
    score: float


class ToolTrace(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | list[Any] | str | None = None
    status: Literal["success", "error"] = "success"


class PendingAction(BaseModel):
    id: str
    tool: Literal["create_ticket"] = "create_ticket"
    arguments: dict[str, Any]
    summary: str


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    route: str
    citations: list[Citation] = Field(default_factory=list)
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    pending_action: PendingAction | None = None


class ActionRequest(BaseModel):
    thread_id: str
    action_id: str


class RouteDecision(BaseModel):
    route: Literal["knowledge", "business", "combined", "create_ticket", "clarify"]
    order_id: str | None = None
    reason: str = ""


class EvaluationSummary(BaseModel):
    retrieval_hit_rate_at_k: float
    retrieval_top1_accuracy: float
    mean_reciprocal_rank: float
    average_citations: float
    route_accuracy: float
    total_cases: int
    details: list[dict[str, Any]]
