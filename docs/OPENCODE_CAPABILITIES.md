# OpenCode capability profiles

In `HYBRID_MODE=1`, Hermes remains the control-plane authority and routes specialist-assigned mission tasks to the existing `queue:opencode`. The requested role is retained as `capability_profile`; OpenCode does not start a new permanent worker for that role.

The profile map lives in `services/mission/executor.py`. It supplies the existing SkillEngine name and the minimum MCP tool declaration when a mission task does not explicitly provide tools. OpenCode retrieves approved instructions through Hermes’ protected SkillEngine endpoint and performs explicit tool calls through the MCP gateway. The gateway remains the authorization boundary; these profiles do not grant credentials or bypass policy.

| Profile | Approved SkillEngine name | Default MCP tools | Existing capability source | Legacy fallback |
|---|---|---|---|---|
| `seo` | `seo` | `search`, `playwright`, `filesystem` | `skills/seo/SKILL.md` and MCP adapters | `queue:seo` / `services/workers/seo` |
| `marketing` | `marketing` | `search`, `filesystem` | `skills/marketing/SKILL.md` and MCP adapters | `queue:marketing` / `services/workers/marketing` |
| `devops` | `devops` | `filesystem`, `github` | `skills/devops/SKILL.md` and policy rules | `queue:devops` / `services/workers/devops` |
| `browser` | `browser` | `playwright` | `skills/browser/SKILL.md`, MCP, and Playwright service | `queue:browser` / `services/workers/browser` |
| `creative` | `creative` | `filesystem` | `skills/creative/SKILL.md`; R2 remains separate | `queue:creative` / `services/workers/creative` |
| `research` | `research` | `search`, `playwright` | `skills/research/SKILL.md` and MCP adapters | `queue:research` / `services/workers/research` |

## Safety and fallback

Only a Hermes-issued OpenCode capability request can reach this path. OpenCode validates the declared tool set before calling the MCP client, and the gateway applies its worker allowlist. A profile does not make external credentials available; provider configuration and approval remain deployment concerns.

The legacy worker directories, queues, Compose services, and tests remain intact. Setting `HYBRID_MODE=0` preserves the legacy deployment branch, and the legacy queues remain available for rollback or parity testing. The RLM runtime and verification/evidence path remain independent and are not represented as ordinary OpenCode skill profiles.

## Verification contract

A capability migration is considered ready for later worker decommissioning only after the profile has passed output-parity, policy, evidence, retry, and resource tests in a real staging environment. This document records the routing contract; it does not claim live provider, browser, R2, or external API verification.
