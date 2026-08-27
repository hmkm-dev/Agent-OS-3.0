"""
E2E: proves write -> index -> search -> retrieve against a real
Qdrant Cloud collection and real embeddings, not the fake-DB unit
tests. Requires QDRANT_URL/QDRANT_API_KEY and
EMBEDDING_PROVIDER=openai + EMBEDDING_API_KEY configured, and a
reachable Postgres (DATABASE_URL).

    DATABASE_URL=... QDRANT_URL=... QDRANT_API_KEY=... \
    EMBEDDING_PROVIDER=openai EMBEDDING_API_KEY=... \
        python3 -m pytest tests/e2e/test_memory.py -v -s

SKIPS honestly if these aren't set — not executed in the environment
that generated this repo (no live Postgres/Qdrant there).
"""
import asyncio
import os
import sys

import pytest

REQUIRED = ["DATABASE_URL", "QDRANT_URL", "QDRANT_API_KEY", "EMBEDDING_API_KEY"]
missing = [v for v in REQUIRED if not os.environ.get(v)]

pytestmark = [pytest.mark.e2e, pytest.mark.external, pytest.mark.skipif(
    bool(missing),
    reason=f"EXTERNAL_CREDENTIAL_REQUIRED: missing env vars: {missing}. See module docstring.",
)]

if not missing:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "hermes"))
    from db import DB  # noqa: E402
    from memory.pipeline import MemoryPipeline  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_write_search_retrieve_roundtrip():
    db = DB()
    pipeline = MemoryPipeline(db)

    content = "The Oracle Always Free ARM tier was reduced to 2 OCPU / 12GB RAM in June 2026."
    stored = run(pipeline.store_memory(
        agent_id=None, session_id=None, task_id=None,
        source="e2e_test", type_="fact", content=content,
    ))
    assert stored["memory_id"]
    assert stored["qdrant_point_id"]

    try:
        hits = run(pipeline.search_memory("Oracle free tier RAM limit", top_k=3))
        assert len(hits) > 0, "search returned no results for a query that should match the stored memory"
        assert any(h.get("memory_id") == stored["memory_id"] for h in hits), (
            "the memory we just stored didn't come back in search results — "
            "embedding/search pipeline may be broken even though write succeeded"
        )
    finally:
        # cleanup — don't leave test data in the real collection
        run(pipeline.delete_memory(stored["memory_id"]))
