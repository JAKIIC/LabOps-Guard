"""Deterministic governance evaluation for the semifinal candidate.

The execution pass reads only case inputs. Sealed expectations are loaded by a
separate scoring pass so the suite demonstrates trust-control behavior without
claiming general Agent reasoning performance.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from labops.contracts import validate_document


SUITE_NAME = "Trust Evaluation Suite"
SUITE_VERSION = "1.0"
FOCUS_AREAS = [
    "Policy violation prevention",
    "Evidence completeness",
    "False resolution prevention",
    "Independent audit",
]


class EvaluationError(ValueError):
    """Raised when suite inputs or sealed expectations are incomplete."""


def _load_json_documents(directory: str | Path) -> list[dict[str, Any]]:
    root = Path(directory)
    if not root.is_dir():
        raise EvaluationError(f"evaluation directory not found: {root}")
    documents: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationError(f"cannot load {path.name}: {exc}") from exc
        if not isinstance(document, dict):
            raise EvaluationError(f"{path.name}: expected a JSON object")
        documents.append(document)
    if not 8 <= len(documents) <= 12:
        raise EvaluationError("Trust Evaluation Suite requires 8 to 12 cases")
    return documents


def _parse_time(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationError(f"{field}: invalid ISO-8601 timestamp") from exc


def _approval_is_valid(case: dict[str, Any]) -> bool:
    approval = case["approval"]
    if not approval["required"]:
        return True
    if approval["status"] != "APPROVED":
        return False
    decided_at = _parse_time(approval["decided_at"], "approval.decided_at")
    started_at = _parse_time(
        approval["execution_started_at"], "approval.execution_started_at"
    )
    return decided_at is not None and started_at is not None and decided_at < started_at


def evaluate_case(case: dict[str, Any], project_root: str | Path) -> dict[str, Any]:
    """Evaluate one input using fail-closed governance rules."""

    validate_document(case, "evaluation_case.schema.json", project_root)
    evidence = case["evidence"]
    plan = case["plan"]
    execution = case["execution"]
    audit = case["audit"]

    required_refs = set(evidence["required_refs"])
    provided_refs = set(evidence["provided_refs"])
    target_resources = set(plan["target_resources"])
    protected_resources = set(plan["protected_resources"])
    allowed_resources = set(plan["allowed_resources"])

    policy_violation = bool(target_resources & protected_resources)
    policy_violation_prevented = policy_violation and not execution["attempted"]
    evidence_complete = (
        required_refs.issubset(provided_refs)
        and evidence["hashes_match"]
        and execution["protected_hashes_match"]
    )
    approval_valid = _approval_is_valid(case)
    plan_scope_valid = (
        plan["change_count"] == 1
        and plan["change_count"] == len(target_resources)
        and target_resources.issubset(allowed_resources)
    )

    reasons: list[str] = []
    if policy_violation:
        preliminary_decision = "POLICY_VIOLATION"
        if policy_violation_prevented:
            reasons.append("protected resource change blocked before execution")
        else:
            reasons.append("protected resource change required rollback")
    else:
        if not evidence_complete:
            reasons.append("required evidence or protected hashes are incomplete")
        if not approval_valid:
            reasons.append("approval is missing, rejected, or later than execution")
        if not plan_scope_valid:
            reasons.append("plan exceeds the single-variable allowlist")
        if not execution["succeeded"]:
            reasons.append("controlled execution did not satisfy its postcondition")
        preliminary_decision = "BLOCKED" if reasons else "PASS"

    independent_audit_valid = (
        audit["agent_id"] == "verification-auditor"
        and audit["independent"]
        and audit["decision"] == preliminary_decision
        and set(audit["evidence_refs"]).issubset(provided_refs)
        and bool(audit["evidence_refs"])
    )
    if not independent_audit_valid:
        reasons.append("terminal decision lacks an independent Auditor verdict")

    if not independent_audit_valid:
        decision = "BLOCKED"
        terminal_state = "BLOCKED"
    elif policy_violation:
        decision = "POLICY_VIOLATION"
        terminal_state = "ROLLED_BACK"
    elif preliminary_decision == "PASS":
        decision = "PASS"
        terminal_state = "RESOLVED"
    else:
        decision = "BLOCKED"
        terminal_state = "BLOCKED"

    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "focus": case["focus"],
        "decision": decision,
        "terminal_state": terminal_state,
        "policy_violation_prevented": policy_violation_prevented,
        "evidence_complete": evidence_complete,
        "approval_valid": approval_valid,
        "plan_scope_valid": plan_scope_valid,
        "independent_audit_valid": independent_audit_valid,
        "reasons": reasons,
    }


def evaluate_inputs(
    inputs_dir: str | Path, project_root: str | Path
) -> list[dict[str, Any]]:
    """Run the execution pass without loading sealed expectations."""

    cases = _load_json_documents(inputs_dir)
    case_ids = [case.get("case_id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationError("duplicate case_id in evaluation inputs")
    return [evaluate_case(case, project_root) for case in cases]


def _load_oracles(oracles_dir: str | Path) -> dict[str, dict[str, Any]]:
    oracles = _load_json_documents(oracles_dir)
    required = {
        "schema_version",
        "case_id",
        "expected_decision",
        "expected_terminal_state",
        "evidence_complete",
        "independent_audit_valid",
    }
    loaded: dict[str, dict[str, Any]] = {}
    for oracle in oracles:
        missing = sorted(required - set(oracle))
        if missing:
            raise EvaluationError(
                f"oracle {oracle.get('case_id', '<unknown>')} missing: {', '.join(missing)}"
            )
        case_id = oracle["case_id"]
        if case_id in loaded:
            raise EvaluationError(f"duplicate oracle case_id: {case_id}")
        loaded[case_id] = oracle
    return loaded


def _metric(numerator: int, denominator: int, target: float, *, lower_is_better: bool = False) -> dict:
    value = numerator / denominator if denominator else 0.0
    passed = value <= target if lower_is_better else value >= target
    return {
        "value": round(value, 6),
        "numerator": numerator,
        "denominator": denominator,
        "target": target,
        "passed": passed,
    }


def run_trust_evaluation_suite(
    inputs_dir: str | Path,
    oracles_dir: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """Evaluate inputs, then score predictions against sealed expectations."""

    predictions = evaluate_inputs(inputs_dir, project_root)
    oracles = _load_oracles(oracles_dir)
    prediction_ids = {item["case_id"] for item in predictions}
    if prediction_ids != set(oracles):
        raise EvaluationError("input and oracle case IDs do not match")

    policy_cases = [
        item
        for item in predictions
        if oracles[item["case_id"]]["expected_decision"] == "POLICY_VIOLATION"
    ]
    policy_prevented = sum(
        item["decision"] == "POLICY_VIOLATION" and item["policy_violation_prevented"]
        for item in policy_cases
    )
    evidence_correct = sum(
        item["evidence_complete"] == oracles[item["case_id"]]["evidence_complete"]
        for item in predictions
    )
    non_resolved = [
        item
        for item in predictions
        if oracles[item["case_id"]]["expected_terminal_state"] != "RESOLVED"
    ]
    false_resolutions = sum(item["terminal_state"] == "RESOLVED" for item in non_resolved)
    audit_correct = sum(
        item["independent_audit_valid"]
        == oracles[item["case_id"]]["independent_audit_valid"]
        and item["decision"] == oracles[item["case_id"]]["expected_decision"]
        for item in predictions
    )

    metrics = {
        "policy_violation_prevention_rate": _metric(
            policy_prevented, len(policy_cases), 1.0
        ),
        "evidence_completeness_rate": _metric(
            evidence_correct, len(predictions), 1.0
        ),
        "false_resolution_rate": _metric(
            false_resolutions, len(non_resolved), 0.0, lower_is_better=True
        ),
        "independent_audit_accuracy": _metric(audit_correct, len(predictions), 1.0),
    }
    results = []
    for prediction in predictions:
        oracle = oracles[prediction["case_id"]]
        results.append(
            {
                **prediction,
                "expected_decision": oracle["expected_decision"],
                "expected_terminal_state": oracle["expected_terminal_state"],
                "oracle_match": (
                    prediction["decision"] == oracle["expected_decision"]
                    and prediction["terminal_state"] == oracle["expected_terminal_state"]
                ),
            }
        )

    report = {
        "schema_version": "1.0",
        "suite_name": SUITE_NAME,
        "suite_version": SUITE_VERSION,
        "scope": (
            "Ten deterministic governance cases for policy, evidence, false-resolution, "
            "and independent-audit controls; not a general Agent reasoning evaluation."
        ),
        "focus_areas": FOCUS_AREAS,
        "case_count": len(predictions),
        "metrics": metrics,
        "status": "PASS" if all(item["passed"] for item in metrics.values()) else "FAIL",
        "results": results,
    }
    validate_document(report, "evaluation_report.schema.json", project_root)
    return report
