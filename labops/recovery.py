"""Governed recovery and human-takeover overlay for non-formal live demos.

This module does not change the Trust State Machine.  It records append-only
attempt ownership and recovery decisions beside an isolated LiveDemoSession.
The current overlay is always reconstructed from the verified hash chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from labops.contracts import ContractError, validate_document
from labops.trace import TraceLog


CLASSIFICATION = "NON_FORMAL_LIVE_DEMO"
FAILURE_TYPES = {
    "EVIDENCE_INCOMPLETE",
    "WORKER_TIMEOUT",
    "CAPABILITY_MISSING",
    "TOOL_FAILURE",
    "POLICY_VIOLATION",
    "AUDIT_INCONCLUSIVE",
}
TERMINAL_POINTS = {"PASS", "RESOLVED", "ROLLED_BACK", "BLOCKED", "REJECTED"}
RESUME_POINTS = {
    "RECEIVED",
    "EVIDENCE_COLLECTING",
    "DIAGNOSING",
    "PLANNING",
    "POLICY_CHECKING",
    "APPROVAL_PENDING",
    "EXECUTING",
    "VERIFYING",
}


class RecoveryError(ValueError):
    """Recovery evidence or requested transition failed closed."""


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"cannot read {path.name}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise RecoveryError(f"{path.name} must contain an object")
    return value


def _session(session_root: str | Path) -> tuple[Path, dict]:
    root = Path(session_root).resolve()
    manifest = _read_object(root / "session.json")
    if manifest.get("classification") != CLASSIFICATION:
        raise RecoveryError("recovery is restricted to NON_FORMAL_LIVE_DEMO sessions")
    required = ("session_id", "attempt_id", "run_id", "agent_order")
    if any(not manifest.get(name) for name in required):
        raise RecoveryError("live session manifest lacks recovery bindings")
    return root, manifest


def _trace(root: Path) -> TraceLog:
    return TraceLog(root / "recovery" / "recovery_trace.jsonl")


def _initial_attempt(manifest: dict) -> dict:
    return {
        "attempt_id": manifest["attempt_id"],
        "parent_attempt_id": None,
        "run_id": manifest["run_id"],
        "start_state": "RECEIVED",
        "resume_point": "RECEIVED",
        "owner_id": "labops-manager",
        "status": "ACTIVE",
        "failure_type": None,
        "assigned_worker_id": None,
        "alternate_worker_evidence": None,
        "required_final_actor": "verification-auditor",
    }


def _base_overlay(manifest: dict) -> dict:
    return {
        "schema_version": "1.0",
        "classification": CLASSIFICATION,
        "session_id": manifest["session_id"],
        "attempts": [_initial_attempt(manifest)],
        "retry_counters": {},
        "pending_takeover": None,
        "last_decision": None,
        "recovery_trace": {
            "path": "recovery/recovery_trace.jsonl",
            "status": "ABSENT",
            "event_count": 0,
        },
    }


def _fold(manifest: dict, records: list[dict]) -> dict:
    overlay = _base_overlay(manifest)
    for record in records:
        event = record.get("event")
        extra = record.get("extra")
        if not isinstance(extra, dict):
            raise RecoveryError(f"recovery event {event!r} lacks structured context")
        if event == "RECOVERY_REQUESTED":
            current = overlay["attempts"][-1]
            current["status"] = "BLOCKED"
            current["failure_type"] = extra.get("failure_type")
        elif event == "RETRY_BUDGET_CONSUMED":
            key = extra.get("counter_key")
            count = extra.get("count")
            if not isinstance(key, str) or not isinstance(count, int):
                raise RecoveryError("retry event is malformed")
            overlay["retry_counters"][key] = count
        elif event == "ATTEMPT_CREATED":
            attempt = extra.get("attempt")
            if not isinstance(attempt, dict):
                raise RecoveryError("attempt event is malformed")
            if any(item.get("attempt_id") == attempt.get("attempt_id") for item in overlay["attempts"]):
                raise RecoveryError("duplicate recovery attempt")
            overlay["attempts"].append(dict(attempt))
        elif event == "TAKEOVER_REQUESTED":
            takeover = extra.get("takeover")
            if overlay["pending_takeover"] is not None or not isinstance(takeover, dict):
                raise RecoveryError("human takeover event is malformed or duplicated")
            overlay["pending_takeover"] = dict(takeover)
        elif event == "TAKEOVER_ACCEPTED":
            pending = overlay["pending_takeover"]
            if not pending or pending.get("takeover_id") != extra.get("takeover_id"):
                raise RecoveryError("takeover acceptance has no matching request")
            pending["status"] = "TAKEOVER_ACCEPTED"
            pending["accepted_by"] = extra.get("accepted_by")
            pending["accepted_at"] = record.get("ts")
        elif event == "TAKEOVER_RESUMED":
            pending = overlay["pending_takeover"]
            if not pending or pending.get("takeover_id") != extra.get("takeover_id"):
                raise RecoveryError("takeover resume has no matching request")
            overlay["pending_takeover"] = None
        elif event in {
            "REASSIGN_UNAVAILABLE",
            "ROLLBACK_REQUIRED",
            "RECOVERY_DECIDED",
        }:
            pass
        else:
            raise RecoveryError(f"unknown recovery event: {event!r}")
        decision = extra.get("decision")
        if isinstance(decision, str):
            overlay["last_decision"] = decision
    overlay["recovery_trace"] = {
        "path": "recovery/recovery_trace.jsonl",
        "status": "VERIFIED",
        "event_count": len(records),
    }
    try:
        validate_document(overlay, "recovery_overlay.schema.json")
    except (ContractError, OSError, ValueError) as exc:
        raise RecoveryError(f"recovery overlay contract failed: {exc}") from exc
    return overlay


def load_recovery_overlay(session_root: str | Path) -> dict:
    """Verify the append-only recovery chain and rebuild its current overlay."""

    root, manifest = _session(session_root)
    trace_path = root / "recovery" / "recovery_trace.jsonl"
    if not trace_path.exists():
        overlay = _base_overlay(manifest)
        try:
            validate_document(overlay, "recovery_overlay.schema.json")
        except (ContractError, OSError, ValueError) as exc:
            raise RecoveryError(f"recovery overlay contract failed: {exc}") from exc
        return overlay
    trace = TraceLog(trace_path)
    try:
        ok, message = trace.verify_chain()
        records = trace.read()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"recovery trace is unreadable: {type(exc).__name__}") from exc
    if not ok:
        raise RecoveryError(f"recovery trace integrity failed: {message}")
    return _fold(manifest, records)


def _safe_source_refs(root: Path, source_refs: list[str] | None) -> list[str]:
    if not source_refs:
        raise RecoveryError("recovery requires at least one source evidence reference")
    checked: list[str] = []
    for reference in source_refs:
        if not isinstance(reference, str) or not reference:
            raise RecoveryError("source evidence reference must be a non-empty string")
        candidate = (root / reference).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RecoveryError("source evidence reference escapes the live session") from exc
        if not candidate.is_file():
            raise RecoveryError(f"source evidence does not exist: {reference}")
        checked.append(candidate.relative_to(root).as_posix())
    return checked


def _append(root: Path, entity_type: str, entity_id: str, event: str, actor: str, extra: dict) -> dict:
    return _trace(root).append(
        entity_type,
        entity_id,
        event,
        actor=actor,
        status=extra.get("decision") or extra.get("status"),
        extra=extra,
    )


def _next_attempt(manifest: dict, overlay: dict, resume_point: str, failure_type: str,
                  assigned_worker_id: str | None = None,
                  alternate_worker_evidence: dict | None = None) -> dict:
    attempt_number = len(overlay["attempts"]) + 1
    run_id = str(manifest["run_id"])
    try:
        prefix, suffix = run_id.rsplit("-", 1)
        next_suffix = int(suffix) + attempt_number - 1
    except (ValueError, TypeError) as exc:
        raise RecoveryError("initial run_id cannot allocate a recovery run") from exc
    if next_suffix > 999:
        raise RecoveryError("recovery run_id namespace exhausted")
    return {
        "attempt_id": f"LIVE-ATTEMPT-{manifest['session_id']}-{attempt_number:02d}",
        "parent_attempt_id": overlay["attempts"][-1]["attempt_id"],
        "run_id": f"{prefix}-{next_suffix:03d}",
        "start_state": "RECEIVED",
        "resume_point": resume_point,
        "owner_id": "labops-manager",
        "status": "PENDING",
        "failure_type": failure_type,
        "assigned_worker_id": assigned_worker_id,
        "alternate_worker_evidence": alternate_worker_evidence,
        "required_final_actor": "verification-auditor",
    }


def _counter_key(failure_type: str, failed_role: str | None) -> str:
    return f"{failure_type}:{failed_role or '*'}"


def _takeover(root: Path, manifest: dict, overlay: dict, failure_type: str,
              requested_by: str, source_refs: list[str], reason: str) -> dict:
    if overlay["pending_takeover"] is not None:
        raise RecoveryError("a human takeover is already pending")
    prior = sum(1 for item in _trace(root).read() if item.get("event") == "TAKEOVER_REQUESTED")
    takeover_id = f"TAKEOVER-{manifest['session_id']}-{prior + 1:02d}"
    takeover = {
        "takeover_id": takeover_id,
        "status": "TAKEOVER_PENDING",
        "failure_type": failure_type,
        "reason": reason,
        "requested_by": requested_by,
        "source_refs": source_refs,
        "accepted_by": None,
        "accepted_at": None,
    }
    _append(root, "human_takeover", takeover_id, "TAKEOVER_REQUESTED", requested_by, {
        "decision": "HUMAN_TAKEOVER",
        "takeover": takeover,
    })
    return {
        "decision": "HUMAN_TAKEOVER",
        "takeover_id": takeover_id,
        "takeover_status": "TAKEOVER_PENDING",
    }


def _validate_alternate(root: Path, failed_role: str | None, failed_worker_id: str | None,
                        evidence: dict | None) -> dict:
    if not isinstance(evidence, dict):
        raise RecoveryError("alternate Worker requires structured live evidence")
    required = ("worker_id", "role", "matrix_event_id", "capability_ref")
    if any(not isinstance(evidence.get(name), str) or not evidence[name] for name in required):
        raise RecoveryError("alternate Worker evidence is incomplete")
    if not failed_role or evidence["role"] != failed_role:
        raise RecoveryError("alternate Worker must retain the failed Agent role")
    if evidence["worker_id"] == failed_worker_id or not evidence["matrix_event_id"].startswith("$"):
        raise RecoveryError("alternate Worker identity or Matrix event is invalid")
    capability_ref = _safe_source_refs(root, [evidence["capability_ref"]])[0]
    capability = _read_object(root / capability_ref)
    if (
        capability.get("worker_id") != evidence["worker_id"]
        or capability.get("role") != failed_role
        or capability.get("status") != "READY"
    ):
        raise RecoveryError("alternate Worker capability artifact is not READY or identity-bound")
    matrix = _read_object(root / "evidence" / "matrix_events.json")
    events = matrix.get("events")
    if not isinstance(events, list):
        raise RecoveryError("Matrix evidence lacks an events array")
    match = next((item for item in events if isinstance(item, dict)
                  and item.get("event_id") == evidence["matrix_event_id"]), None)
    if not match or match.get("worker_id") != evidence["worker_id"] or match.get("sender_agent") != failed_role:
        raise RecoveryError("alternate Worker is not backed by the referenced Matrix event")
    normalized = dict(evidence)
    normalized["capability_ref"] = capability_ref
    return normalized


def request_recovery(session_root: str | Path, *, failure_type: str,
                     requested_by: str, source_refs: list[str],
                     failed_role: str | None = None,
                     failed_worker_id: str | None = None,
                     alternate_worker_evidence: dict | None = None,
                     idempotent: bool = False, safe_to_retry: bool = False) -> dict:
    """Record a governed recovery decision for one failed live attempt."""

    root, manifest = _session(session_root)
    if failure_type not in FAILURE_TYPES:
        raise RecoveryError(f"unsupported recovery failure: {failure_type}")
    if requested_by not in manifest["agent_order"]:
        raise RecoveryError("recovery must be requested by a canonical Agent role")
    refs = _safe_source_refs(root, source_refs)
    overlay = load_recovery_overlay(root)
    if overlay["pending_takeover"] is not None:
        raise RecoveryError("a human takeover is already pending")
    if failure_type in {"WORKER_TIMEOUT", "CAPABILITY_MISSING"} and not failed_role:
        raise RecoveryError(f"{failure_type} requires failed_role")
    validated_alternate = None
    if failure_type == "CAPABILITY_MISSING" and alternate_worker_evidence is not None:
        validated_alternate = _validate_alternate(
            root,
            failed_role,
            failed_worker_id,
            alternate_worker_evidence,
        )
    current = overlay["attempts"][-1]
    _append(root, "recovery", current["attempt_id"], "RECOVERY_REQUESTED", requested_by, {
        "failure_type": failure_type,
        "failed_role": failed_role,
        "failed_worker_id": failed_worker_id,
        "source_refs": refs,
    })
    overlay = load_recovery_overlay(root)

    if failure_type == "POLICY_VIOLATION":
        _append(root, "recovery", current["attempt_id"], "ROLLBACK_REQUIRED", requested_by, {
            "decision": "ROLLBACK_REQUIRED",
            "source_refs": refs,
        })
        return {"decision": "ROLLBACK_REQUIRED"}
    if failure_type == "AUDIT_INCONCLUSIVE":
        return _takeover(root, manifest, overlay, failure_type, requested_by, refs,
                         "independent audit is inconclusive")

    key = _counter_key(failure_type, failed_role)
    used = int(overlay["retry_counters"].get(key, 0))
    retry_allowed = used < 1
    decision = "RETRY"
    resume_point = "RECEIVED"
    assigned_worker = failed_worker_id or failed_role
    alternate = None

    if failure_type == "EVIDENCE_INCOMPLETE":
        decision = "RETRY_AFTER_EVIDENCE"
        resume_point = "EVIDENCE_COLLECTING"
    elif failure_type == "WORKER_TIMEOUT":
        pass
    elif failure_type == "TOOL_FAILURE":
        if not (idempotent and safe_to_retry):
            retry_allowed = False
    elif failure_type == "CAPABILITY_MISSING":
        if alternate_worker_evidence is None:
            _append(root, "recovery", current["attempt_id"], "REASSIGN_UNAVAILABLE", requested_by, {
                "decision": "REASSIGN_UNAVAILABLE",
                "failed_role": failed_role,
            })
            overlay = load_recovery_overlay(root)
            return _takeover(root, manifest, overlay, failure_type, requested_by, refs,
                             "no verifiable alternate Worker is available")
        alternate = validated_alternate
        decision = "REASSIGN"
        assigned_worker = alternate["worker_id"]

    if not retry_allowed:
        return _takeover(root, manifest, overlay, failure_type, requested_by, refs,
                         "automatic recovery budget is exhausted or unsafe")

    _append(root, "recovery", current["attempt_id"], "RETRY_BUDGET_CONSUMED", requested_by, {
        "counter_key": key,
        "count": used + 1,
    })
    overlay = load_recovery_overlay(root)
    attempt = _next_attempt(
        manifest,
        overlay,
        resume_point,
        failure_type,
        assigned_worker_id=assigned_worker,
        alternate_worker_evidence=alternate,
    )
    _append(root, "attempt", attempt["attempt_id"], "ATTEMPT_CREATED", "labops-manager", {
        "decision": decision,
        "attempt": attempt,
    })
    return {"decision": decision, "attempt": attempt}


def accept_human_takeover(session_root: str | Path, *, takeover_id: str,
                          accepted_by: str) -> dict:
    """Record explicit acceptance by a non-Agent policy identity."""

    root, manifest = _session(session_root)
    overlay = load_recovery_overlay(root)
    pending = overlay["pending_takeover"]
    if not pending or pending.get("takeover_id") != takeover_id:
        raise RecoveryError("no matching human takeover is pending")
    if not accepted_by or accepted_by in manifest["agent_order"]:
        raise RecoveryError("canonical Agent identities cannot accept Human Takeover")
    if pending.get("status") != "TAKEOVER_PENDING":
        raise RecoveryError("human takeover was already accepted")
    record = _append(root, "human_takeover", takeover_id, "TAKEOVER_ACCEPTED", accepted_by, {
        "status": "TAKEOVER_ACCEPTED",
        "takeover_id": takeover_id,
        "accepted_by": accepted_by,
    })
    return {
        "decision": "HUMAN_TAKEOVER_ACCEPTED",
        "takeover_id": takeover_id,
        "takeover_status": "TAKEOVER_ACCEPTED",
        "accepted_by": accepted_by,
        "accepted_at": record["ts"],
    }


def resume_human_takeover(session_root: str | Path, *, takeover_id: str,
                          resumed_by: str, resume_point: str) -> dict:
    """Return accepted work to AgentTeams without granting terminal authority."""

    root, manifest = _session(session_root)
    if resume_point in TERMINAL_POINTS or resume_point not in RESUME_POINTS:
        raise RecoveryError("Human Takeover may resume only at a non-terminal state")
    overlay = load_recovery_overlay(root)
    pending = overlay["pending_takeover"]
    if not pending or pending.get("takeover_id") != takeover_id:
        raise RecoveryError("no matching human takeover is pending")
    if pending.get("status") != "TAKEOVER_ACCEPTED":
        raise RecoveryError("Human Takeover must be accepted before resume")
    if pending.get("accepted_by") != resumed_by:
        raise RecoveryError("only the accepted Human Takeover owner may resume")
    attempt = _next_attempt(
        manifest,
        overlay,
        resume_point,
        str(pending.get("failure_type")),
    )
    _append(root, "attempt", attempt["attempt_id"], "ATTEMPT_CREATED", "labops-manager", {
        "decision": "HUMAN_TAKEOVER_RESUMED",
        "attempt": attempt,
    })
    _append(root, "human_takeover", takeover_id, "TAKEOVER_RESUMED", resumed_by, {
        "decision": "HUMAN_TAKEOVER_RESUMED",
        "takeover_id": takeover_id,
        "resume_point": resume_point,
        "attempt_id": attempt["attempt_id"],
    })
    return {
        "decision": "HUMAN_TAKEOVER_RESUMED",
        "takeover_id": takeover_id,
        "attempt": attempt,
    }
