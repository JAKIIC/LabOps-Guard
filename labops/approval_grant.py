"""ApprovalGrant v1 strong binding for governed Runner execution.

This module is deliberately independent of the Trust State Machine.  It binds
one human decision to one immutable plan, run, side-effect scope and resource
budget, then records single-use consumption before the Runner starts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from labops.contracts import validate_document


AGENT_IDENTITIES = {
    "labops-manager",
    "evidence-collector",
    "rca-analyst",
    "experiment-planner",
    "safe-executor",
    "verification-auditor",
}


class ApprovalBindingError(ValueError):
    """A fail-closed ApprovalGrant rejection with a stable reason code."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def canonical_plan_sha256(plan: dict) -> str:
    """Hash a plan using deterministic UTF-8 JSON canonicalization."""

    if not isinstance(plan, dict):
        raise TypeError("plan must be an object")
    encoded = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ApprovalBindingError("APPROVAL_EXPIRED", f"{field} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalBindingError("APPROVAL_EXPIRED", f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ApprovalBindingError("APPROVAL_EXPIRED", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _plan_scope(plan: dict) -> list[str]:
    scope: list[str] = []
    for change in plan.get("changes", []):
        if not isinstance(change, dict):
            raise ApprovalBindingError("SCOPE_MISMATCH", "plan changes must be objects")
        file_name = change.get("file")
        field = change.get("field")
        if not isinstance(file_name, str) or not file_name or not isinstance(field, str) or not field:
            raise ApprovalBindingError("SCOPE_MISMATCH", "each plan change requires file and field")
        scope.append(f"{file_name}:{field}")
    return sorted(scope)


def _same_string_set(left: object, right: object) -> bool:
    return (
        isinstance(left, list)
        and isinstance(right, list)
        and all(isinstance(item, str) for item in left + right)
        and sorted(left) == sorted(right)
    )


def validate_approval_grant(
    plan: dict,
    grant: dict,
    tool_contract: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Validate that a human ApprovalGrant exactly authorizes this invocation."""

    try:
        validate_document(grant, "approval_grant.schema.json")
    except (ValueError, OSError) as exc:
        raise ApprovalBindingError("SCOPE_MISMATCH", f"invalid ApprovalGrant v1: {exc}") from exc
    required_strings = (
        "approval_id",
        "task_id",
        "incident_id",
        "plan_id",
        "canonical_plan_sha256",
        "run_id",
        "decided_by",
        "approved_at",
        "expires_at",
        "nonce",
    )
    if grant.get("schema_version") != "1.0" or grant.get("decision") != "APPROVED":
        raise ApprovalBindingError("SCOPE_MISMATCH", "ApprovalGrant must use version 1.0 and APPROVED")
    if any(not isinstance(grant.get(name), str) or not grant[name] for name in required_strings):
        raise ApprovalBindingError("SCOPE_MISMATCH", "ApprovalGrant identifiers must be non-empty strings")
    if len(grant["nonce"]) < 8:
        raise ApprovalBindingError("SCOPE_MISMATCH", "ApprovalGrant nonce is too short")

    expected_hash = canonical_plan_sha256(plan)
    if grant["canonical_plan_sha256"] != expected_hash:
        raise ApprovalBindingError("PLAN_HASH_MISMATCH", "approval is bound to a different plan")

    identity_pairs = (
        ("task_id", plan.get("task_id")),
        ("incident_id", plan.get("incident_id")),
        ("plan_id", plan.get("plan_id")),
        ("run_id", plan.get("run_id")),
    )
    if any(grant.get(name) != value for name, value in identity_pairs):
        raise ApprovalBindingError("SCOPE_MISMATCH", "approval identity does not match the plan")
    if tool_contract.get("approval_reference") != grant.get("approval_id"):
        raise ApprovalBindingError("SCOPE_MISMATCH", "tool contract approval reference does not match")
    if any(
        tool_contract.get(name) != grant.get(name)
        for name in ("task_id", "incident_id", "run_id")
    ):
        raise ApprovalBindingError("SCOPE_MISMATCH", "tool contract identity does not match approval")

    if grant.get("decision") != "APPROVED" or grant.get("decided_by") in AGENT_IDENTITIES:
        raise ApprovalBindingError("SCOPE_MISMATCH", "approval must be accepted by a separate human")
    if sorted(grant.get("approved_scope", [])) != _plan_scope(plan):
        raise ApprovalBindingError("SCOPE_MISMATCH", "approved scope does not match plan changes")

    plan_protected = plan.get("forbidden_changes", [])
    if not _same_string_set(grant.get("allowed_side_effects"), tool_contract.get("allowed_side_effects")):
        raise ApprovalBindingError("SCOPE_MISMATCH", "allowed side effects do not match tool contract")
    if not _same_string_set(grant.get("protected_resources"), plan_protected):
        raise ApprovalBindingError("SCOPE_MISMATCH", "protected resources do not match plan")
    if not _same_string_set(grant.get("protected_resources"), tool_contract.get("protected_resources")):
        raise ApprovalBindingError("SCOPE_MISMATCH", "protected resources do not match tool contract")

    if grant.get("resource_budget") != plan.get("budget"):
        raise ApprovalBindingError("BUDGET_MISMATCH", "approved budget does not match plan")
    if grant.get("resource_budget") != tool_contract.get("resource_budget"):
        raise ApprovalBindingError("BUDGET_MISMATCH", "approved budget does not match tool contract")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    approved_at = _parse_timestamp(grant.get("approved_at"), "approved_at")
    expires_at = _parse_timestamp(grant.get("expires_at"), "expires_at")
    if approved_at > current or expires_at < current or expires_at <= approved_at:
        raise ApprovalBindingError("APPROVAL_EXPIRED", "approval is not active at execution time")

    return {
        "status": "VALID",
        "approval_id": grant["approval_id"],
        "canonical_plan_sha256": expected_hash,
        "run_id": grant["run_id"],
        "nonce": grant["nonce"],
    }


def consume_approval_nonce(grant: dict, ledger_path: str | Path) -> dict:
    """Persist one-time ApprovalGrant consumption in an append-only JSON ledger."""

    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        records = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ApprovalBindingError("APPROVAL_REPLAYED", "approval nonce ledger is invalid")
    else:
        records = []
    if any(
        record.get("nonce") == grant.get("nonce")
        or record.get("approval_id") == grant.get("approval_id")
        for record in records
        if isinstance(record, dict)
    ):
        raise ApprovalBindingError("APPROVAL_REPLAYED", "approval grant has already been consumed")

    record = {
        "approval_id": grant["approval_id"],
        "nonce": grant["nonce"],
        "run_id": grant["run_id"],
        "consumed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    records.append(record)
    temporary = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(ledger_path)
    return {"status": "CONSUMED", **record}
