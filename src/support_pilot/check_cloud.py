"""Probe configured cloud APIs using synthetic text, without opening a database."""

from __future__ import annotations

import argparse
import math

from support_pilot.config import Settings
from support_pilot.embeddings import build_embeddings
from support_pilot.model_gateway import ModelGateway


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-only", action="store_true", help="Do not send API requests")
    parser.add_argument("--only", choices=["chat", "embedding", "both"], default="both")
    args = parser.parse_args()
    settings = Settings()
    check_chat = args.only in {"chat", "both"}
    check_embedding = args.only in {"embedding", "both"}
    try:
        settings.validate_api_credentials(chat=check_chat, embedding=check_embedding)
        if check_chat:
            if settings.model_provider.lower() != "openai":
                raise ValueError("请将 MODEL_PROVIDER 设为 openai")
            if not settings.openai_base_url.strip():
                raise ValueError("请填写对话服务商的 OPENAI_BASE_URL")
        if check_embedding:
            if settings.embedding_provider.lower() != "openai":
                raise ValueError("请将 EMBEDDING_PROVIDER 设为 openai")
            if not settings.effective_embedding_base_url.strip():
                raise ValueError("请填写 EMBEDDING_BASE_URL 或共用的 OPENAI_BASE_URL")
    except ValueError as exc:
        print(f"配置未就绪：{exc}")
        return 2

    if check_chat:
        print(f"对话配置就绪：{settings.chat_model}")
    if check_embedding:
        print(f"向量配置就绪：{settings.embedding_model}")
    if args.config_only:
        print("未发送网络请求；此结果不代表云端接口已连通。")
        return 0

    stage = "配置"
    try:
        if check_embedding:
            stage = "Embedding"
            vectors = build_embeddings(settings).embed_documents(
                ["这是一条向量接口连接测试。", "测试售后政策检索。"]
            )
            if (
                len(vectors) != 2
                or not vectors[0]
                or len(vectors[0]) != len(vectors[1])
                or any(not math.isfinite(value) for row in vectors for value in row)
                or any(not any(row) for row in vectors)
            ):
                raise ValueError("Invalid embedding response")
            print(f"PASS Embedding：返回 2 条向量，维度 {len(vectors[0])}")
        if check_chat:
            stage = "对话"
            model = ModelGateway(settings).model
            assert model is not None
            # Bypass offline fallback when testing cloud connectivity.
            response = model.invoke("这是接口连接测试，请只回复：连接成功。")
            if not response.content:
                raise ValueError("Empty chat response")
            print("PASS 对话：收到模型非空回答")
    except Exception as exc:
        # Do not echo provider error bodies, request text, or credentials.
        status = getattr(exc, "status_code", None)
        print(f"FAIL {stage}：{type(exc).__name__}" + (f" HTTP {status}" if status else ""))
        print("请核对密钥与地域、模型权限、余额及网络；本次未修改知识库。")
        return 1
    print("所选接口测试通过。仅发送了测试句子，未读取或上传知识库。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
