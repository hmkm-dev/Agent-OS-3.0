"""Compatibility export for mixed historical/service-scoped test imports.

The test helper remains canonical in tests.unit.mission.fake_db; this module
only makes `mission.fake_db` resolve when services/ is first on sys.path.
"""
from tests.unit.mission.fake_db import FakeDB

__all__ = ["FakeDB"]
