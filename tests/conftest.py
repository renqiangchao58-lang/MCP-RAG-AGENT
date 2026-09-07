from __future__ import annotations

from pathlib import Path

import pytest

from support_pilot.config import Settings


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    bundled_documents = (
        "产品保修手册.md",
        "售后补偿政策.md",
        "客服操作规范.md",
        "退换货规则.md",
    )
    for name in bundled_documents:
        source = project_root / "data" / "knowledge" / name
        (knowledge_dir / name).write_bytes(source.read_bytes())
    return Settings(
        model_provider="offline",
        embedding_provider="hash",
        knowledge_dir=knowledge_dir,
        qdrant_path=tmp_path / "qdrant",
        qdrant_collection="test_collection",
        support_db_path=tmp_path / "support.db",
        top_k=5,
        max_citations=2,
        relevance_ratio=0.6,
    )
