"""Deterministic minimum-change experiment planner."""

from __future__ import annotations

from labops.contracts import validate_document


def plan_checkpoint_repair(hypothesis: dict) -> dict:
    if not hypothesis.get("evidence_ids"):
        raise ValueError("plan requires an evidence-grounded hypothesis")
    plan = {
        "plan_id": "PLAN-DEMO-001",
        "hypothesis_id": hypothesis["hypothesis_id"],
        "objective": "Verify whether selecting best.pt restores validation accuracy.",
        "changes": [{
            "file": "eval_config.json",
            "field": "checkpoint",
            "before": "checkpoints/last.pt",
            "after": "checkpoints/best.pt",
        }],
        "command": "python evaluate.py --run-dir <sandbox-run>",
        "success_criteria": {
            "metric": "accuracy",
            "minimum": 0.88,
            "minimum_improvement": 0.15,
            "repeats": 3,
        },
        "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
        "risk_level": "L1",
        "approval_required": False,
        "rollback": "discard sandbox or restore eval_config.json from snapshot",
        "forbidden_changes": ["metric.py", "dataset", "target_metric"],
    }
    validate_document(plan, "plan.schema.json")
    return plan


def check_plan_policy(plan: dict) -> dict:
    changes = plan.get("changes", [])
    allowed = (
        len(changes) == 1
        and changes[0].get("file") == "eval_config.json"
        and changes[0].get("field") == "checkpoint"
        and changes[0].get("before") == "checkpoints/last.pt"
        and changes[0].get("after") == "checkpoints/best.pt"
        and plan.get("budget", {}).get("network") is False
    )
    return {
        "plan_id": plan.get("plan_id"),
        "decision": "AUTO_APPROVED" if allowed else "REJECTED",
        "risk_level": plan.get("risk_level"),
        "reason": "single L1 checkpoint field change" if allowed else "plan exceeds checkpoint-only scope",
    }

