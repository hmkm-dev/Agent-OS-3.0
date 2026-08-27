import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.fake_db import FakeDB  # noqa: E402
from mission.verifiers import (  # noqa: E402
    DatabaseVerifier, FileVerifier, TestVerifier, VerifierUnavailable,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── FileVerifier — real filesystem checks, no mocking ──────────────

def test_file_verifier_passes_for_real_existing_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        path = f.name
    try:
        result = run(FileVerifier().verify("claimed it exists", {"path": path}))
        assert result.passed is True
        assert result.evidence_hash is not None
    finally:
        os.remove(path)


def test_file_verifier_fails_for_nonexistent_file():
    result = run(FileVerifier().verify("claimed it exists", {"path": "/tmp/definitely-does-not-exist-xyz123.txt"}))
    assert result.passed is False


def test_file_verifier_checks_expected_content():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("def add(a, b): return a + b")
        path = f.name
    try:
        passing = run(FileVerifier().verify("claim", {"path": path, "expected_substring": "def add"}))
        assert passing.passed is True

        failing = run(FileVerifier().verify("claim", {"path": path, "expected_substring": "def subtract"}))
        assert failing.passed is False
    finally:
        os.remove(path)


def test_file_verifier_requires_path_context():
    try:
        run(FileVerifier().verify("claim", {}))
        assert False, "expected VerifierUnavailable"
    except VerifierUnavailable:
        pass


# ── TestVerifier — real structured data checks ──────────────────────

def test_test_verifier_passes_on_zero_exit_code():
    result = run(TestVerifier().verify("tests passed", {"exit_code": 0}))
    assert result.passed is True


def test_test_verifier_fails_on_nonzero_exit_code():
    result = run(TestVerifier().verify("tests passed", {"exit_code": 1}))
    assert result.passed is False


def test_test_verifier_fails_if_any_tests_failed_even_with_zero_exit():
    """Real property: exit_code alone isn't sufficient if explicit
    pass/fail counts are provided and show failures."""
    result = run(TestVerifier().verify("tests passed", {"exit_code": 0, "tests_passed": 5, "tests_failed": 2}))
    assert result.passed is False


def test_test_verifier_requires_exit_code():
    try:
        run(TestVerifier().verify("tests passed", {}))
        assert False, "expected VerifierUnavailable"
    except VerifierUnavailable:
        pass


# ── DatabaseVerifier — real parameterized query execution against FakeDB ──

def test_database_verifier_confirms_row_exists():
    db = FakeDB()
    db.missions["m1"] = {"mission_id": "m1", "status": "EXECUTING"}
    # FakeDB doesn't implement arbitrary SELECT parsing, so this test
    # uses a minimal custom fetchrow monkeypatch to prove the real
    # query-execution path works, not FakeDB's generic dispatch.
    class MiniDB:
        async def fetchrow(self, query, *params):
            assert query.strip().upper().startswith("SELECT")
            return {"mission_id": "m1"} if params[0] == "m1" else None

    verifier = DatabaseVerifier(MiniDB())
    result = run(verifier.verify("claim", {"query": "SELECT * FROM missions WHERE mission_id = $1", "params": ["m1"]}))
    assert result.passed is True


def test_database_verifier_fails_when_no_row_found():
    class MiniDB:
        async def fetchrow(self, query, *params):
            return None

    verifier = DatabaseVerifier(MiniDB())
    result = run(verifier.verify("claim", {"query": "SELECT * FROM missions WHERE mission_id = $1", "params": ["nonexistent"]}))
    assert result.passed is False


def test_database_verifier_rejects_non_select_queries():
    """Real safety property: never accept a mutating query, even one
    that would happen to 'pass' if it ran."""
    class MiniDB:
        async def fetchrow(self, query, *params):
            return {"ok": True}

    verifier = DatabaseVerifier(MiniDB())
    try:
        run(verifier.verify("claim", {"query": "DELETE FROM missions WHERE mission_id = $1", "params": ["m1"]}))
        assert False, "expected VerifierUnavailable for a non-SELECT query"
    except VerifierUnavailable:
        pass
