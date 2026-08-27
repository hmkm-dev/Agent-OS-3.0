from services.mcp.gateway import ALLOWLIST, ToolCall


def test_browser_worker_can_request_playwright():
    request = ToolCall(
        worker_type="browser",
        tool="playwright",
        action="get_text",
        args={"url": "https://example.com"},
    )
    assert request.worker_type == "browser"
    assert request.tool in ALLOWLIST[request.worker_type]


def test_profile_worker_types_are_validated_before_allowlist_decision():
    for worker_type in ("seo", "marketing", "devops", "verification", "rlm"):
        request = ToolCall(
            worker_type=worker_type,
            tool="search",
            action="query",
            args={"q": "test"},
        )
        assert request.worker_type == worker_type


def test_devops_and_verification_have_no_implicit_tool_access():
    assert ALLOWLIST.get("devops", set()) == set()
    assert ALLOWLIST.get("verification", set()) == set()
    assert ALLOWLIST.get("rlm", set()) == set()
