"""
Two-level evaluation — per spec §10-11. The EXISTING task-level
evaluator (services/evaluator/evaluator.py) is unchanged and still
answers "was this individual task done correctly?". This module adds
the MISSION-level question: "was the original user goal actually
achieved?" — which is not implied by all tasks passing (spec's
explicit example: 20/20 tasks complete != mission complete).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .evidence import EvidenceEngine

MISSION_VERIFICATION_PROMPT = """You are performing FINAL VERIFICATION of a completed mission. Be skeptical — your job is to catch false completion, not to be agreeable.

Original goal: {goal}
Objective: {objective}
Success criteria: {success_criteria}

All tasks in this mission report status "passed". Here is the VERIFIED evidence collected (unverified claims are excluded — only independently-confirmed evidence is shown):
{evidence}

For EACH success criterion, determine if the verified evidence above actually demonstrates it was met. Respond with ONLY a JSON object:
{{
  "criteria_results": [{{"criterion": "...", "met": true/false, "reasoning": "..."}}],
  "overall_verdict": "COMPLETED" | "INCOMPLETE",
  "gaps": ["what's missing if not COMPLETED"]
}}"""


class MissionEvaluator:
    def __init__(self, db, route_fn):
        self.db = db
        self.evidence_engine = EvidenceEngine(db)
        self.route_fn = route_fn

    async def evaluate_mission(self, mission: dict) -> dict:
        """Real check against success_criteria, using only VERIFIED
        evidence (not claimed). Returns a structured verdict — never
        returns COMPLETED just because task records say 'passed'."""
        success_criteria = json.loads(mission["success_criteria"]) if isinstance(mission["success_criteria"], str) else mission["success_criteria"]
        verified_evidence = await self.evidence_engine.get_mission_evidence(mission["mission_id"], verified_only=True)
        tasks = await self.db.fetch("SELECT * FROM mission_tasks WHERE mission_id = $1", mission["mission_id"])
        tasks = [dict(t) for t in tasks]
        missing_task_evidence = [
            str(t["task_id"]) for t in tasks
            if t.get("status") in ("passed", "skipped")
            and not await self.evidence_engine.has_verified_evidence_for_task(t["task_id"])
        ]

        if missing_task_evidence:
            return {
                "overall_verdict": "INCOMPLETE",
                "gaps": [f"passed task(s) without independently verified evidence: {', '.join(missing_task_evidence)}"],
                "criteria_results": [{"criterion": c, "met": False, "reasoning": "not every passed task has verified evidence"} for c in success_criteria],
            }

        if not verified_evidence:
            return {
                "overall_verdict": "INCOMPLETE",
                "gaps": ["no verified evidence exists for this mission — only claims, if any"],
                "criteria_results": [{"criterion": c, "met": False, "reasoning": "no verified evidence"} for c in success_criteria],
            }

        evidence_summary = "\n".join(
            f"- [{e['kind']}] {e['claim']} (verified: {e['verification_detail']})" for e in verified_evidence
        )

        prompt = MISSION_VERIFICATION_PROMPT.format(
            goal=mission["user_goal"], objective=mission.get("objective") or "(none stated)",
            success_criteria=json.dumps(success_criteria), evidence=evidence_summary,
        )
        response = await self.route_fn("reasoning", prompt)
        result = self._parse(response["text"])

        await self.db.execute(
            "UPDATE missions SET final_verification = $1, updated_at = $2 WHERE mission_id = $3",
            json.dumps(result), datetime.now(timezone.utc), mission["mission_id"],
        )
        return result

    def _parse(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            # Fail closed: an unparseable verification response means
            # we cannot confirm completion, so INCOMPLETE, not COMPLETED.
            return {
                "overall_verdict": "INCOMPLETE",
                "gaps": [f"mission evaluator response was not valid JSON: {e}"],
                "criteria_results": [],
            }
        if parsed.get("overall_verdict") not in ("COMPLETED", "INCOMPLETE"):
            parsed["overall_verdict"] = "INCOMPLETE"
            parsed.setdefault("gaps", []).append("evaluator returned an unrecognized verdict, defaulting to INCOMPLETE")
        return parsed
