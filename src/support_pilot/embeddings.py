from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from langchain_core.embeddings import Embeddings


class HashEmbeddings(Embeddings):
    """Deterministic offline embeddings for demos and automated tests.

    The implementation uses feature hashing over English tokens, Chinese
    characters and Chinese bigrams. It is intentionally small and requires no
    model download. Production users can switch to OpenAI-compatible embeddings
    through configuration.
    """

    def __init__(self, dimensions: int = 384):
        if dimensions < 32:
            raise ValueError("dimensions must be at least 32")
        self.dimensions = dimensions

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = text.lower()
        words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalized)
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
        bigrams = [chinese[index : index + 2] for index in range(len(chinese) - 1)]
        return words + bigrams

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(self._tokens(text))
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

