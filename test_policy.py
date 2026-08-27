"""Real unit tests against the actual PolicyEngine — no mocking of the
decision logic itself."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from engine import PolicyEngine  # noqa: E402


def _engine():
    return PolicyEngine(rules_path=os.path.join(os.path.dirname(__file__), "rules.yaml"))


def test_read_file_allowed():
    d = _engine().evaluate("READ_FILE")
    assert d.result == "ALLOW"


def test_credential_access_denied():
    d = _engine().evaluate("CREDENTIAL_ACCESS")
    assert d.result == "DENY"


def test_execute_command_with_destructive_keyword_denied():
    d = _engine().evaluate("EXECUTE_COMMAND", context={"payload": "rm -rf /"})
    assert d.result == "DENY"


def test_execute_command_without_keyword_requires_approval():
    d = _engine().evaluate("EXECUTE_COMMAND", context={"payload": "ls -la"})
    assert d.result == "REQUIRE_APPROVAL"


def test_unknown_action_denied():
    d = _engine().evaluate("NOT_A_REAL_ACTION")
    assert d.result == "DENY"


def test_write_file_escalates_on_sensitive_path():
    d = _engine().evaluate("WRITE_FILE", context={"payload": "writing to ~/.ssh/id_rsa"})
    assert d.result == "REQUIRE_APPROVAL"
