"""
Isolated Playwright service — runs in its own container (see Dockerfile,
based on the official Microsoft Playwright image with browsers
preinstalled). Real browser automation via the actual playwright
Python package, not a mock.

Isolation rules enforced here (per spec §14 and §19):
  - each request gets a fresh browser context (no shared cookies
    between unrelated calls unless explicitly given a persistent
    profile_id)
  - hard timeout per navigation
  - no filesystem access outside /tmp/browser-artifacts
  - screenshots/logs captured on error for debugging
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel

ARTIFACT_DIR = "/tmp/browser-artifacts"
DEFAULT_TIMEOUT_MS = int(os.environ.get("PLAYWRIGHT_TIMEOUT_MS", "30000"))
os.makedirs(ARTIFACT_DIR, exist_ok=True)

app = FastAPI(title="Playwright Service")


class GetTextRequest(BaseModel):
    url: str
    profile_id: Optional[str] = None  # only set this for tasks that need a persistent logged-in session
    timeout_ms: Optional[int] = None


class NavigateRequest(BaseModel):
    url: str
    actions: list[dict] = []  # e.g. [{"type": "click", "selector": "#foo"}, {"type": "fill", "selector": "#bar", "value": "x"}]
    profile_id: Optional[str] = None
    timeout_ms: Optional[int] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/get_text")
async def get_text(req: GetTextRequest):
    timeout = req.timeout_ms or DEFAULT_TIMEOUT_MS
    try:
        async with asyncio.timeout(timeout / 1000 + 5):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await _make_context(browser, req.profile_id)
                page = await context.new_page()
                try:
                    await page.goto(req.url, timeout=timeout, wait_until="domcontentloaded")
                    text = await page.inner_text("body")
                    return {"url": req.url, "text": text[:20000]}
                except Exception as e:
                    screenshot_path = await _capture_error_artifact(page, e)
                    raise HTTPException(
                        status_code=502,
                        detail=f"navigation failed: {e}; screenshot: {screenshot_path}",
                    )
                finally:
                    await context.close()
                    await browser.close()
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"task exceeded {timeout}ms timeout")


@app.post("/navigate")
async def navigate(req: NavigateRequest):
    timeout = req.timeout_ms or DEFAULT_TIMEOUT_MS
    try:
        async with asyncio.timeout(timeout / 1000 + 10):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await _make_context(browser, req.profile_id)
                page = await context.new_page()
                log = []
                try:
                    await page.goto(req.url, timeout=timeout, wait_until="domcontentloaded")
                    log.append(f"navigated to {req.url}")

                    for action in req.actions:
                        await _run_action(page, action)
                        log.append(f"executed {action}")

                    screenshot_path = os.path.join(ARTIFACT_DIR, f"{uuid.uuid4().hex}.png")
                    await page.screenshot(path=screenshot_path)
                    return {"status": "completed", "log": log, "screenshot": screenshot_path}
                except Exception as e:
                    screenshot_path = await _capture_error_artifact(page, e)
                    raise HTTPException(
                        status_code=502,
                        detail=f"action sequence failed: {e}; log so far: {log}; screenshot: {screenshot_path}",
                    )
                finally:
                    await context.close()
                    await browser.close()
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"task exceeded {timeout}ms timeout")


async def _make_context(browser, profile_id: Optional[str]):
    """Fresh, isolated context by default. Only reuses a persistent
    storage_state if profile_id is explicitly given AND a saved state
    file exists for it — this is the one sanctioned way to keep a
    logged-in session (e.g. Pinterest) across calls, and it must be
    set up out-of-band by a human login + state export, not by an
    agent creating its own persistent credentials."""
    if profile_id:
        state_path = f"/tmp/browser-artifacts/profile-{profile_id}.json"
        if os.path.exists(state_path):
            return await browser.new_context(storage_state=state_path)
    return await browser.new_context()


async def _run_action(page, action: dict):
    action_type = action.get("type")
    selector = action.get("selector")
    if action_type == "click":
        await page.click(selector, timeout=DEFAULT_TIMEOUT_MS)
    elif action_type == "fill":
        await page.fill(selector, action.get("value", ""), timeout=DEFAULT_TIMEOUT_MS)
    elif action_type == "wait_for_selector":
        await page.wait_for_selector(selector, timeout=DEFAULT_TIMEOUT_MS)
    else:
        raise ValueError(f"unsupported action type: {action_type}")


async def _capture_error_artifact(page, error: Exception) -> str:
    path = os.path.join(ARTIFACT_DIR, f"error-{uuid.uuid4().hex}.png")
    try:
        await page.screenshot(path=path)
    except Exception:
        path = "screenshot capture also failed"
    return path
