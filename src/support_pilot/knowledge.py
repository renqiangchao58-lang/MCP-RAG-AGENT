from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from support_pilot.config import Settings, get_settings
from support_pilot.embeddings import HashEmbeddings
from support_pilot.schemas import Citation


ALLOWED_SUFFIXES = {".pdf", ".md", ".txt"}


class KnowledgeService:
    """Document ingestion and cited retrieval backed by Qdrant."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self.embeddings = self._build_embeddings()
        self.client = self._build_client()
        self._store: QdrantVectorStore | None = None
        self._lock = threading.RLock()

    def _build_embeddings(self) -> Embeddings:
        if self.settings.embedding_provider.lower() == "openai":
            if not self.settings.openai_api_key:
                raise ValueError("EMBEDDING_PROVIDER=openai 时必须配置 OPENAI_API_KEY")
            return OpenAIEmbeddings(
                model=self.settings.embedding_model,
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url or None,
            )
        return HashEmbeddings(self.settings.hash_embedding_dimensions)

    def _build_client(self) -> QdrantClient:
        if self.settings.qdrant_url:
            return QdrantClient(url=self.settings.qdrant_url)
        self.settings.qdrant_path.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(self.settings.qdrant_path))

    @property
    def vector_size(self) -> int:
        if isinstance(self.embeddings, HashEmbeddings):
            return self.embeddings.dimensions
        return len(self.embeddings.embed_query("embedding dimension probe"))

    def _ensure_collection(self) -> None:
        name = self.settings.qdrant_collection
        if not self.client.collection_exists(name):
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )
        self._store = QdrantVectorStore(
            client=self.client,
            collection_name=name,
            embedding=self.embeddings,
        )

    @property
    def store(self) -> QdrantVectorStore:
        with self._lock:
            if self._store is None:
                self._ensure_collection()
            assert self._store is not None
            return self._store

    def list_documents(self) -> list[dict[str, object]]:
        files = []
        for path in sorted(self.settings.knowledge_dir.glob("*")):
            if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
                files.append(
                    {
                        "name": path.name,
                        "size": path.stat().st_size,
                        "type": path.suffix.lower().lstrip("."),
                    }
                )
        return files

    def _load_file(self, path: Path) -> list[Document]:
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"不支持的文件类型: {suffix}")
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            documents = []
            for number, page in enumerate(reader.pages, start=1):
                content = page.extract_text() or ""
                if content.strip():
                    documents.append(
                        Document(
                            page_content=content,
                            metadata={"source": path.name, "page": number},
                        )
                    )
            return documents
        text = path.read_text(encoding="utf-8")
        return [Document(page_content=text, metadata={"source": path.name, "page": 1})]

    def load_documents(self) -> list[Document]:
        pages: list[Document] = []
        for path in sorted(self.settings.knowledge_dir.glob("*")):
            if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
                pages.extend(self._load_file(path))
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=100,
            separators=["\n## ", "\n# ", "\n\n", "。", "\n", " "],
        )
        chunks = splitter.split_documents(pages)
        for index, chunk in enumerate(chunks):
            digest = hashlib.sha1(chunk.page_content.encode("utf-8")).hexdigest()[:10]
            chunk.metadata["chunk_id"] = f"{index:04d}-{digest}"
        return chunks

    def rebuild(self) -> dict[str, int]:
        with self._lock:
            chunks = self.load_documents()
            if not chunks:
                raise ValueError("知识库目录中没有可索引的文档")
            name = self.settings.qdrant_collection
            if self.client.collection_exists(name):
                self.client.delete_collection(name)
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )
            self._store = QdrantVectorStore(
                client=self.client,
                collection_name=name,
                embedding=self.embeddings,
            )
            ids = [
                str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{doc.metadata['source']}:{doc.metadata['page']}:{doc.metadata['chunk_id']}",
                    )
                )
                for doc in chunks
            ]
            self._store.add_documents(chunks, ids=ids)
            return {"documents": len(self.list_documents()), "chunks": len(chunks)}

    def has_index(self) -> bool:
        name = self.settings.qdrant_collection
        if not self.client.collection_exists(name):
            return False
        return bool(self.client.get_collection(name).points_count)

    def ensure_index(self) -> None:
        if not self.has_index():
            self.rebuild()

    def retrieve(self, query: str, top_k: int | None = None) -> list[Citation]:
        self.ensure_index()
        candidate_count = top_k or self.settings.top_k
        results = self.store.similarity_search_with_score(
            query=query,
            k=candidate_count,
        )
        ranked = sorted(
            (
                (
                    document,
                    0.55 * float(vector_score)
                    + 0.45 * self._lexical_relevance(query, document.page_content),
                )
                for document, vector_score in results
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            return []

        best_score = ranked[0][1]
        cutoff = best_score * self.settings.relevance_ratio if best_score > 0 else best_score
        selected = [item for item in ranked if item[1] >= cutoff]
        selected = selected[: self.settings.max_citations]
        return [
            Citation(
                source=str(document.metadata.get("source", "unknown")),
                page=int(document.metadata["page"]) if document.metadata.get("page") else None,
                chunk_id=str(document.metadata.get("chunk_id", "unknown")),
                content=document.page_content.strip(),
                score=round(float(score), 4),
            )
            for document, score in selected
        ]

    @staticmethod
    def _lexical_relevance(query: str, content: str) -> float:
        """Return query-token coverage for a small deterministic hybrid reranker."""

        def tokens(text: str) -> set[str]:
            normalized = text.lower()
            result = set(re.findall(r"[a-z0-9]+", normalized))
            for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
                if len(segment) == 1:
                    result.add(segment)
                else:
                    result.update(
                        segment[index : index + 2]
                        for index in range(len(segment) - 1)
                    )
            return result

        query_tokens = tokens(query)
        if not query_tokens:
            return 0.0
        return len(query_tokens & tokens(content)) / len(query_tokens)

    def save_upload(self, filename: str, content: bytes) -> Path:
        safe_name = Path(filename).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError("仅支持 PDF、Markdown 和 TXT 文件")
        target = (self.settings.knowledge_dir / safe_name).resolve()
        knowledge_root = self.settings.knowledge_dir.resolve()
        if knowledge_root not in target.parents:
            raise ValueError("无效文件名")
        target.write_bytes(content)
        return target

    def close(self) -> None:
        self.client.close()
