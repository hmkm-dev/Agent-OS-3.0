# Skill: Instagram

**Status: NOT IMPLEMENTED — explicit external integration point.** Same honesty rule as Pinterest — no Instagram API calls exist in this repo.

## Purpose (once connected)
Automated post/story creation for an Instagram business account.

## External prerequisites (you must obtain these)
1. An Instagram Business or Creator account, linked to a Facebook Page
2. A Meta Developer app: https://developers.facebook.com/apps/
3. Instagram Graph API access — requires Meta App Review for most publishing permissions (`instagram_content_publish`) in production, a manual approval process outside this repo's control
4. A long-lived access token via the OAuth flow

## What would need to be built (not built yet)
- `services/mcp/tools/instagram.py` — real Graph API calls (`POST /{ig-user-id}/media` then `POST /{ig-user-id}/media_publish`), same pattern as `github.py`: raises clearly if `INSTAGRAM_ACCESS_TOKEN` is unset, never fakes a successful post
- MCP gateway allowlist registration
- `SOCIAL_POST` policy class (already present) gating every real publish call

## Current safe behavior
Same as Pinterest: escalate, never fake success.
