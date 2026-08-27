"""Real tests for the embedding provider selection logic (not the live
API call itself, which needs a real key — that's an integration-test
concern, see docs/TESTING.md)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from embeddings import (OpenAIEmbeddingProvider, UnconfiguredEmbeddingProvider,
                         get_embedding_provider)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_unconfigured_provider_selected_by_default():
    os.environ.pop("EMBEDDING_PROVIDER", None)
    provider = get_embedding_provider()
    assert isinstance(provider, UnconfiguredEmbeddingProvider)


def test_unconfigured_provider_raises_clearly_not_fake_vector():
    provider = UnconfiguredEmbeddingProvider()
    try:
        run(provider.embed("hello"))
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "EMBEDDING_PROVIDER" in str(e)


def test_openai_provider_selected_when_configured():
    os.environ["EMBEDDING_PROVIDER"] = "openai"
    provider = get_embedding_provider()
    assert isinstance(provider, OpenAIEmbeddingProvider)
    os.environ.pop("EMBEDDING_PROVIDER", None)


def test_openai_provider_raises_without_key():
    os.environ.pop("EMBEDDING_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    provider = OpenAIEmbeddingProvider()
    try:
        run(provider.embed("hello"))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
