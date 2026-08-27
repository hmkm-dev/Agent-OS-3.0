from pathlib import Path


def _repo_root() -> Path:
    # Resolve from this test file so pytest works from the repository root,
    # its parent directory, or an IDE/CI working directory.
    return Path(__file__).resolve().parents[3]


def test_agent_os30_compose_profile_declares_all_dedicated_workers():
    compose = _repo_root() / "docker-compose.yml"
    s = compose.read_text(encoding="utf-8")
    for name in ("rlm-worker", "browser-worker", "verification-worker", "seo-worker", "marketing-worker", "devops-worker"):
        assert name in s
    assert 'profiles: ["agent_os30"]' in s
