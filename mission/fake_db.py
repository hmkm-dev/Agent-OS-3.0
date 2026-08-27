"""Compatibility export for the existing mission unit-test fake database.

The helper remains owned by the test suite; this module keeps legacy imports
working without changing its behavior or creating a second implementation.
"""
from tests.unit.mission.fake_db import FakeDB

__all__ = ["FakeDB"]
