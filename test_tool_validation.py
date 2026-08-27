"""
Real tests for validate_required_tools()'s status classification logic
(ok/not_allowed/not_configured/error/unreachable), using a fake
httpx transport rather than a live MCP gateway — but exercising the
REAL status-mapping code, not a mocked-out version of it.
"""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from skill_engine.tool_validation import all_tools_ok, validate_required_tools  # noqa: E402

# Capture the REAL AsyncClient class before any monkeypatching happens.
# Bug this fixes: the previous version of this file called
# `httpx.AsyncClient(...)` from inside the factory function that
# `monkeypatch.setattr(httpx, "AsyncClient", factory)` installs — but
# by the time the factory runs, `httpx.AsyncClient` no longer refers to
# the real class, it refers to `factory` itself (monkeypatch replaced
# the module attribute). So `factory()` called `factory()` called
# `factory()`... -> RecursionError. Binding `_RealAsyncClient` here,
# at import time, before any test's monkeypatch runs, breaks that cycle.
_RealAsyncClient = httpx.AsyncClient


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_client_with_transport(handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)
    return factory


def test_gateway_unreachable_marks_all_tools_unreachable(monkeypatch):
    async def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _make_client_with_transport(handler))
    report = run(validate_required_tools("research", ["search"]))
    assert report["gateway_reachable"] is False
    assert report["tools"]["search"]["status"] == "unreachable"
    assert all_tools_ok(report) is False


def test_tool_ok_when_probe_succeeds(monkeypatch):
    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", _make_client_with_transport(handler))
    report = run(validate_required_tools("research", ["search"]))
    assert report["gateway_reachable"] is True
    assert report["tools"]["search"]["status"] == "ok"
    assert all_tools_ok(report) is True


def test_tool_not_allowed_on_403(monkeypatch):
    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(403, json={"detail": "not allowed"})

    monkeypatch.setattr(httpx, "AsyncClient", _make_client_with_transport(handler))
    report = run(validate_required_tools("creative", ["github"]))
    assert report["tools"]["github"]["status"] == "not_allowed"
    assert all_tools_ok(report) is False


def test_tool_not_configured_on_503(monkeypatch):
    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(503, json={"detail": "BRAVE_SEARCH_API_KEY not set"})

    monkeypatch.setattr(httpx, "AsyncClient", _make_client_with_transport(handler))
    report = run(validate_required_tools("research", ["search"]))
    assert report["tools"]["search"]["status"] == "not_configured"
    assert all_tools_ok(report) is False


def test_unknown_tool_reported_not_silently_ok(monkeypatch):
    async def handler(request):
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(httpx, "AsyncClient", _make_client_with_transport(handler))
    report = run(validate_required_tools("research", ["some_nonexistent_tool"]))
    assert report["tools"]["some_nonexistent_tool"]["status"] == "unknown_tool"
    assert all_tools_ok(report) is False
