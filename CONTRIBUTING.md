# Contributing

This started as a personal/solo-operator project (see README), so this
file is intentionally light — expand it if the project grows
contributors.

## Making a change
1. Branch off `main`.
2. If you touch `agents/workspace.py`, `services/workers/common/base_worker.py`,
   or the policy/approval/evaluator/memory/handoff modules under
   `services/hermes/`, edit the **canonical source** (see README's repo
   structure section for which copy is canonical), then run
   `bash scripts/sync_shared.sh` before building.
3. Run `python3 -m pytest tests/unit -v` — all tests must pass.
4. Update the relevant doc in `docs/` if behavior changed. Documentation
   must match actual implementation — don't describe a stub as complete.
5. Open a PR. CI (`.github/workflows/ci.yml`) runs lint + unit tests +
   Docker build validation automatically.

## Code style
No enforced formatter yet. Keep it consistent with surrounding code.
Flake8 in CI only checks for actual errors (undefined names, syntax
errors), not style — style nits aren't a merge blocker.

## Reporting issues
Use GitHub Issues. For security issues, see `SECURITY.md` — do not open
a public issue for a vulnerability.
