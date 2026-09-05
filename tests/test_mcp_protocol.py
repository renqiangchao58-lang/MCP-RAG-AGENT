import os
import sys
from pathlib import Path

import pytest

from support_pilot.business import MCPBusinessGateway


@pytest.mark.asyncio
async def test_stdio_mcp_tool_discovery_and_call(app_settings):
    project_root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(project_root / "src")
    environment["SUPPORT_DB_PATH"] = str(app_settings.support_db_path)
    connections = MCPBusinessGateway.stdio_connection(
        python_executable=sys.executable,
        cwd=project_root,
        env=environment,
    )
    gateway = MCPBusinessGateway(app_settings, connections=connections)

    order = await gateway.get_order("A1024")

    assert order["found"] is True
    assert order["delay_days"] == 5
    assert order["customer_tier"] == "gold"

