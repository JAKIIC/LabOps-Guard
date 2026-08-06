"""Deterministic minimum-change experiment planner."""

from __future__ import annotations

from labops.contracts import validate_document


def plan_checkpoint_repair(
    hypothesis: dict,
    *,
    plan_id: str = "PLAN-DEMO-001",
    command: str = "python evaluate.py --run-dir <sandbox-run>",
    approval_required: bool = False,
    extra: dict | None = None,
) -> dict:
    if not hypothesis.get("evidence_ids"):
        raise ValueError("plan requires an evidence-grounded hypothesis")
    plan = {
        "plan_id": plan_id,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "objective": "Verify whether selecting best.pt restores validation accuracy.",
        "changes": [{
            "file": "eval_config.json",
            "field": "checkpoint",
            "before": "checkpoints/last.pt",
            "after": "checkpoints/best.pt",
        }],
        "command": command,
        "success_criteria": {
            "metric": "accuracy",
            "minimum": 0.88,
            "minimum_improvement": 0.15,
            "repeats": 3,
        },
        "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
        "risk_level": "L1",
        "approval_required": approval_required,
        "rollback": "discard sandbox or restore eval_config.json from snapshot",
        "forbidden_changes": ["metric.py", "dataset", "target_metric", "original_workspace"],
    }
    if extra:
        plan.update(extra)
    validate_document(plan, "plan.schema.json")
    return plan


def plan_eval_drift_repair(
    hypothesis: dict,
    *,
    plan_id: str = "PLAN-LABOPS-AT-004-001",
    approval_required: bool = True,
    extra: dict | None = None,
) -> dict:
    if not hypothesis.get("evidence_ids"):
        raise ValueError("plan requires an evidence-grounded hypothesis")
    plan = {
        "plan_id": plan_id,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "objective": "Verify whether restoring the historical evaluation preprocessing profile recovers accuracy.",
        "changes": [{
            "file": "eval_config.json",
            "field": "evaluation.preprocessing_profile",
            "before": "train_augmented",
            "after": "eval_standard",
        }],
        "command": "evaluate_preprocessing_profile",
        "success_criteria": {
            "metric": "accuracy",
            "minimum": 0.97,
            "minimum_improvement": 0.20,
            "maximum_repeat_spread": 0.001,
            "repeats": 3,
        },
        "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
        "risk_level": "L1",
        "approval_required": approval_required,
        "rollback": "discard the sandbox or restore evaluation.preprocessing_profile from the snapshot",
        "forbidden_changes": [
            "metric.py", "validation_data.pt", "checkpoint", "evaluation_protocol.yaml",
            "target_metric", "original_workspace",
        ],
    }
    if extra:
        plan.update(extra)
    validate_document(plan, "plan.schema.json")
    return plan


def check_plan_policy(plan: dict) -> dict:
    changes = plan.get("changes", [])
    checkpoint_allowed = (
        len(changes) == 1
        and changes[0].get("file") == "eval_config.json"
        and changes[0].get("field") == "checkpoint"
        and changes[0].get("before") == "checkpoints/last.pt"
        and changes[0].get("after") == "checkpoints/best.pt"
        and plan.get("budget", {}).get("network") is False
        and plan.get("budget", {}).get("device") == "cpu"
        and 0 < int(plan.get("budget", {}).get("max_runtime_seconds", 0)) <= 30
        and bool(plan.get("rollback"))
        and {"metric.py", "dataset", "target_metric", "original_workspace"}.issubset(
            set(plan.get("forbidden_changes", []))
        )
    )
    eval_drift_allowed = (
        len(changes) == 1
        and changes[0].get("file") == "eval_config.json"
        and changes[0].get("field") == "evaluation.preprocessing_profile"
        and changes[0].get("before") == "train_augmented"
        and changes[0].get("after") == "eval_standard"
        and plan.get("command") == "evaluate_preprocessing_profile"
        and plan.get("budget", {}).get("network") is False
        and plan.get("budget", {}).get("device") == "cpu"
        and 0 < int(plan.get("budget", {}).get("max_runtime_seconds", 0)) <= 30
        and int(plan.get("success_criteria", {}).get("repeats", 0)) == 3
        and bool(plan.get("rollback"))
        and {
            "metric.py", "validation_data.pt", "checkpoint", "evaluation_protocol.yaml",
            "target_metric", "original_workspace",
        }.issubset(set(plan.get("forbidden_changes", [])))
    )
    allowed = checkpoint_allowed or eval_drift_allowed
    return {
        "plan_id": plan.get("plan_id"),
        "decision": "AUTO_APPROVED" if allowed else "REJECTED",
        "risk_level": plan.get("risk_level"),
        "reason": (
            "single L1 checkpoint field change" if checkpoint_allowed
            else "single L1 evaluation preprocessing profile change" if eval_drift_allowed
            else "plan exceeds the allowlisted single-variable scope"
        ),
    }
