from pathlib import Path


def _repo_root() -> Path:
    """Find the checkout regardless of whether this test is root-level or nested."""
    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "docker-compose.yml").is_file():
            return candidate
    raise RuntimeError("could not locate repository root")


def test_agent_os30_compose_profile_declares_all_dedicated_workers():
    compose = _repo_root() / "docker-compose.yml"
    s = compose.read_text(encoding="utf-8")
    for name in ("rlm-worker", "browser-worker", "verification-worker", "seo-worker", "marketing-worker", "devops-worker"):
        assert name in s
    assert 'profiles: ["agent_os30"]' in s
