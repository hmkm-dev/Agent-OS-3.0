"""
Model router — real implementation calling OpenRouter's actual API.
Provider-independent by design: swap MODEL_MAP or add a new provider
function without touching callers (workers call POST /internal/route
on Hermes, never OpenRouter directly).
"""

from __future__ import annotations

import os

import httpx

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Task type -> model. Edit freely; nothing else needs to change.
# Pick real, currently-available OpenRouter model slugs for your account.
MODEL_MAP = {
    "reasoning": os.environ.get("MODEL_REASONING", "anthropic/claude-sonnet-4.5"),
    "coding": os.environ.get("MODEL_CODING", "anthropic/claude-sonnet-4.5"),
    "creative": os.environ.get("MODEL_CREATIVE", "anthropic/claude-sonnet-4.5"),
    "fast": os.environ.get("MODEL_FAST", "google/gemini-2.0-flash-001"),
}

FALLBACK_MODEL = os.environ.get("MODEL_FALLBACK", "google/gemini-2.0-flash-001")


class ModelRouterError(Exception):
    pass


async def route(task_type: str, prompt: str, max_tokens: int = 2000) -> dict:
    if not OPENROUTER_API_KEY:
        raise ModelRouterError(
            "OPENROUTER_API_KEY is not set. Model routing cannot execute a real "
            "completion without it — set it in .env rather than faking a response."
        )

    model = MODEL_MAP.get(task_type, MODEL_MAP["reasoning"])

    async with httpx.AsyncClient(timeout=90) as client:
        try:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Fall back once to a different model before giving up.
            if model != FALLBACK_MODEL:
                return await route.__wrapped__(task_type="fast", prompt=prompt, max_tokens=max_tokens) \
                    if hasattr(route, "__wrapped__") else await _retry_with_fallback(client, prompt, max_tokens)
            raise ModelRouterError(f"OpenRouter request failed: {e.response.status_code} {e.response.text}") from e

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return {"text": text, "model": model, "raw_usage": data.get("usage", {})}


async def _retry_with_fallback(client: httpx.AsyncClient, prompt: str, max_tokens: int) -> dict:
    resp = await client.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": FALLBACK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return {"text": data["choices"][0]["message"]["content"], "model": FALLBACK_MODEL,
            "raw_usage": data.get("usage", {}), "used_fallback": True}
