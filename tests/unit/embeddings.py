"""
Embedding provider abstraction. Real implementation for OpenAI's
embeddings endpoint (widely available, cheap, good default). Swap or
add providers by subclassing — the memory pipeline never talks to an
embeddings API directly.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimensions(self) -> int:
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    MODEL = "text-embedding-3-small"
    DIMS = 1536

    def __init__(self):
        self.api_key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY")

    @property
    def dimensions(self) -> int:
        return self.DIMS

    async def embed(self, text: str) -> list[float]:
        if not self.api_key:
            raise RuntimeError(
                "EMBEDDING_API_KEY (or OPENAI_API_KEY) not set — memory embedding "
                "is unavailable until configured. No vector is fabricated."
            )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.MODEL, "input": text[:8000]},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]


class UnconfiguredEmbeddingProvider(EmbeddingProvider):
    @property
    def dimensions(self) -> int:
        return 1536

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError(
            "No EMBEDDING_PROVIDER configured. Set EMBEDDING_PROVIDER=openai and "
            "EMBEDDING_API_KEY in .env."
        )


def get_embedding_provider() -> EmbeddingProvider:
    provider = os.environ.get("EMBEDDING_PROVIDER", "").lower()
    if provider == "openai":
        return OpenAIEmbeddingProvider()
    return UnconfiguredEmbeddingProvider()
