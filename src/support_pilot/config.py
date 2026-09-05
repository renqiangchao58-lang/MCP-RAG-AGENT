from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model_provider: str = "offline"
    openai_api_key: str = ""
    openai_base_url: str = ""
    chat_model: str = "gpt-4.1-mini"
    model_routing_enabled: bool = False

    embedding_provider: str = "hash"
    embedding_model: str = "text-embedding-3-small"
    hash_embedding_dimensions: int = 384

    knowledge_dir: Path = Path("data/knowledge")
    qdrant_path: Path = Path(".data/qdrant")
    qdrant_url: str = ""
    qdrant_collection: str = "support_knowledge"
    support_db_path: Path = Path(".data/support.db")

    mcp_url: str = "http://127.0.0.1:8001/mcp"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_url: str = "http://127.0.0.1:8000"
    log_level: str = "INFO"

    top_k: int = Field(default=5, ge=1, le=20)
    max_citations: int = Field(default=2, ge=1, le=10)
    relevance_ratio: float = Field(default=0.6, ge=0, le=1)
    max_upload_mb: int = Field(default=10, ge=1, le=100)

    @property
    def llm_enabled(self) -> bool:
        return self.model_provider.lower() == "openai" and bool(self.openai_api_key)

    def ensure_directories(self) -> None:
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.parent.mkdir(parents=True, exist_ok=True)
        self.support_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
