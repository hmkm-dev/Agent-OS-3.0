# Skill: SEO

**Status: PARTIALLY IMPLEMENTED** — the underlying tools (search, browser reading, content generation via OpenCode/model router) are real and working. There is no dedicated SEO-specific tool/API integration in this repo (e.g. no Ahrefs/SEMrush connector) — that is an explicit external integration point, not built.

## Purpose
Keyword research (via search), on-page content analysis (via Playwright page reads), content generation/editing (via OpenCode/model router) for SEO purposes.

## Inputs
- `target_keywords` or `topic`
- `target_url` (for on-page analysis of existing content)

## Outputs
- Research summary with sources (reuses the research skill)
- Generated/edited content (reuses the coding or creative skill's model-router path)

## Allowed tools
`search`, `playwright` — same as research skill; no SEO-specific MCP tool exists

## What's an integration point (not built, not faked)
- Rank tracking APIs (Ahrefs, SEMrush, Google Search Console API) — none connected. If needed, add as a new MCP tool following the pattern in `services/mcp/tools/search.py` (real adapter, raises clearly if unconfigured) and add to the relevant worker's `ALLOWLIST` entry in `services/mcp/gateway.py`.
- Google Search Console requires OAuth app verification — external prerequisite, not something this repo can pre-configure for you.

## Success criteria / verification
Same evidence-based pattern as research: claims about keyword volume/rankings must be `source_reference`-backed with a real fetched URL, never asserted from model prior knowledge alone.

## Failure handling
Standard `services/mission/failure_recovery.py` classification applies; no SEO-specific failure modes defined yet.
