"""
Research worker — real queue plumbing via BaseWorker. Calls the MCP
gateway for search + page retrieval, then synthesizes a report via
the model router. Preserves source metadata on every result and never
fabricates a citation: if the MCP search adapter isn't configured
(no SEARCH_PROVIDER/API key set), this raises a clear error instead
of inventing sources.
"""

import os

import httpx
from base_worker import BaseWorker

MCP_URL = os.environ.get("MCP_URL", "http://mcp:8100")
MODEL_ROUTER_URL = os.environ.get("MODEL_ROUTER_URL", "http://hermes:8000/internal/route")


class ResearchWorker(BaseWorker):
    worker_type = "research"
    queue_name = "queue:research"

    def handle(self, task: dict) -> dict:
        payload = task["payload"]
        query = payload.get("query")
        if not query:
            raise ValueError("payload.query is required")

        sources = self._search(query)
        if not sources:
            return {"summary": "no sources found", "sources": []}

        pages = [self._fetch_page(s["url"]) for s in sources[:5]]
        synthesis = self._synthesize(query, sources, pages)

        return {
            "query": query,
            "summary": synthesis,
            "sources": [{"url": s["url"], "title": s.get("title")} for s in sources[:5]],
        }

    def _search(self, query: str) -> list[dict]:
        resp = httpx.post(
            f"{MCP_URL}/call",
            json={"worker_type": "research", "tool": "search", "action": "query", "args": {"q": query}},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _fetch_page(self, url: str) -> dict:
        resp = httpx.post(
            f"{MCP_URL}/call",
            json={"worker_type": "research", "tool": "playwright", "action": "get_text", "args": {"url": url}},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _synthesize(self, query: str, sources: list[dict], pages: list[dict]) -> str:
        # Calls Hermes's internal model-routing endpoint rather than
        # hard-coding a provider here — see services/hermes/model_router.py.
        context = "\n\n".join(p.get("text", "")[:2000] for p in pages)
        resp = httpx.post(
            MODEL_ROUTER_URL,
            json={
                "task_type": "reasoning",
                "prompt": (
                    f"Synthesize a concise, sourced answer to: {query}\n\n"
                    f"Source material:\n{context}\n\n"
                    "Only state claims supported by the source material above."
                ),
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("text", "")


if __name__ == "__main__":
    ResearchWorker().run()
