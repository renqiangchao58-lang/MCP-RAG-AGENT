from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class SupportRepository:
    """Small SQLite-backed support system used by the MCP server."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    email TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL REFERENCES customers(id),
                    product TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ordered_at TEXT NOT NULL,
                    promised_at TEXT NOT NULL,
                    delivered_at TEXT,
                    delay_days INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL REFERENCES orders(id),
                    ticket_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            if count == 0:
                self._seed(connection)

    @staticmethod
    def _seed(connection: sqlite3.Connection) -> None:
        tiers = ("standard", "silver", "gold", "vip")
        customers = [
            (f"C{i:03d}", f"示例客户{i:02d}", tiers[(i - 1) % len(tiers)], f"customer{i:02d}@example.com")
            for i in range(1, 21)
        ]
        connection.executemany(
            "INSERT INTO customers(id, name, tier, email) VALUES (?, ?, ?, ?)", customers
        )

        statuses = ("processing", "shipped", "delivered", "delayed")
        orders: list[tuple[Any, ...]] = []
        for i in range(1001, 1031):
            customer_index = ((i - 1001) % 20) + 1
            status = statuses[(i - 1001) % len(statuses)]
            delay = 0 if status not in {"delivered", "delayed"} else (i - 1000) % 8
            delivered = "2026-08-20" if status == "delivered" else None
            orders.append(
                (
                    f"A{i}",
                    f"C{customer_index:03d}",
                    f"智能设备-{(i % 5) + 1}",
                    status,
                    "2026-08-10",
                    "2026-08-15",
                    delivered,
                    delay,
                )
            )

        # The primary demo order is a gold customer with a five-day delay.
        demo_index = 1024 - 1001
        orders[demo_index] = (
            "A1024",
            "C003",
            "智能空气净化器 Pro",
            "delayed",
            "2026-08-10",
            "2026-08-15",
            None,
            5,
        )
        connection.executemany(
            """
            INSERT INTO orders(
                id, customer_id, product, status, ordered_at,
                promised_at, delivered_at, delay_days
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            orders,
        )

        tickets = [
            (
                f"T-202608-{i:04d}",
                f"A{1000 + i}",
                "售后咨询",
                f"示例历史工单 {i}",
                "normal",
                "closed" if i % 2 else "open",
                f"2026-08-{i + 1:02d}T09:00:00+00:00",
            )
            for i in range(1, 11)
        ]
        connection.executemany(
            """
            INSERT INTO tickets(
                id, order_id, ticket_type, reason, priority, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tickets,
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT o.*, c.name AS customer_name, c.tier AS customer_tier
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE UPPER(o.id) = UPPER(?)
                """,
                (order_id,),
            ).fetchone()
        if row is None:
            return {"found": False, "order_id": order_id, "error": "订单不存在"}
        return {"found": True, **dict(row)}

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, tier, email FROM customers WHERE UPPER(id) = UPPER(?)",
                (customer_id,),
            ).fetchone()
        if row is None:
            return {"found": False, "customer_id": customer_id, "error": "客户不存在"}
        return {"found": True, **dict(row)}

    def list_tickets(self, order_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, order_id, ticket_type, reason, priority, status, created_at
                FROM tickets WHERE UPPER(order_id) = UPPER(?) ORDER BY created_at DESC
                """,
                (order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_ticket(
        self,
        order_id: str,
        ticket_type: str,
        reason: str,
        priority: str = "normal",
    ) -> dict[str, Any]:
        order = self.get_order(order_id)
        if not order["found"]:
            return {"created": False, "order_id": order_id, "error": "订单不存在"}
        if priority not in {"low", "normal", "high", "urgent"}:
            return {"created": False, "order_id": order_id, "error": "优先级无效"}

        now = datetime.now(UTC).replace(microsecond=0)
        prefix = now.strftime("T-%Y%m%d-")
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM tickets WHERE id LIKE ?", (f"{prefix}%",)
            ).fetchone()[0]
            ticket_id = f"{prefix}{count + 1:04d}"
            connection.execute(
                """
                INSERT INTO tickets(
                    id, order_id, ticket_type, reason, priority, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (ticket_id, order_id.upper(), ticket_type, reason, priority, now.isoformat()),
            )
        return {
            "created": True,
            "ticket_id": ticket_id,
            "order_id": order_id.upper(),
            "ticket_type": ticket_type,
            "reason": reason,
            "priority": priority,
            "status": "open",
            "created_at": now.isoformat(),
        }

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("customers", "orders", "tickets")
            }

