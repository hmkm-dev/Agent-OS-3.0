#!/usr/bin/env bash
# Docker build contexts are isolated per service, but a few modules
# (agents/workspace.py, services/workers/common/base_worker.py) are
# shared across services. This script copies the canonical source
# into each service directory before `docker compose build`.
# Run this after editing any shared module and before building.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[sync] agents/workspace.py -> services/mcp/agents/workspace.py"
mkdir -p services/mcp/agents
cp agents/workspace.py services/mcp/agents/workspace.py
touch services/mcp/agents/__init__.py

echo "[sync] services/workers/common/base_worker.py -> each worker dir"
for w in opencode research creative; do
  cp services/workers/common/base_worker.py services/workers/$w/base_worker.py
done

echo "[sync] done"

echo "[sync] policy/approval/agents/evaluator -> services/hermes/"
cp services/policy/engine.py services/hermes/policy/engine.py
cp services/policy/rules.yaml services/hermes/policy/rules.yaml
cp services/approval/manager.py services/hermes/approval/manager.py
cp agents/identity.py services/hermes/agents/identity.py
cp agents/workspace.py services/hermes/agents/workspace.py
cp services/evaluator/evaluator.py services/hermes/evaluator/evaluator.py
echo "[sync] done (extended)"

echo "[sync] memory + handoff -> services/hermes/"
mkdir -p services/hermes/memory services/hermes/handoff
cp services/memory/embeddings.py services/hermes/memory/embeddings.py
cp services/memory/qdrant_client.py services/hermes/memory/qdrant_client.py
cp services/memory/pipeline.py services/hermes/memory/pipeline.py
cp services/handoff/manager.py services/hermes/handoff/manager.py
touch services/hermes/memory/__init__.py services/hermes/handoff/__init__.py

echo "[sync] agent_runtime -> services/workers/opencode/"
cp services/runtime/agent_runtime.py services/workers/opencode/agent_runtime.py

echo "[sync] done (phase A/B/C additions)"

echo "[sync] skill_engine -> services/hermes/"
mkdir -p services/hermes/skill_engine
cp services/skill_engine/skill.py services/hermes/skill_engine/skill.py
cp services/skill_engine/teach.py services/hermes/skill_engine/teach.py
cp services/skill_engine/routine.py services/hermes/skill_engine/routine.py
touch services/hermes/skill_engine/__init__.py
echo "[sync] done (skill_engine)"

echo "[sync] tool_validation.py -> services/hermes/skill_engine/"
cp services/skill_engine/tool_validation.py services/hermes/skill_engine/tool_validation.py
echo "[sync] done (tool_validation)"

echo "[sync] mission/* -> services/hermes/mission/"
mkdir -p services/hermes/mission
for f in control task_graph decomposition failure_recovery evidence mission_evaluator cost_tracker artifacts context executor verifiers verification_pipeline strategy idempotency; do
  [ -f "services/mission/$f.py" ] && cp "services/mission/$f.py" "services/hermes/mission/$f.py"
done
touch services/hermes/mission/__init__.py
echo "[sync] done (mission control)"

echo "[sync] Agent OS 3.0 capability layer -> dedicated workers"
for w in rlm; do
  rm -rf "services/workers/$w/agent_os30"
  cp -R services/hermes/agent_os30 "services/workers/$w/agent_os30"
done
for w in browser seo marketing devops; do
  cp services/workers/common/base_worker.py "services/workers/$w/base_worker.py"
done
# Verification worker needs the canonical mission verification stack and DB wrapper.
cp services/workers/common/base_worker.py services/workers/verification/base_worker.py
cp services/hermes/db.py services/workers/verification/db.py
rm -rf services/workers/verification/mission
cp -R services/hermes/mission services/workers/verification/mission
rm -rf services/workers/verification/evaluator
cp -R services/hermes/evaluator services/workers/verification/evaluator
# Keep worker-local imports deterministic for isolated Docker build contexts.
echo "[sync] done (Agent OS 3.0 workers)"
