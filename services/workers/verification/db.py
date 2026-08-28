"""
Thin async Postgres wrapper around asyncpg. Real implementation —
connects to the real DATABASE_URL, no mocking. If Postgres isn't up
yet (e.g. you're still on Phase 1-4 of the README and haven't
uncommented the postgres service), calls will raise a clear
ConnectionError rather than silently no-op'ing.
"""

from __future__ import annotations

import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:{}@postgres:5432/agentos".format(
        os.environ.get("DATABASE_PASSWORD", "")
    ),
)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        except (OSError, asyncpg.PostgresError) as e:
            raise ConnectionError(
                f"could not connect to Postgres at {DATABASE_URL.split('@')[-1]}: {e}. "
                "If you haven't reached Phase 6 of the README yet, this is expected — "
                "Hermes falls back to Redis-only task state until Postgres is deployed."
            ) from e
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


class DB:
    async def execute(self, query: str, *args):
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetchrow(self, query: str, *args):
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetch(self, query: str, *args):
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)
