from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from support_pilot import __version__
from support_pilot.agent import AgentService
from support_pilot.business import BusinessGateway, MCPBusinessGateway
from support_pilot.config import Settings, get_settings
from support_pilot.knowledge import KnowledgeService
from support_pilot.model_gateway import ModelGateway
from support_pilot.schemas import ActionRequest, ChatRequest, ChatResponse


logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    business: BusinessGateway | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_settings.validate_api_credentials()
        knowledge = KnowledgeService(runtime_settings)
        try:
            attempts = 20 if runtime_settings.qdrant_url else 1
            for attempt in range(attempts):
                try:
                    await asyncio.to_thread(knowledge.ensure_index)
                    break
                except Exception:
                    if attempt == attempts - 1:
                        raise
                    await asyncio.sleep(0.5)
            agent = AgentService(
                knowledge=knowledge,
                business=business or MCPBusinessGateway(runtime_settings),
                model=ModelGateway(runtime_settings),
            )
            app.state.settings = runtime_settings
            app.state.knowledge = knowledge
            app.state.agent = agent
            yield
        finally:
            knowledge.close()

    app = FastAPI(
        title="SupportPilot AI API",
        version=__version__,
        description="Cited RAG and MCP-powered support agent",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error method=%s path=%s request_id=%s",
                request.method,
                request.url.path,
                request_id,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "服务内部错误，请稍后重试",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            request_id,
        )
        return response

    def knowledge_service(request: Request) -> KnowledgeService:
        return request.app.state.knowledge

    def agent_service(request: Request) -> AgentService:
        return request.app.state.agent

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        knowledge = knowledge_service(request)
        return {
            "status": "ok",
            "version": __version__,
            "knowledge_indexed": knowledge.has_index(),
            "model_mode": "llm" if runtime_settings.llm_enabled else "offline",
            "chat_model": runtime_settings.chat_model,
            "embedding_provider": runtime_settings.embedding_provider,
            "embedding_model": runtime_settings.embedding_model,
            "qdrant_collection": runtime_settings.qdrant_collection,
        }

    @app.get("/api/knowledge/documents")
    async def list_documents(request: Request) -> dict[str, Any]:
        knowledge = knowledge_service(request)
        return {"documents": knowledge.list_documents(), "indexed": knowledge.has_index()}

    @app.post("/api/knowledge/upload")
    async def upload_document(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        content = await file.read()
        limit = runtime_settings.max_upload_mb * 1024 * 1024
        if len(content) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过 {runtime_settings.max_upload_mb} MB 限制",
            )
        knowledge = knowledge_service(request)
        try:
            target = await asyncio.to_thread(
                knowledge.save_upload, file.filename or "upload.txt", content
            )
            result = await asyncio.to_thread(knowledge.rebuild)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": target.name, **result}

    @app.post("/api/knowledge/rebuild")
    async def rebuild_index(request: Request) -> dict[str, int]:
        try:
            return await asyncio.to_thread(knowledge_service(request).rebuild)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        return await agent_service(request).chat(payload.thread_id, payload.message)

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        response = await agent_service(request).chat(payload.thread_id, payload.message)

        async def events() -> AsyncIterator[str]:
            for index in range(0, len(response.answer), 8):
                data = {"type": "token", "data": response.answer[index : index + 8]}
                yield json.dumps(data, ensure_ascii=False) + "\n"
                await asyncio.sleep(0)
            yield json.dumps(
                {"type": "result", "data": response.model_dump(mode="json")},
                ensure_ascii=False,
            ) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.post("/api/actions/confirm", response_model=ChatResponse)
    async def confirm_action(payload: ActionRequest, request: Request) -> ChatResponse:
        try:
            return await agent_service(request).confirm_action(
                payload.thread_id, payload.action_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/actions/reject", response_model=ChatResponse)
    async def reject_action(payload: ActionRequest, request: Request) -> ChatResponse:
        try:
            return agent_service(request).reject_action(payload.thread_id, payload.action_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "support_pilot.api:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
