# Skill: Marketing

**Status: PARTIALLY IMPLEMENTED** — content generation/planning via the existing creative worker's model-router path is real. No dedicated marketing-automation platform integration (e.g. no Mailchimp/HubSpot connector) exists — explicit integration point.

## Purpose
Marketing copy generation, campaign content planning, using the existing creative worker.

## Inputs
- `content_type`, `brief` (matches `services/workers/creative/worker.py`'s existing payload shape — this skill doesn't need a new worker)

## Outputs
- Generated text, optionally uploaded to R2 (`r2_key`) via the creative worker's existing R2 integration

## Allowed tools
`search` (per `ALLOWLIST["creative"]`)

## What's an integration point (not built, not faked)
- Email platform APIs (Mailchimp, ConvertKit, etc.) — none connected. Requires an API key from the specific platform; add as a new MCP tool when a real account exists.
- Analytics/attribution platforms — same, not connected.

## Success criteria / verification
Content generation itself is verifiable (the text exists, matches the brief structurally). Marketing *performance* claims (open rates, conversions) would require the platform integrations above — until those exist, this skill cannot verify campaign performance, only content production.

## Failure handling
Standard classification via `failure_recovery.py`.
