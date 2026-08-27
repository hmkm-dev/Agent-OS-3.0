# Skill: Pinterest

**Status: NOT IMPLEMENTED — explicit external integration point.** No Pinterest API calls exist anywhere in this repo. Per the "do not invent integrations" rule, this file documents exactly what's needed rather than pretending a connection exists.

## Purpose (once connected)
Automated pin creation/scheduling for LuxeNest Decor's Pinterest presence.

## External prerequisites (you must obtain these — nothing here can substitute)
1. A Pinterest Business account
2. A registered Pinterest Developer app: https://developers.pinterest.com/apps/
3. **App approval** — Pinterest requires manual review before granting write scopes (`pins:write`, `boards:write`) in production; this can take days and is entirely outside this repo's control
4. OAuth 2.0 credentials (`client_id`, `client_secret`) and a completed OAuth flow producing a refresh token

## What would need to be built (not built yet)
- A new MCP tool `services/mcp/tools/pinterest.py`, following the exact real-adapter pattern in `services/mcp/tools/github.py`: real REST calls to `https://api.pinterest.com/v5/pins`, raising clearly if `PINTEREST_ACCESS_TOKEN` (a new `.env` variable, not yet added) is unset — never fabricating a "pin created" response
- Registration in `services/mcp/gateway.py`'s `ALLOWLIST` for whichever worker should get pin-creation access (likely `creative`)
- A `SOCIAL_POST`-classed policy check (already added to `services/policy/rules.yaml` this pass — `REQUIRE_APPROVAL`) in front of any real pin-creation call

## Current safe behavior
Any mission task that requires this skill should be classified `missing_information` or `tool_failure` by `services/mission/failure_recovery.py` and escalate to human review, NOT be silently skipped or falsely marked complete.
