from fastapi.testclient import TestClient

from support_pilot.api import create_app
from support_pilot.business import LocalBusinessGateway
from support_pilot.repository import SupportRepository


def test_health_chat_and_confirmation(app_settings):
    repository = SupportRepository(app_settings.support_db_path)
    app = create_app(app_settings, LocalBusinessGateway(repository))

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["knowledge_indexed"] is True

        chat = client.post(
            "/api/chat",
            json={"thread_id": "api-test", "message": "帮订单 A1024 创建工单"},
        )
        assert chat.status_code == 200
        pending = chat.json()["pending_action"]
        assert pending is not None
        assert repository.counts()["tickets"] == 10

        confirmed = client.post(
            "/api/actions/confirm",
            json={"thread_id": "api-test", "action_id": pending["id"]},
        )
        assert confirmed.status_code == 200
        assert repository.counts()["tickets"] == 11


def test_stream_endpoint_returns_tokens_and_result(app_settings):
    repository = SupportRepository(app_settings.support_db_path)
    app = create_app(app_settings, LocalBusinessGateway(repository))

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream",
            json={"thread_id": "stream-test", "message": "主机保修多久？"},
        )
    lines = [line for line in response.text.splitlines() if line]
    assert '"type": "token"' in lines[0]
    assert '"type": "result"' in lines[-1]

