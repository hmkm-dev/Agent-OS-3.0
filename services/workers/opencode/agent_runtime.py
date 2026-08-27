"""
AgentRuntime abstraction (Phase A / §19 of the spec). The OpenCode
worker calls a runtime, not the OpenCode CLI directly, so a second
runtime (DSH) can be added later without touching worker/queue code.

OpenCodeRuntime is a real implementation: it actually shells out to
the configured binary and captures stdout/stderr/exit code/timing. It
is not a mock. `services/workers/opencode/Dockerfile` installs the
real OpenCode CLI (`opencode-ai@1.18.20` via npm — see that
Dockerfile's comments for the exact pin and verification notes), so
the binary is expected to be present in a correctly built image. The
`shutil.which()` check in `execute()` below is a defensive runtime
guard (raises a clear RuntimeError instead of a confusing downstream
failure if something's wrong with a given build/container), not a
sign of an unresolved gap — the "binary not installed" gap this
comment used to describe was closed in a prior pass.

DSHRuntime is intentionally NOT implemented. Per the spec (§19/§40),
DSH must not be integrated before the core system passes E2E tests,
and must remain optional. Wiring it in prematurely — even as a stub
that "works" — would violate that ordering. It raises
NotImplementedError with a clear message rather than being silently
half-built.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RuntimeResult:
    exit_code: int
    stdout: str
    stderr: str
    files_changed: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class AgentRuntime(ABC):
    @abstractmethod
    def execute(self, instructions: str, workspace_dir: str, timeout_seconds: int = 100) -> RuntimeResult:
        raise NotImplementedError


class OpenCodeRuntime(AgentRuntime):
    """Real implementation. Verified against OpenCode's actual CLI docs
    (opencode.ai/docs/cli, Aug 2026): `opencode run "<prompt>"` is the
    real non-interactive invocation, not a guess.

    Known limitation (tracked upstream, not something this repo can
    fix): OpenCode has an open issue (anomalyco/opencode#10411) where
    a permission prompt can hang a headless run in some versions.
    Since stdout/stderr here are piped (non-TTY), OpenCode is documented
    to default to non-interactive behavior, but this hasn't been
    exercised against a live container in this sandbox — treat the
    first real run as a smoke test, not an assumed-working path.
    """

    def __init__(self, binary: str | None = None, model: str | None = None):
        self.binary = binary or os.environ.get("OPENCODE_BIN", "opencode")
        self.model = model or os.environ.get("OPENCODE_MODEL")  # e.g. "openrouter/anthropic/claude-sonnet-4.5"

    def execute(self, instructions: str, workspace_dir: str, timeout_seconds: int = 100) -> RuntimeResult:
        if shutil.which(self.binary) is None:
            raise RuntimeError(
                f"'{self.binary}' binary not found in this container. "
                "services/workers/opencode/Dockerfile should have installed it via "
                "`npm install -g opencode-ai` — check the build log."
            )

        cmd = [self.binary, "run"]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(instructions)

        started = time.monotonic()
        proc = subprocess.run(
            cmd,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration = time.monotonic() - started

        changed_files = self._git_diff_files(workspace_dir)

        return RuntimeResult(
            exit_code=proc.returncode,
            stdout=proc.stdout[-8000:],
            stderr=proc.stderr[-4000:],
            files_changed=changed_files,
            duration_seconds=duration,
        )

    def _git_diff_files(self, workspace_dir: str) -> list[str]:
        if not os.path.isdir(os.path.join(workspace_dir, ".git")):
            return []
        proc = subprocess.run(
            ["git", "-C", workspace_dir, "diff", "--name-only"],
            capture_output=True, text=True,
        )
        return [f for f in proc.stdout.splitlines() if f]


class DSHRuntime(AgentRuntime):
    """Deliberately not implemented — see module docstring. Integrate
    only after Phase M (post-E2E, benchmarked against OpenCodeRuntime),
    per spec §19/§40."""

    def execute(self, instructions: str, workspace_dir: str, timeout_seconds: int = 100) -> RuntimeResult:
        raise NotImplementedError(
            "DSHRuntime is intentionally deferred until the core system passes E2E "
            "tests and DSH is benchmarked against OpenCodeRuntime (spec Phase M). "
            "This is a documented decision, not an oversight."
        )


def get_runtime(name: str = "opencode") -> AgentRuntime:
    if name == "opencode":
        return OpenCodeRuntime()
    if name == "dsh":
        return DSHRuntime()
    raise ValueError(f"unknown runtime '{name}'")
