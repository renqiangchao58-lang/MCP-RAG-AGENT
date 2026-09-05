from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / ".data"


def start_process(module: str, *arguments: str, log_name: str) -> tuple[subprocess.Popen, object, object]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    stdout = (DATA_DIR / f"{log_name}.out.log").open("w", encoding="utf-8")
    stderr = (DATA_DIR / f"{log_name}.err.log").open("w", encoding="utf-8")
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", module, *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=stdout,
        stderr=stderr,
        creationflags=creation_flags,
    )
    return process, stdout, stderr


def wait_for_json(client: httpx.Client, url: str) -> dict:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            response = client.get(url)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"status": response.text.strip()}
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Service did not become ready at {url}: {last_error}")


def main() -> None:
    processes: list[tuple[subprocess.Popen, object, object]] = []
    try:
        processes.append(
            start_process(
                "support_pilot.mcp_server",
                "--transport",
                "streamable-http",
                log_name="mcp-http",
            )
        )
        processes.append(start_process("support_pilot.api", log_name="api-http"))
        # Local service calls must bypass any corporate/system HTTP proxy.
        with httpx.Client(timeout=20, trust_env=False) as client:
            health = wait_for_json(client, "http://127.0.0.1:8000/health")
            processes.append(
                start_process(
                    "streamlit",
                    "run",
                    "src/support_pilot/ui.py",
                    "--server.headless=true",
                    "--server.port=8501",
                    log_name="web-http",
                )
            )
            web_health = wait_for_json(client, "http://127.0.0.1:8501/_stcore/health")
            combined = client.post(
                "http://127.0.0.1:8000/api/chat",
                json={
                    "thread_id": "http-e2e",
                    "message": "订单 A1024 延迟五天，按政策是否能补偿？",
                },
            )
            combined.raise_for_status()
            combined_data = combined.json()
            pending = client.post(
                "http://127.0.0.1:8000/api/chat",
                json={"thread_id": "http-e2e", "message": "帮我创建工单"},
            )
            pending.raise_for_status()
            pending_data = pending.json()
            if pending_data.get("pending_action") is None:
                raise RuntimeError(
                    "Agent did not prepare the expected action: "
                    f"route={pending_data.get('route')}, answer={pending_data.get('answer')}"
                )
            confirmed = client.post(
                "http://127.0.0.1:8000/api/actions/confirm",
                json={
                    "thread_id": "http-e2e",
                    "action_id": pending_data["pending_action"]["id"],
                },
            )
            confirmed.raise_for_status()
            confirmed_data = confirmed.json()
        print(
            {
                "health": health["status"],
                "web": web_health["status"],
                "mode": health["model_mode"],
                "route": combined_data["route"],
                "citation": combined_data["citations"][0]["source"],
                "mcp_tool": combined_data["tool_traces"][0]["name"],
                "pending_tool": pending_data["pending_action"]["tool"],
                "confirmed": confirmed_data["answer"],
            }
        )
    finally:
        for process, stdout, stderr in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            stdout.close()
            stderr.close()


if __name__ == "__main__":
    main()
