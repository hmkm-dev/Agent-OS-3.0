"""Compatibility import package for the legacy skill-engine test suite.

Canonical skill-engine modules remain under ``services/skill_engine``.
"""
from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[1] / "services" / "skill_engine"))
