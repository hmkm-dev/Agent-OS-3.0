"""Compatibility import package for the legacy mission test suite.

The canonical implementation remains in ``services/mission``. This package
only provides the historical top-level import name used by existing tests and
isolated service contexts.
"""
from pathlib import Path

# Keep submodule resolution on the canonical source tree; no implementation is
# copied or replaced here.
__path__.append(str(Path(__file__).resolve().parents[1] / "services" / "mission"))
