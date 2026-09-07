from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from support_pilot.config import get_settings
from support_pilot.repository import SupportRepository


settings = get_settings()
repository = SupportRepository(settings.support_db_path)
mcp = FastMCP(
    "SupportPilot AI Business System",
    instructions="Query demo customers/orders/tickets and create support tickets.",
    host=settings.mcp_host,
    port=settings.mcp_port,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def get_order(order_id: str) -> dict[str, Any]:
    """Return order status, delivery dates, delay and customer tier by order ID."""
    return repository.get_order(order_id)


@mcp.tool()
def get_customer(customer_id: str) -> dict[str, Any]:
    """Return a customer's basic profile and service tier by customer ID."""
    return repository.get_customer(customer_id)


@mcp.tool()
def list_tickets(order_id: str) -> list[dict[str, Any]]:
    """List support tickets associated with an order."""
    return repository.list_tickets(order_id)


@mcp.tool()
def create_ticket(
    order_id: str,
    ticket_type: str,
    reason: str,
    priority: str = "normal",
) -> dict[str, Any]:
    """Create a support ticket. The calling application must obtain user approval first."""
    return repository.create_ticket(order_id, ticket_type, reason, priority)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SupportPilot MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="streamable-http",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
