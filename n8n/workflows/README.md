# n8n Workflows

## What's here
`skill_routine_trigger.json` — a **minimal example**, not a production
routine. It shows the pattern: a schedule trigger calling Hermes's
`POST /tasks` endpoint with an API key header. This is deliberately
simple (single hardcoded task type in `$json.taskType`) rather than a
fully general routine engine — build your actual Pinterest/backlink
routines from this pattern once you know the specific task payloads
you want to automate (see LuxeNest Decor content workflow).

## Importing
1. Open n8n (`https://n8n.yourdomain.com` once Phase 10 is deployed).
2. Workflows → Import from File → select `skill_routine_trigger.json`.
3. Set environment variables in n8n's settings (or via
   `N8N_ENV_FILE`/Docker env): `HERMES_URL` (e.g. `http://hermes:8000`
   — internal Docker network, not the public hostname) and
   `HERMES_API_KEY` (same value as in `.env`).
4. Edit the schedule and the JSON body to match a real task you want
   automated, then toggle the workflow **Active**.

## Credentials required
None beyond the two environment variables above — this workflow talks
to Hermes over the internal Docker network, not to any external
service directly. If you build a routine that calls Playwright/GitHub/
search directly from n8n instead of going through Hermes, you'd be
bypassing the policy engine and evaluator — don't do that. Routines
should always go through `POST /tasks`, never call workers or MCP
directly.

## Webhook-triggered routines
If you want a routine triggered by an external webhook (e.g. a form
submission) instead of a schedule, replace the Schedule Trigger node
with an n8n Webhook node. The webhook URL will be
`https://n8n.yourdomain.com/webhook/<path>` — put this behind
Cloudflare Access or a shared-secret query param, since n8n's webhook
URLs are otherwise unauthenticated by default.
