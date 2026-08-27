# GitHub Release Gate

This repository treats "unit tests pass" and "production works" as different claims.

## Automated gates

Every push/PR to `main` runs:

1. secret scan
2. shared-code synchronization check
3. Python unit tests
4. E2E test discovery (credential-gated tests skip without live credentials)
5. Compose configuration validation
6. Docker build matrix for all first-party images
7. a real Docker/Compose core-stack smoke test

The smoke test is `scripts/ci_smoke.sh`. It creates a temporary synthetic `.env`,
builds the production Compose services, starts the core stack, waits for
health/readiness, checks MCP and Playwright health endpoints, verifies the
OpenCode binary, verifies that the non-root worker can write `/workspace`, and
checks that the worker processes remain running.

It intentionally does not require or expose production credentials.

## External acceptance tests

Run against a real deployment:

```bash
HERMES_URL=https://api.example.com HERMES_API_KEY='...' python -m pytest tests/e2e/test_openrouter.py tests/e2e/test_opencode_execution.py -v -s
```

For memory, R2, Playwright, n8n, and handoff tests, provide the credentials
documented in each E2E module.

## Release rule

A release is considered repository/runtime ready only when:

- all CI jobs are green;
- Docker images build successfully;
- the core-stack smoke test passes;
- external E2E tests are run separately against a real deployment;
- no secrets are committed.

A skipped external test is never treated as a successful external integration.
