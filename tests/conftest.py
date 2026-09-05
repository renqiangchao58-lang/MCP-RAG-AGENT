from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from support_pilot.config import Settings


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    knowledge_dir = tmp_path / "knowledge"
    shutil.copytree(project_root / "data" / "knowledge", knowledge_dir)
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
