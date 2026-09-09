from __future__ import annotations

import json
from functools import partial

import httpx
import pytest
from openai import OpenAI
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from support_pilot import check_cloud, embeddings as embeddings_module, model_gateway
from support_pilot.config import Settings
from support_pilot.embeddings import build_embeddings
from support_pilot.model_gateway import ModelGateway


def test_bailian_embedding_wire_format_and_batch_limit():
    settings = Settings(
        _env_file=None,
        model_provider="openai",
        embedding_provider="openai",
        openai_api_key="test-only-key",
        openai_base_url="https://bailian.test/v1",
        embedding_model="text-embedding-v4",
    )
    texts = [f"中文政策片段 {index}" for index in range(23)]
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == "text-embedding-v4"
        assert payload["encoding_format"] == "float"
        assert 1 <= len(payload["input"]) <= 10
        assert all(isinstance(text, str) for text in payload["input"])
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-v4",
                "data": [
                    {"object": "embedding", "index": index, "embedding": [float(text.split()[-1]), 1.0]}
                    for index, text in enumerate(payload["input"])
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    embeddings = build_embeddings(settings)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        embeddings.client = OpenAI(
            api_key="test-only-key", base_url=settings.openai_base_url, http_client=client
        ).embeddings
        vectors = embeddings.embed_documents(texts)
        assert embeddings.embed_query("查询 99") == [99.0, 1.0]

    assert [len(item["input"]) for item in requests] == [10, 10, 3, 1]
    assert [text for item in requests[:3] for text in item["input"]] == texts
    assert vectors == [[float(index), 1.0] for index in range(23)]


@pytest.mark.parametrize("provider", ["chat", "embedding"])
def test_missing_key_cannot_silently_use_offline_mode(provider):
    settings = Settings(
        _env_file=None,
        openai_api_key="",
        model_provider="openai" if provider == "chat" else "offline",
        embedding_provider="openai" if provider == "embedding" else "hash",
    )
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        if provider == "chat":
            ModelGateway(settings)
        else:
            build_embeddings(settings)


def test_chat_and_embeddings_send_distinct_keys_to_the_correct_hosts(monkeypatch):
    settings = Settings(
        _env_file=None,
        model_provider="openai",
        openai_api_key="chat-test-key",
        openai_base_url="https://chat.test/v1",
        chat_model="chat-test-model",
        embedding_provider="openai",
        embedding_api_key="embedding-test-key",
        embedding_base_url="https://embedding.test/v1",
        embedding_model="text-embedding-v4",
    )
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        seen.append(request.url.host)
        if request.url.host == "embedding.test":
            assert request.headers["authorization"] == "Bearer embedding-test-key"
            assert request.url.path == "/v1/embeddings"
            assert payload["model"] == "text-embedding-v4"
            return httpx.Response(200, json={
                "data": [{"embedding": [1.0, 0.0], "index": 0, "object": "embedding"}],
                "model": "text-embedding-v4", "object": "list",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            })
        assert request.url.host == "chat.test"
        assert request.headers["authorization"] == "Bearer chat-test-key"
        assert request.url.path == "/v1/chat/completions"
        assert payload["model"] == "chat-test-model"
        return httpx.Response(200, json={
            "id": "test-response", "object": "chat.completion", "created": 0,
            "model": "chat-test-model",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "连接成功"}}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(embeddings_module, "OpenAIEmbeddings", partial(OpenAIEmbeddings, http_client=client))
        monkeypatch.setattr(model_gateway, "ChatOpenAI", partial(ChatOpenAI, http_client=client))
        assert build_embeddings(settings).embed_query("测试") == [1.0, 0.0]
        assert ModelGateway(settings).model.invoke("测试").content == "连接成功"
    assert seen == ["embedding.test", "chat.test"]


@pytest.mark.parametrize("key,url", [("", "https://embedding.test/v1"), ("embedding-test-key", "")])
def test_partial_embedding_override_cannot_reuse_chat_credentials(key, url):
    settings = Settings(
        _env_file=None, model_provider="openai", openai_api_key="chat-test-key",
        openai_base_url="https://chat.test/v1", embedding_provider="openai",
        embedding_api_key=key, embedding_base_url=url,
    )
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY.*EMBEDDING_BASE_URL"):
        build_embeddings(settings)


def test_chat_only_probe_does_not_require_or_call_embedding(monkeypatch, capsys):
    settings = Settings(
        _env_file=None, model_provider="openai", openai_api_key="chat-test-key",
        openai_base_url="https://chat.test/v1", embedding_provider="openai",
        embedding_api_key="", embedding_base_url="https://embedding.test/v1",
    )
    monkeypatch.setattr(check_cloud, "Settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["check_cloud", "--only", "chat", "--config-only"])
    assert check_cloud.main() == 0
    assert "未发送网络请求" in capsys.readouterr().out
    # Constructing the real chat client must also work without the embedding key.
    assert ModelGateway(settings).model is not None
