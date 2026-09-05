from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

from support_pilot.config import Settings, get_settings
from support_pilot.repository import SupportRepository


def _local_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an MCP client that never sends localhost traffic to a proxy."""
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout or httpx.Timeout(30, read=300),
        auth=auth,
        follow_redirects=True,
        trust_env=False,
    )


class BusinessGateway(Protocol):
    async def get_order(self, order_id: str) -> dict[str, Any]: ...

    async def get_customer(self, customer_id: str) -> dict[str, Any]: ...

    async def list_tickets(self, order_id: str) -> list[dict[str, Any]]: ...

    async def create_ticket(
        self, order_id: str, ticket_type: str, reason: str, priority: str = "normal"
    ) -> dict[str, Any]: ...


class LocalBusinessGateway:
    """In-process gateway for offline evaluation; production uses MCP."""

    def __init__(self, repository: SupportRepository):
        self.repository = repository

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return self.repository.get_order(order_id)

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        return self.repository.get_customer(customer_id)

    async def list_tickets(self, order_id: str) -> list[dict[str, Any]]:
        return self.repository.list_tickets(order_id)

    async def create_ticket(
        self, order_id: str, ticket_type: str, reason: str, priority: str = "normal"
    ) -> dict[str, Any]:
        return self.repository.create_ticket(order_id, ticket_type, reason, priority)


class MCPBusinessGateway:
    """Business gateway that invokes tools discovered from an MCP server."""

    def __init__(
        self,
        settings: Settings | None = None,
        connections: dict[str, Any] | None = None,
    ):
        settings = settings or get_settings()
        http_connection: dict[str, Any] = {
            "transport": "http",
            "url": settings.mcp_url,
        }
        if urlparse(settings.mcp_url).hostname in {"127.0.0.1", "localhost", "::1"}:
            http_connection["httpx_client_factory"] = _local_mcp_http_client
        self.client = MultiServerMCPClient(
            connections
            or {
                "support": http_connection
            }
        )

    @staticmethod
    def stdio_connection(
        python_executable: str,
        cwd: str | Path,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "support": {
                "transport": "stdio",
                "command": python_executable,
                "args": ["-m", "support_pilot.mcp_server", "--transport", "stdio"],
                "cwd": str(cwd),
                "env": env,
            }
        }

    @staticmethod
    def _normalize_result(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        if isinstance(value, list) and len(value) == 1:
            item = value[0]
            if isinstance(item, dict) and item.get("type") == "text":
                return MCPBusinessGateway._normalize_result(item.get("text", ""))
        if isinstance(value, dict):
            if "structured_content" in value:
                return value["structured_content"]
            if "content" in value and len(value) <= 2:
                return MCPBusinessGateway._normalize_result(value["content"])
        return value

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        tools = {tool.name: tool for tool in await self.client.get_tools()}
        if name not in tools:
            raise RuntimeError(f"MCP Server 未提供工具: {name}")
        result = await tools[name].ainvoke(arguments)
        return self._normalize_result(result)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._call("get_order", {"order_id": order_id})

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        return await self._call("get_customer", {"customer_id": customer_id})

    async def list_tickets(self, order_id: str) -> list[dict[str, Any]]:
        return await self._call("list_tickets", {"order_id": order_id})

    async def create_ticket(
        self, order_id: str, ticket_type: str, reason: str, priority: str = "normal"
    ) -> dict[str, Any]:
        return await self._call(
            "create_ticket",
            {
                "order_id": order_id,
                "ticket_type": ticket_type,
                "reason": reason,
                "priority": priority,
            },
        )
