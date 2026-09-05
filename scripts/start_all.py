from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / ".data"
LOG_DIR = DATA_DIR / "logs"


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_port(port: int, process: subprocess.Popen, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port):
            return
        if process.poll() is not None:
            raise RuntimeError(f"process exited with code {process.returncode}")
        time.sleep(0.25)
    raise RuntimeError(f"port {port} did not become ready")


def wait_for_http(
    url: str, process: subprocess.Popen | None = None, timeout: float = 30
) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    with httpx.Client(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"process exited with code {process.returncode}")
            try:
                response = client.get(url)
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError:
                    return {"status": response.text.strip()}
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
    raise RuntimeError(f"{url} did not become ready: {last_error}")


def start_service(name: str, module: str, *arguments: str) -> tuple[subprocess.Popen, object, object]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    stdout = (LOG_DIR / f"{name}.out.log").open("a", encoding="utf-8")
    stderr = (LOG_DIR / f"{name}.err.log").open("a", encoding="utf-8")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "-m", module, *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=stdout,
        stderr=stderr,
        creationflags=flags,
    )
    return process, stdout, stderr


def tail_log(name: str, lines: int = 30) -> str:
    path = LOG_DIR / f"{name}.err.log"
    if not path.exists():
        return "(no log)"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def main() -> None:
    services: dict[str, tuple[subprocess.Popen, object, object]] = {}
    status: dict[str, str] = {}
    try:
        if port_open(8001):
            status["mcp"] = "already_running"
        else:
            services["mcp"] = start_service(
                "mcp", "support_pilot.mcp_server", "--transport", "streamable-http"
            )
            wait_for_port(8001, services["mcp"][0])
            status["mcp"] = "started"

        if port_open(8000):
            api_health = wait_for_http("http://127.0.0.1:8000/health", timeout=5)
            status["api"] = "already_running"
        else:
            services["api"] = start_service("api", "support_pilot.api")
            api_health = wait_for_http(
                "http://127.0.0.1:8000/health", services["api"][0], timeout=45
            )
            status["api"] = "started"

        if port_open(8501):
            web_health = wait_for_http(
                "http://127.0.0.1:8501/_stcore/health", timeout=5
            )
            status["web"] = "already_running"
        else:
            services["web"] = start_service(
                "web",
                "streamlit",
                "run",
                "src/support_pilot/ui.py",
                "--server.headless=true",
                "--server.port=8501",
            )
            web_health = wait_for_http(
                "http://127.0.0.1:8501/_stcore/health", services["web"][0]
            )
            status["web"] = "started"

        runtime = {
            "started_at": datetime.now(UTC).isoformat(),
            "services": {
                name: {"pid": service[0].pid}
                for name, service in services.items()
            },
        }
        (DATA_DIR / "runtime.json").write_text(
            json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "mcp": "http://127.0.0.1:8001/mcp",
                    "api": "http://127.0.0.1:8000",
                    "web": "http://127.0.0.1:8501",
                    "model_mode": api_health.get("model_mode"),
                    "web_status": web_health.get("status"),
                    "services": status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception as exc:
        for process, stdout, stderr in reversed(list(services.values())):
            if process.poll() is None:
                process.terminate()
            stdout.close()
            stderr.close()
        print(f"启动失败: {exc}", file=sys.stderr)
        for name in services:
            print(f"\n--- {name} error log ---\n{tail_log(name)}", file=sys.stderr)
        raise SystemExit(1) from exc
    else:
        for _, stdout, stderr in services.values():
            stdout.close()
            stderr.close()


if __name__ == "__main__":
    main()
