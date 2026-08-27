"""Provide a fresh event loop per test for Python 3.13 compatibility."""
import asyncio
import pytest

@pytest.fixture(autouse=True)
def ensure_event_loop():
    loop=asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())
