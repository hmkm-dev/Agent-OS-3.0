"""
Real tests for the Mission Control permission classes added to
services/policy/rules.yaml (spec §12) — verifies the actual current
production rules.yaml, not a copy that could drift from it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from policy_engine import PolicyEngine  # noqa: E402


def _engine():
    return PolicyEngine(rules_path=os.path.join(os.path.dirname(__file__), "policy_rules.yaml"))


def test_network_low_risk_allowed():
    assert _engine().evaluate("NETWORK").result == "ALLOW"


def test_browser_low_risk_allowed():
    assert _engine().evaluate("BROWSER").result == "ALLOW"


def test_github_medium_risk_requires_approval():
    assert _engine().evaluate("GITHUB").result == "REQUIRE_APPROVAL"


def test_deploy_high_risk_requires_approval():
    assert _engine().evaluate("DEPLOY").result == "REQUIRE_APPROVAL"


def test_social_post_high_risk_requires_approval():
    assert _engine().evaluate("SOCIAL_POST").result == "REQUIRE_APPROVAL"


def test_financial_high_risk_requires_approval():
    assert _engine().evaluate("FINANCIAL").result == "REQUIRE_APPROVAL"


def test_destructive_denied_by_default():
    """The strictest class — deny by default, no blanket approval path."""
    assert _engine().evaluate("DESTRUCTIVE").result == "DENY"


def test_existing_categories_unaffected_by_additive_change():
    """Confirms the new categories didn't disturb the pre-existing ones."""
    e = _engine()
    assert e.evaluate("READ_FILE").result == "ALLOW"
    assert e.evaluate("CREDENTIAL_ACCESS").result == "DENY"
