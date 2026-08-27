"""
Memory pipeline — Phase C. This closes the gap flagged in the previous
audit: `memory_records` existed in Postgres but nothing populated
`qdrant_point_id`. This module is that missing write path, plus
retrieval.

Task -> Result -> Evaluator -> Memory Extraction -> Embedding -> Qdrant
                                      |
                                Postgres (memory_records, pointer row)

Retention policy: configurable per call via `retention_policy`; a
default policy of "default" is NOT "forever" — `sweep_expired()`
implements a real deletion pass, not just a documented intention. Call
it from a cron job (see scripts/memory_sweep.sh) if you want automatic
pruning; nothing prunes automatically on its own.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from .embeddings import get_embedding_provider
from . import qdrant_client as qc

# retention_policy name -> days to keep (None = keep indefinitely)
RETENTION_POLICIES = {
    "default": 180,
    "short": 30,
    "permanent": None,
}


class MemoryPipeline:
    def __init__(self, db):
        self.db = db
        self.embedder = get_embedding_provider()

    async def store_memory(self, agent_id: str | None, session_id: str | None, task_id: str | None,
                            source: str, type_: str, content: str,
                            retention_policy: str = "default", importance: float = 0.5) -> dict:
        if retention_policy not in RETENTION_POLICIES:
            raise ValueError(f"unknown retention_policy '{retention_policy}'")

        memory_id = str(uuid.uuid4())

        vector = await self.embedder.embed(content)
        await qc.ensure_collection(self.embedder.dimensions)
        point_id = await qc.upsert_point(
            vector=vector,
            payload={
                "memory_id": memory_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "task_id": task_id,
                "type": type_,
                "source": source,
                "importance": importance,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        await self.db.execute(
            """
            INSERT INTO memory_records
                (memory_id, agent_id, session_id, task_id, source, type, content,
                 qdrant_point_id, retention_policy, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            memory_id, agent_id, session_id, task_id, source, type_, content,
            point_id, retention_policy, datetime.now(timezone.utc),
        )
        return {"memory_id": memory_id, "qdrant_point_id": point_id}

    async def search_memory(self, query: str, top_k: int = 5,
                             agent_id: str | None = None, type_: str | None = None) -> list[dict]:
        vector = await self.embedder.embed(query)
        filter_ = None
        must = []
        if agent_id:
            must.append({"key": "agent_id", "match": {"value": agent_id}})
        if type_:
            must.append({"key": "type", "match": {"value": type_}})
        if must:
            filter_ = {"must": must}

        hits = await qc.search(vector, top_k=top_k, filter_=filter_)
        return [{"score": h["score"], **h.get("payload", {})} for h in hits]

    async def retrieve_relevant_memory(self, query: str, agent_id: str, top_k: int = 5) -> str:
        """Convenience wrapper returning a formatted context block ready
        to prepend to a model prompt — this is what Research/Creative
        workers should call before synthesizing, once wired in."""
        hits = await self.search_memory(query, top_k=top_k, agent_id=agent_id)
        if not hits:
            return ""
        lines = [f"- ({h.get('type')}, score={h['score']:.2f}) memory_id={h.get('memory_id')}" for h in hits]
        return "Relevant prior memory:\n" + "\n".join(lines)

    async def delete_memory(self, memory_id: str) -> None:
        row = await self.db.fetchrow(
            "SELECT qdrant_point_id FROM memory_records WHERE memory_id = $1", memory_id
        )
        if row and row["qdrant_point_id"]:
            await qc.delete_point(row["qdrant_point_id"])
        await self.db.execute("DELETE FROM memory_records WHERE memory_id = $1", memory_id)

    async def update_memory(self, memory_id: str, new_content: str) -> dict:
        """Re-embeds and replaces a memory record: read metadata first,
        delete the old Postgres row + Qdrant point, store fresh (new
        embedding, new point id). Correct order matters — metadata is
        read before anything is deleted."""
        # Note: importance is stored only in the Qdrant payload (not a
        # Postgres column — see migrations/001_init.sql), so it can't be
        # recovered here; it resets to the default on update. Acceptable
        # tradeoff, documented rather than silently wrong.
        row = await self.db.fetchrow(
            "SELECT agent_id, session_id, task_id, source, type, retention_policy "
            "FROM memory_records WHERE memory_id = $1", memory_id
        )
        if row is None:
            raise LookupError(f"memory {memory_id} not found")

        await self.delete_memory(memory_id)

        return await self.store_memory(
            agent_id=row["agent_id"], session_id=row["session_id"], task_id=row["task_id"],
            source=row["source"], type_=row["type"], content=new_content,
            retention_policy=row["retention_policy"],
        )

    async def sweep_expired(self) -> int:
        """Real deletion pass honoring RETENTION_POLICIES. Returns count
        deleted. Call from a cron job — nothing calls this automatically."""
        deleted = 0
        for policy, days in RETENTION_POLICIES.items():
            if days is None:
                continue
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows = await self.db.fetch(
                "SELECT memory_id FROM memory_records WHERE retention_policy = $1 AND created_at < $2",
                policy, cutoff,
            )
            for row in rows:
                await self.delete_memory(row["memory_id"])
                deleted += 1
        return deleted
