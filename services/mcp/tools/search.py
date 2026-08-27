"""
Search provider abstraction. Real implementation for one provider
(Brave Search API — has a free tier, good fit for this project's
cost constraints) plus a clean interface for adding more. Research
worker never talks to a search API directly, only to this module via
the MCP gateway, per spec §21.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx


class SearchProvider(ABC):
    @abstractmethod
    async def query(self, q: str, count: int = 5) -> list[dict]:
        """Return a list of {"url": ..., "title": ..., "snippet": ...}."""
        raise NotImplementedError


class BraveSearchProvider(SearchProvider):
    def __init__(self):
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY")

    async def query(self, q: str, count: int = 5) -> list[dict]:
        if not self.api_key:
            raise RuntimeError(
                "BRAVE_SEARCH_API_KEY not set — search is unavailable until "
                "configured. No results are fabricated."
            )
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                params={"q": q, "count": count},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", [])[:count]:
                results.append({
                    "url": item.get("url"),
                    "title": item.get("title"),
                    "snippet": item.get("description"),
                })
            return results


class UnconfiguredSearchProvider(SearchProvider):
    """Used when no provider is configured. Fails loudly and clearly
    instead of returning empty/fake results that could be mistaken
    for 'no results found'."""

    async def query(self, q: str, count: int = 5) -> list[dict]:
        raise RuntimeError(
            "No SEARCH_PROVIDER configured. Set SEARCH_PROVIDER=brave and "
            "BRAVE_SEARCH_API_KEY in .env, or implement another SearchProvider "
            "subclass and register it in get_provider()."
        )


def get_provider() -> SearchProvider:
    provider = os.environ.get("SEARCH_PROVIDER", "").lower()
    if provider == "brave":
        return BraveSearchProvider()
    return UnconfiguredSearchProvider()
