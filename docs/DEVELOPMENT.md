# Development

## Running tests
```bash
pip install -r services/hermes/requirements.txt pytest pytest-asyncio --break-system-packages
pytest tests/unit -v
```
Integration/E2E flow is currently manual (no live infra in CI):
```bash
# 1. bring up the core stack (see docs/DEPLOYMENT.md)
# 2. create a task
curl -X POST http://localhost:8000/tasks \
  -H "x-api-key: $HERMES_API_KEY" -H "Content-Type: application/json" \
  -d '{"type":"research","payload":{"query":"test query"}}'
# 3. poll status
curl http://localhost:8000/tasks/<task_id> -H "x-api-key: $HERMES_API_KEY"
# 4. trigger evaluation once completed
curl -X POST http://localhost:8000/tasks/<task_id>/evaluate -H "x-api-key: $HERMES_API_KEY"
```

## Adding a new skill
1. `POST` a demonstration transcript through `TeachToSkill.capture_and_extract()`
   (no HTTP route yet — call it directly in a Python shell against the
   running Hermes container, or add a route if you want this over HTTP).
2. Review the generated draft, add test cases.
3. `SkillEngine.mark_tested()` once you're satisfied.
4. A human calls `SkillEngine.approve()` — never automate this call.

## Adding a new MCP tool
1. Write the adapter in `services/mcp/tools/<tool>.py`, matching the
   pattern in `search.py`/`github.py` (raise clearly if unconfigured,
   never fabricate results).
2. Add the tool to `ALLOWLIST` in `services/mcp/gateway.py` for the
   worker types that should have access.
3. Add a case to `call_tool()`'s dispatch.

## Adding a new model provider
Edit `services/hermes/model_router.py` — swap the OpenRouter call for
your provider's API, or add a second provider function and pick
between them in `route()`. Callers (workers, evaluator) never change,
they only call `POST /internal/route` on Hermes.

## Remember
After editing any shared module (`agents/workspace.py`,
`services/workers/common/base_worker.py`, policy/approval/evaluator
under `services/hermes/`'s copies), run:
```bash
bash scripts/sync_shared.sh
```
before rebuilding, since each service has an isolated Docker build
context.
