# Skill: Creative

**Status: IMPLEMENTED** — this is the existing Creative worker (`services/workers/creative/worker.py`), unchanged. Real model-router calls + R2 upload.

## Purpose
Content generation (text, image prompts, structured content) for LuxeNest Decor-style use cases (Pinterest descriptions, blog content, etc.) — the actual publishing (Bug: Pinterest/Instagram posting) is a SEPARATE skill (see `skills/pinterest/`, `skills/instagram/`), since posting requires external OAuth this repo doesn't have configured.

## Inputs / Outputs / Allowed tools
Unchanged from the existing worker — see `skills/marketing/SKILL.md` (same worker, this is the generic version).

## Success criteria / verification
Content exists and is well-formed. No "was this actually published and did it perform" verification here — that's downstream of the Pinterest/Instagram skills once those are connected.

## Failure handling
Standard classification.
