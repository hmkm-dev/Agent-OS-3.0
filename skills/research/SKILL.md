# Skill: Research

**Status: IMPLEMENTED** — runs via the existing Research worker + MCP search/Playwright tools. Requires `SEARCH_PROVIDER=brave` + `BRAVE_SEARCH_API_KEY` configured (documented external prerequisite — a real Brave Search API account, free tier available).

## Purpose
Web search, page retrieval, source-gathering, and synthesis with preserved citations.

## Inputs
- `query`: what to research

## Outputs
- `summary`, `sources` (list of `{url, title}`)

## Allowed tools
`search`, `playwright`

## Workflow
1. MCP `search` tool call (real Brave Search API call)
2. Top results fetched via Playwright
3. Synthesis via the model router, instructed to only state claims the source material supports

## Success criteria
- `sources` non-empty
- Summary grounded in fetched page content

## Verification
`source_reference` evidence: each cited URL is the actual URL fetched, traceable to the real Playwright call. `cross_check_result`: a second independent fetch confirming the same claim before verified=true.

## Failure handling
`missing_information`/`external_service_failure` — not silently treated as "complete with zero findings"; the mission evaluator requires verified evidence.
