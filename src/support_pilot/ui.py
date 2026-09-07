from __future__ import annotations

import json
from uuid import uuid4

import httpx
import streamlit as st

from support_pilot.config import get_settings


settings = get_settings()
API_URL = settings.api_url.rstrip("/")

st.set_page_config(page_title="SupportPilot AI", page_icon="🛟", layout="wide")
st.title("🛟 SupportPilot AI")
st.caption("带来源引用的企业知识库与 MCP 工单执行 Agent")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []


class APIRequestError(RuntimeError):
    pass


def api_error(response: httpx.Response) -> APIRequestError:
    try:
        payload = response.json()
        detail = payload.get("detail", response.text)
    except ValueError:
        detail = response.text or f"HTTP {response.status_code}"
    request_id = response.headers.get("X-Request-ID")
    suffix = f"（请求 ID：{request_id}）" if request_id else ""
    return APIRequestError(f"{detail}{suffix}")


def request_json(method: str, path: str, **kwargs):
    # Local API traffic must not be sent through a system/corporate proxy.
    try:
        with httpx.Client(timeout=60, trust_env=False) as client:
            response = client.request(method, f"{API_URL}{path}", **kwargs)
    except httpx.RequestError as exc:
        raise APIRequestError("无法连接 Agent API，请确认一键启动脚本仍在运行") from exc
    if response.is_error:
        raise api_error(response)
    return response.json()


def render_details(response: dict) -> None:
    citations = response.get("citations", [])
    traces = response.get("tool_traces", [])
    if citations:
        with st.expander(f"引用来源（{len(citations)}）"):
            for item in citations:
                st.markdown(
                    f"**{item['source']} · P{item.get('page') or 1}** "
                    f"`score={item['score']:.3f}`"
                )
                st.caption(item["content"][:500])
    if traces:
        with st.expander(f"MCP 工具调用（{len(traces)}）"):
            for trace in traces:
                icon = "✅" if trace["status"] == "success" else "❌"
                st.markdown(f"{icon} **{trace['name']}**")
                st.json({"arguments": trace["arguments"], "result": trace["result"]})


with st.sidebar:
    st.header("知识库")
    try:
        health = request_json("GET", "/health")
        mode = "DeepSeek / LLM" if health["model_mode"] == "llm" else "离线模式"
        st.success(f"API 已连接 · {mode}")
        status = request_json("GET", "/api/knowledge/documents")
        st.caption(f"已导入 {len(status['documents'])} 份文档")
        for item in status["documents"]:
            st.text(f"• {item['name']}")
    except APIRequestError as exc:
        st.error(f"API 未连接：{exc}")

    uploaded = st.file_uploader("上传文档", type=["pdf", "md", "txt"])
    if uploaded and st.button("导入并重建索引", type="primary"):
        try:
            with st.spinner("正在解析文档并重建索引…"):
                result = request_json(
                    "POST",
                    "/api/knowledge/upload",
                    files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                )
            st.success(f"已索引 {result['documents']} 份文档、{result['chunks']} 个片段")
        except APIRequestError as exc:
            st.error(f"导入失败：{exc}")

    if st.button("新建会话"):
        st.session_state.thread_id = str(uuid4())
        st.session_state.messages = []
        st.rerun()
    st.caption(f"会话：{st.session_state.thread_id[:8]}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            render_details(message.get("response", {}))

prompt = st.chat_input("例如：订单 A1024 延迟 5 天，按政策是否可以补偿？")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        result_holder: dict = {}

        def token_stream():
            try:
                with httpx.Client(timeout=120, trust_env=False) as client:
                    with client.stream(
                        "POST",
                        f"{API_URL}/api/chat/stream",
                        json={"thread_id": st.session_state.thread_id, "message": prompt},
                    ) as response:
                        if response.is_error:
                            response.read()
                            raise api_error(response)
                        for line in response.iter_lines():
                            if not line:
                                continue
                            event = json.loads(line)
                            if event["type"] == "token":
                                yield event["data"]
                            elif event["type"] == "result":
                                result_holder.update(event["data"])
            except httpx.RequestError as exc:
                raise APIRequestError(
                    "与 Agent API 的连接中断，请确认服务仍在运行"
                ) from exc

        try:
            answer = st.write_stream(token_stream())
            render_details(result_holder)
            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "response": result_holder}
            )
        except (APIRequestError, json.JSONDecodeError) as exc:
            st.error(f"请求失败：{exc}")

pending = next(
    (
        message.get("response", {}).get("pending_action")
        for message in reversed(st.session_state.messages)
        if message.get("response", {}).get("pending_action")
    ),
    None,
)
if pending:
    st.warning(f"待确认操作：{pending['summary']}")
    confirm_col, reject_col = st.columns(2)
    if confirm_col.button("确认执行", type="primary", use_container_width=True):
        try:
            result = request_json(
                "POST",
                "/api/actions/confirm",
                json={"thread_id": st.session_state.thread_id, "action_id": pending["id"]},
            )
            st.session_state.messages.append(
                {"role": "assistant", "content": result["answer"], "response": result}
            )
            # Clear the stale pending action from prior UI history.
            for message in st.session_state.messages:
                prior = message.get("response", {}).get("pending_action") or {}
                if prior.get("id") == pending["id"]:
                    message["response"]["pending_action"] = None
            st.rerun()
        except APIRequestError as exc:
            st.error(f"执行失败：{exc}")
    if reject_col.button("取消", use_container_width=True):
        try:
            result = request_json(
                "POST",
                "/api/actions/reject",
                json={"thread_id": st.session_state.thread_id, "action_id": pending["id"]},
            )
            st.session_state.messages.append(
                {"role": "assistant", "content": result["answer"], "response": result}
            )
            for message in st.session_state.messages:
                prior = message.get("response", {}).get("pending_action") or {}
                if prior.get("id") == pending["id"]:
                    message["response"]["pending_action"] = None
            st.rerun()
        except APIRequestError as exc:
            st.error(f"取消失败：{exc}")
