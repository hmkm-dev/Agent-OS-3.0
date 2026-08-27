"""
Thin Qdrant REST client (Qdrant Cloud, per architecture decision to
not self-host — see docs/ARCHITECTURE.md). Real HTTP calls via httpx
against Qdrant's REST API, no client SDK dependency needed for the
handful of operations this pipeline uses.
"""

from __future__ import annotations

import os
import uuid

import httpx

QDRANT_URL = os.environ.get("QDRANT_URL")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "agent_memory")


class QdrantNotConfigured(Exception):
    pass


def _require_config():
    if not (QDRANT_URL and QDRANT_API_KEY):
        raise QdrantNotConfigured(
            "QDRANT_URL / QDRANT_API_KEY not set — semantic memory is unavailable "
            "until you sign up for Qdrant Cloud's free tier and configure these."
        )


async def ensure_collection(vector_size: int):
    _require_config()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            headers={"api-key": QDRANT_API_KEY},
        )
        if resp.status_code == 200:
            return
        create = await client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            headers={"api-key": QDRANT_API_KEY},
            json={"vectors": {"size": vector_size, "distance": "Cosine"}},
        )
        create.raise_for_status()


async def upsert_point(vector: list[float], payload: dict, point_id: str | None = None) -> str:
    _require_config()
    point_id = point_id or str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            headers={"api-key": QDRANT_API_KEY},
            json={"points": [{"id": point_id, "vector": vector, "payload": payload}]},
        )
        resp.raise_for_status()
    return point_id


async def search(vector: list[float], top_k: int = 5, filter_: dict | None = None) -> list[dict]:
    _require_config()
    body = {"vector": vector, "limit": top_k, "with_payload": True}
    if filter_:
        body["filter"] = filter_
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            headers={"api-key": QDRANT_API_KEY},
            json=body,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])


async def delete_point(point_id: str) -> None:
    _require_config()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
            headers={"api-key": QDRANT_API_KEY},
            json={"points": [point_id]},
        )
        resp.raise_for_status()
