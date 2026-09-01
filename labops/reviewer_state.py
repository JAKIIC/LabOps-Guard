"""Truth-preserving projection for the read-only Reviewer Edition.

This module never drives AgentTeams, approves plans, invokes tools, or changes
workflow state.  It combines configured contracts with allowlisted evidence and
keeps workflow progress separate from evidence confidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from labops.live_demo import ROLE_ORDER, SESSION_ID, verify_session
from labops.recovery import RecoveryError, load_recovery_overlay
from labops.skill_registry import list_skills


EVIDENCE_STATES = {"NOT_OBSERVED", "CONFIGURED", "OBSERVED", "VERIFIED", "BLOCKED"}
ROLE_NAMES = {
    "labops-manager": "Incident Commander",
    "evidence-collector": "Evidence Collector",
    "rca-analyst": "RCA Analyst",
    "experiment-planner": "Experiment Planner",
    "safe-executor": "Safe Executor",
    "verification-auditor": "Verification Auditor",
}
EXPECTED_TIMELINE = [
    ("task_dispatched", "RECEIVED", "EVIDENCE_COLLECTING"),
    ("manager_to_collector", "RECEIVED", "EVIDENCE_COLLECTING"),
    ("evidence_collected", "EVIDENCE_COLLECTING", "EVIDENCE_READY"),
    ("collector_to_rca", "EVIDENCE_READY", "DIAGNOSING"),
    ("hypotheses_ranked", "DIAGNOSING", "DIAGNOSIS_READY"),
    ("rca_to_planner", "DIAGNOSIS_READY", "PLANNING"),
    ("policy_passed", "PLAN_READY", "POLICY_CHECKING"),
    ("approval_pending", "POLICY_CHECKING", "APPROVAL_PENDING"),
    ("approval_granted", "APPROVAL_PENDING", "APPROVED"),
    ("executor_to_gateway", "APPROVED", "EXECUTING"),
    ("runner_started", "APPROVED", "EXECUTING"),
    ("runner_completed", "EXECUTING", "VERIFYING"),
    ("executor_to_auditor", "EXECUTING", "VERIFYING"),
    ("verification_completed", "VERIFYING", "VERIFYING"),
    ("terminal_decided", "VERIFYING", "RESOLVED"),
    ("commander_published", "RESOLVED", "RESOLVED"),
]
EVENT_KINDS = {kind for kind, _, _ in EXPECTED_TIMELINE}
AGENT_PROGRESS = {
    "task_dispatched": ("labops-manager", "EVIDENCE_COLLECTING"),
    "manager_to_collector": ("labops-manager", "EVIDENCE_COLLECTING"),
    "evidence_collected": ("evidence-collector", "EVIDENCE_READY"),
    "collector_to_rca": ("evidence-collector", "EVIDENCE_READY"),
    "hypotheses_ranked": ("rca-analyst", "DIAGNOSIS_READY"),
    "rca_to_planner": ("rca-analyst", "DIAGNOSIS_READY"),
    "policy_passed": ("experiment-planner", "PLAN_READY"),
    "approval_pending": ("experiment-planner", "PLAN_READY"),
    "executor_to_gateway": ("safe-executor", "EXECUTING"),
    "runner_started": ("safe-executor", "EXECUTING"),
    "runner_completed": ("safe-executor", "VERIFYING"),
    "executor_to_auditor": ("safe-executor", "VERIFYING"),
    "verification_completed": ("verification-auditor", "VERIFYING"),
    "terminal_decided": ("verification-auditor", "RESOLVED"),
    "commander_published": ("labops-manager", "RESOLVED"),
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc(parsed)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def classify_source_status(
    mode: str,
    connected: bool,
    last_success_at: str | None,
    now: datetime,
    live_threshold_seconds: int = 15,
    disconnect_threshold_seconds: int = 60,
) -> str:
    """Classify a source from observed connectivity and freshness."""

    normalized = mode.lower()
    if normalized not in {"quick", "live"}:
        raise ValueError("mode must be quick or live")
    if normalized == "quick":
        return "REPLAY"
    if live_threshold_seconds < 0 or disconnect_threshold_seconds < live_threshold_seconds:
        raise ValueError("invalid source freshness thresholds")
    try:
        last_success = _parse_utc(last_success_at)
    except (TypeError, ValueError):
        return "DISCONNECTED"
    if last_success is None:
        return "DISCONNECTED"
    age = max(0.0, (_utc(now) - last_success).total_seconds())
    if age <= live_threshold_seconds:
        return "LIVE"
    if age <= disconnect_threshold_seconds:
        return "STALE"
    return "DISCONNECTED"


def configured_recovery_policy() -> dict[str, dict[str, Any]]:
    """Return the configured policy separately from observed directives."""

    return {
        "EVIDENCE_INCOMPLETE": {
            "decision": "RETRY_AFTER_EVIDENCE",
            "resume_condition": "evidence gap is supplied and a new attempt is created",
        },
        "WORKER_TIMEOUT": {
            "first_failure": "RETRY",
            "budget_exhausted": "HUMAN_TAKEOVER",
            "resume_condition": "same-role retry budget remains",
        },
        "CAPABILITY_MISSING": {
            "decision": "REASSIGN_OR_HUMAN_TAKEOVER",
            "resume_condition": "a real alternate Worker event and capability artifact exist",
        },
        "TOOL_FAILURE": {
            "decision": "BOUNDED_RETRY_OR_HUMAN_TAKEOVER",
            "resume_condition": "the operation is idempotent and explicitly safe to retry",
        },
        "POLICY_VIOLATION": {
            "decision": "ROLLBACK_REQUIRED",
            "resume_condition": "no automatic retry",
        },
        "AUDIT_INCONCLUSIVE": {
            "decision": "HUMAN_TAKEOVER",
            "resume_condition": "a human owner accepts and returns work to a non-terminal state",
        },
    }


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bounded_strings(value: object, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, str)]


def _timeline_event(
    kind: str,
    workflow_from: str,
    workflow_to: str,
    *,
    evidence_state: str = "CONFIGURED",
    source: str = "CONFIGURED",
    event_id: str | None = None,
    timestamp: str | None = None,
    actor: str | None = None,
    artifact_refs: object = None,
    hash_refs: object = None,
) -> dict[str, Any]:
    state = evidence_state if evidence_state in EVIDENCE_STATES else "OBSERVED"
    return {
        "kind": kind,
        "workflow_from": workflow_from,
        "workflow_to": workflow_to,
        "evidence_state": state,
        "source": source,
        "event_id": event_id if isinstance(event_id, str) else None,
        "timestamp": timestamp if isinstance(timestamp, str) else None,
        "actor": actor if isinstance(actor, str) else None,
        "artifact_refs": _bounded_strings(artifact_refs),
        "hash_refs": _bounded_strings(hash_refs),
    }


def _configured_timeline() -> list[dict[str, Any]]:
    return [
        _timeline_event(kind, workflow_from, workflow_to)
        for kind, workflow_from, workflow_to in EXPECTED_TIMELINE
    ]


def _archived_timeline(archived: dict[str, Any], verified: bool) -> list[dict[str, Any]]:
    timeline = _configured_timeline()
    if not verified:
        return timeline
    handoffs = archived.get("agentteams", {}).get("handoffs", [])
    handoffs = handoffs if isinstance(handoffs, list) else []

    def mark(kind: str, record: object, actor: str | None = None) -> None:
        if not isinstance(record, dict):
            return
        item = next(row for row in timeline if row["kind"] == kind)
        event_id = record.get("event_id")
        item.update({
            "source": "ARCHIVED_EVIDENCE",
            "evidence_state": "VERIFIED",
            "event_id": event_id if isinstance(event_id, str) and event_id.startswith("$") else None,
            "timestamp": record.get("source_event_time") if isinstance(record.get("source_event_time"), str) else None,
            "actor": actor,
            "artifact_refs": _bounded_strings([record.get("input"), record.get("output")]),
            "hash_refs": [],
        })

    if len(handoffs) > 0:
        mark("task_dispatched", handoffs[0], "labops-manager")
        mark("manager_to_collector", handoffs[0], "labops-manager")
        mark("evidence_collected", handoffs[0].get("completion"), "evidence-collector")
    if len(handoffs) > 1:
        mark("collector_to_rca", handoffs[1], "evidence-collector")
        mark("hypotheses_ranked", handoffs[1], "rca-analyst")
    if len(handoffs) > 2:
        mark("rca_to_planner", handoffs[2], "rca-analyst")
        mark("policy_passed", handoffs[2], "experiment-planner")
    human = archived.get("agentteams", {}).get("human_approval", {})
    mark("approval_granted", human, "human-approver")
    if len(handoffs) > 3:
        mark("runner_started", handoffs[3], "safe-executor")
        mark("runner_completed", handoffs[3], "safe-executor")
    if len(handoffs) > 4:
        mark("executor_to_auditor", handoffs[4], "safe-executor")
        mark("verification_completed", handoffs[4], "verification-auditor")
        mark("terminal_decided", handoffs[4], "verification-auditor")
    return timeline


def _live_timeline(matrix_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    by_kind: dict[str, dict[str, Any]] = {}
    events = matrix_snapshot.get("events", [])
    if isinstance(events, list):
        for item in events:
            if not isinstance(item, dict) or item.get("kind") not in EVENT_KINDS:
                continue
            kind = str(item["kind"])
            if kind in by_kind:
                continue
            expected = next(row for row in EXPECTED_TIMELINE if row[0] == kind)
            by_kind[kind] = _timeline_event(
                kind,
                str(item.get("workflow_from") or expected[1]),
                str(item.get("workflow_to") or expected[2]),
                evidence_state=str(item.get("evidence_state") or "OBSERVED"),
                source="MATRIX",
                event_id=item.get("event_id"),
                timestamp=item.get("timestamp"),
                actor=item.get("actor"),
                artifact_refs=item.get("artifact_refs"),
                hash_refs=item.get("hash_refs"),
            )
    return [
        by_kind.get(kind) or _timeline_event(kind, workflow_from, workflow_to)
        for kind, workflow_from, workflow_to in EXPECTED_TIMELINE
    ]


def _put_timeline_evidence(
    timeline: list[dict[str, Any]],
    kind: str,
    *,
    source: str,
    artifact_ref: str,
    actor: str | None = None,
    timestamp: str | None = None,
    verified: bool = False,
) -> None:
    item = next(row for row in timeline if row["kind"] == kind)
    if item["evidence_state"] in {"OBSERVED", "VERIFIED"}:
        return
    item.update({
        "source": source,
        "evidence_state": "VERIFIED" if verified else "OBSERVED",
        "actor": actor,
        "timestamp": timestamp,
        "artifact_refs": [artifact_ref],
    })


def _load_live_artifacts(
    session_root: Path,
    timeline: list[dict[str, Any]],
    verifier_status: str,
) -> dict[str, dict[str, Any]]:
    evidence = session_root / "evidence"
    approval = _read_object(evidence / "approval_grant.json")
    gateway = _read_object(evidence / "gateway_request.json")
    run = _read_object(evidence / "runner" / "run_result.json")
    verification = _read_object(evidence / "verification.json")
    is_verified = verifier_status == "VERIFIED"
    if approval:
        _put_timeline_evidence(
            timeline,
            "approval_granted",
            source="APPROVAL_ARTIFACT",
            artifact_ref="evidence/approval_grant.json",
            actor=str(approval.get("decided_by") or "human-approver"),
            timestamp=approval.get("approved_at"),
            verified=is_verified,
        )
    if gateway:
        _put_timeline_evidence(
            timeline,
            "executor_to_gateway",
            source="GATEWAY_ARCHIVE",
            artifact_ref="evidence/gateway_request.json",
            actor="safe-executor",
            verified=is_verified,
        )
    if run:
        _put_timeline_evidence(
            timeline,
            "runner_started",
            source="RUNNER_ARTIFACT",
            artifact_ref="evidence/runner/run_result.json",
            actor="safe-executor",
            timestamp=run.get("start_time"),
            verified=is_verified,
        )
        _put_timeline_evidence(
            timeline,
            "runner_completed",
            source="RUNNER_ARTIFACT",
            artifact_ref="evidence/runner/run_result.json",
            actor="safe-executor",
            timestamp=run.get("end_time"),
            verified=is_verified,
        )
    if verification:
        _put_timeline_evidence(
            timeline,
            "verification_completed",
            source="AUDITOR_ARTIFACT",
            artifact_ref="evidence/verification.json",
            actor=verification.get("verified_by"),
            timestamp=verification.get("verified_at"),
            verified=is_verified,
        )
        if verification.get("decision") in {"PASS", "POLICY_VIOLATION", "BLOCKED"}:
            _put_timeline_evidence(
                timeline,
                "terminal_decided",
                source="AUDITOR_ARTIFACT",
                artifact_ref="evidence/verification.json",
                actor=verification.get("verified_by"),
                timestamp=verification.get("verified_at"),
                verified=is_verified,
            )
    return {
        "approval": approval,
        "gateway": gateway,
        "run": run,
        "verification": verification,
    }


def _agent_nodes(timeline: list[dict[str, Any]], *, archived_verified: bool = False) -> list[dict[str, Any]]:
    nodes = {
        agent_id: {
            "agent_id": agent_id,
            "role_name": ROLE_NAMES[agent_id],
            "workflow_state": "NOT_STARTED",
            "evidence_state": "VERIFIED" if archived_verified else "CONFIGURED",
            "runtime_identity": agent_id,
        }
        for agent_id in ROLE_ORDER
    }
    if archived_verified:
        archived_states = {
            "labops-manager": "RESOLVED",
            "evidence-collector": "EVIDENCE_READY",
            "rca-analyst": "DIAGNOSIS_READY",
            "experiment-planner": "PLAN_READY",
            "safe-executor": "VERIFYING",
            "verification-auditor": "RESOLVED",
        }
        for agent_id, state in archived_states.items():
            nodes[agent_id]["workflow_state"] = state
        return [nodes[agent_id] for agent_id in ROLE_ORDER]

    for event in timeline:
        if event["evidence_state"] not in {"OBSERVED", "VERIFIED"}:
            continue
        progress = AGENT_PROGRESS.get(event["kind"])
        if not progress:
            continue
        agent_id, workflow_state = progress
        nodes[agent_id]["workflow_state"] = workflow_state
        nodes[agent_id]["evidence_state"] = event["evidence_state"]
    return [nodes[agent_id] for agent_id in ROLE_ORDER]


def _live_incident(manifest: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row for row in timeline if row["evidence_state"] in {"OBSERVED", "VERIFIED"}]
    last = observed[-1] if observed else None
    workflow_state = last["workflow_to"] if last else "RECEIVED"
    last_actor = last.get("actor") if last else "labops-manager"
    last_active = ROLE_NAMES.get(str(last_actor), "Incident Commander")
    current_owner = last_active
    if workflow_state == "APPROVAL_PENDING":
        current_owner = "Human Approver"
        last_active = "Experiment Planner"
    elif workflow_state == "APPROVED":
        current_owner = "Safe Executor"
    elif workflow_state == "VERIFYING":
        current_owner = "Verification Auditor"
    elif workflow_state in {"RESOLVED", "ROLLED_BACK", "BLOCKED"}:
        current_owner = "Incident Commander"
    return {
        "task_id": manifest.get("task_instance_id"),
        "incident_id": manifest.get("incident_instance_id"),
        "attempt_id": manifest.get("attempt_id"),
        "run_id": manifest.get("run_id"),
        "workflow_state": workflow_state,
        "current_owner": current_owner,
        "last_active_agent": last_active,
        "last_event": last.get("kind") if last else None,
        "last_event_at": last.get("timestamp") if last else None,
    }


def _recovery_projection(session_root: Path) -> dict[str, Any]:
    try:
        overlay = load_recovery_overlay(session_root)
    except RecoveryError as exc:
        return {
            "status": "BLOCKED",
            "current_directive": "NONE",
            "display": "BLOCKED",
            "resume_condition": None,
            "latest_attempt": None,
            "pending_takeover": None,
            "trace_status": "BLOCKED",
            "configured_policy": configured_recovery_policy(),
            "errors": [str(exc)],
        }
    decision = overlay.get("last_decision") or "NONE"
    pending = overlay.get("pending_takeover")
    if pending and decision == "NONE":
        decision = "HUMAN_TAKEOVER"
    attempts = overlay.get("attempts", [])
    latest = attempts[-1] if isinstance(attempts, list) and attempts else None
    display = "STOP / NO RETRY" if decision == "ROLLBACK_REQUIRED" else decision
    resume_condition = None
    if pending:
        resume_condition = "takeover owner accepts, handles the gap, then resumes at a non-terminal state"
    elif latest and latest.get("resume_point") != "RECEIVED":
        resume_condition = latest.get("resume_point")
    return {
        "status": "OBSERVED" if decision != "NONE" else "CONFIGURED",
        "current_directive": decision,
        "display": display,
        "resume_condition": resume_condition,
        "latest_attempt": latest,
        "pending_takeover": pending,
        "trace_status": overlay.get("recovery_trace", {}).get("status", "ABSENT"),
        "configured_policy": configured_recovery_policy(),
        "errors": [],
    }


def _short(value: object, length: int = 12) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value if len(value) <= length else value[:length] + "…"


def _skill_version(project_root: Path, skill_id: str) -> str | None:
    try:
        skill = next(item for item in list_skills(project_root) if item["skill_id"] == skill_id)
    except (StopIteration, OSError, ValueError):
        return None
    version = skill.get("version")
    return version if isinstance(version, str) else None


def _tool_contract_projection(
    project_root: Path,
    gateway_request: dict[str, Any],
    verifier: dict[str, Any],
) -> dict[str, Any]:
    contract = gateway_request.get("tool_contract")
    if not isinstance(contract, dict):
        return {
            "status": "NOT_OBSERVED",
            "skill": "control-lab-action@0.2.0",
            "caller": None,
            "tool_id": None,
            "plan_hash": None,
            "approval_binding": "NOT_OBSERVED",
            "protected_resource_count": 0,
            "resource_budget": {},
            "details": {},
        }
    skill_id = str(contract.get("skill_id") or "")
    version = _skill_version(project_root, skill_id)
    skill_status = (
        verifier.get("skill_runtime_evidence", {})
        .get("control-lab-action", {})
        .get("status")
    )
    runtime_verified = verifier.get("status") == "VERIFIED" and skill_status == "VERIFIED"
    approval = gateway_request.get("approval")
    approval = approval if isinstance(approval, dict) else {}
    plan = gateway_request.get("experiment_plan")
    plan = plan if isinstance(plan, dict) else {}
    canonical_hash = approval.get("canonical_plan_sha256")
    approval_binding = (
        gateway_request.get("approval_binding", {}).get("status", "NOT_OBSERVED")
        if isinstance(gateway_request.get("approval_binding"), dict)
        else "NOT_OBSERVED"
    )
    binding_errors = []
    expected_identities = {
        "tool_id": "labops.runner.execute",
        "caller_agent_id": "safe-executor",
        "skill_id": "control-lab-action",
        "task_id": plan.get("task_id"),
        "incident_id": plan.get("incident_id"),
        "run_id": plan.get("run_id"),
        "approval_reference": approval.get("approval_id"),
    }
    for field, expected in expected_identities.items():
        if not isinstance(expected, str) or not expected or contract.get(field) != expected:
            binding_errors.append(field)
    if approval_binding != "VALID":
        binding_errors.append("approval_binding")
    if not isinstance(canonical_hash, str) or len(canonical_hash) != 64:
        binding_errors.append("canonical_plan_sha256")
    protected = _bounded_strings(contract.get("protected_resources"), 64)
    details = {
        "task_id": contract.get("task_id"),
        "incident_id": contract.get("incident_id"),
        "plan_id": plan.get("plan_id"),
        "run_id": contract.get("run_id"),
        "approval_reference": contract.get("approval_reference"),
        "canonical_plan_sha256": canonical_hash,
        "protected_resources": protected,
        "allowed_side_effects": _bounded_strings(contract.get("allowed_side_effects"), 64),
        "resource_budget": contract.get("resource_budget") if isinstance(contract.get("resource_budget"), dict) else {},
        "idempotency_key": contract.get("idempotency_key"),
        "binding_errors": binding_errors,
    }
    return {
        "status": "BLOCKED" if binding_errors else ("VERIFIED" if runtime_verified else "CONFIGURED"),
        "skill": f"{skill_id}@{version}" if version else skill_id,
        "caller": contract.get("caller_agent_id"),
        "tool_id": contract.get("tool_id"),
        "plan_hash": _short(canonical_hash),
        "approval_binding": approval_binding,
        "protected_resource_count": len(protected),
        "resource_budget": details["resource_budget"],
        "details": details,
    }


def _quick_state(project_root: Path, now: datetime) -> dict[str, Any]:
    from labops.web import build_at004_state

    at004_root = project_root / "demo" / "output-agentteams-at004"
    archived = build_at004_state(at004_root)
    verified = bool(
        archived.get("ready")
        and archived.get("status") == "PASS"
        and archived.get("resolution_status") == "RESOLVED"
        and archived.get("integrity", {}).get("trace_ok") is True
        and archived.get("bundle", {}).get("artifact_hashes_ok") is True
    )
    timeline = _archived_timeline(archived, verified)
    archive_state = "VERIFIED" if verified else "BLOCKED"
    run = archived.get("runs", [{}])[0] if archived.get("runs") else {}
    approval = archived.get("approval", {})
    return {
        "schema_version": "1.0",
        "mode": "QUICK",
        "read_only": True,
        "source_summary": "REPLAY",
        "sources": {
            "archived_evidence": {
                "status": archive_state,
                "source": "demo/output-agentteams-at004",
                "freshness_mode": "IMMUTABLE_ARCHIVE",
            }
        },
        "session": {
            "classification": "ARCHIVED_VERIFIED_RUN",
            "session_id": None,
        },
        "incident": {
            "task_id": archived.get("task_id"),
            "incident_id": archived.get("incident_id"),
            "attempt_id": None,
            "run_id": run.get("run_id"),
            "workflow_state": "RESOLVED" if verified else "BLOCKED",
            "current_owner": "Incident Commander",
            "last_active_agent": "Incident Commander",
            "last_event": "commander_published" if verified else None,
            "last_event_at": None,
        },
        "agents": _agent_nodes(timeline, archived_verified=verified),
        "approval": {
            "status": "VERIFIED" if verified and approval.get("before_execution") else "BLOCKED",
            "decision": approval.get("decision"),
            "decided_by": approval.get("decided_by"),
            "approval_id": approval.get("approval_id"),
        },
        "timeline": timeline,
        "tool_contract": {
            "status": "CONFIGURED",
            "skill": "control-lab-action@0.2.0",
            "caller": "safe-executor",
            "tool_id": "labops.runner.execute",
            "plan_hash": None,
            "approval_binding": "HISTORICAL_CONTRACT",
            "protected_resource_count": len(archived.get("plan", {}).get("forbidden_changes", [])),
            "resource_budget": archived.get("plan", {}).get("budget", {}),
            "details": {
                "run_id": run.get("run_id"),
                "protected_resources": archived.get("plan", {}).get("forbidden_changes", []),
            },
        },
        "recovery": {
            "status": "CONFIGURED",
            "current_directive": "NONE",
            "display": "NONE",
            "resume_condition": None,
            "latest_attempt": None,
            "pending_takeover": None,
            "trace_status": "ABSENT",
            "configured_policy": configured_recovery_policy(),
            "errors": [],
        },
        "runner": {
            "status": "VERIFIED" if verified and run.get("status") == "completed" else "BLOCKED",
            "run_id": run.get("run_id"),
            "network": run.get("network"),
            "sandbox_only": run.get("sandbox_only"),
        },
        "audit": {
            "status": "VERIFIED" if verified else "BLOCKED",
            "decision": archived.get("verification", {}).get("decision"),
            "resolution_status": archived.get("verification", {}).get("resolution_status"),
            "verified_by": archived.get("verification", {}).get("verified_by"),
        },
        "limitations": [
            "REPLAY is an immutable archived run, not a current AgentTeams execution.",
            "Historical AT-004 does not contain the newer per-Skill runtime event schema.",
        ],
        "updated_at": _iso(now),
    }


def _blocked_live_state(session_id: str | None, now: datetime, error: str) -> dict[str, Any]:
    timeline = _configured_timeline()
    return {
        "schema_version": "1.0",
        "mode": "LIVE",
        "read_only": True,
        "source_summary": "DISCONNECTED",
        "sources": {
            "matrix": {
                "status": "DISCONNECTED",
                "connected": False,
                "last_success_at": None,
                "live_threshold_seconds": 15,
                "disconnect_threshold_seconds": 60,
            }
        },
        "session": {"classification": "NON_FORMAL_LIVE_DEMO", "session_id": session_id},
        "incident": {
            "task_id": None,
            "incident_id": None,
            "attempt_id": None,
            "run_id": None,
            "workflow_state": "BLOCKED",
            "current_owner": "Incident Commander",
            "last_active_agent": "Incident Commander",
            "last_event": None,
            "last_event_at": None,
        },
        "agents": _agent_nodes(timeline),
        "approval": {"status": "NOT_OBSERVED", "decision": None},
        "timeline": timeline,
        "tool_contract": _tool_contract_projection(Path.cwd(), {}, {}),
        "recovery": {
            "status": "BLOCKED",
            "current_directive": "NONE",
            "display": "BLOCKED",
            "resume_condition": None,
            "latest_attempt": None,
            "pending_takeover": None,
            "trace_status": "BLOCKED",
            "configured_policy": configured_recovery_policy(),
            "errors": [error],
        },
        "runner": {"status": "NOT_OBSERVED", "run_id": None},
        "audit": {"status": "BLOCKED", "decision": None, "resolution_status": None},
        "limitations": [error],
        "updated_at": _iso(now),
    }


def build_reviewer_state(
    project_root: str | Path,
    sessions_root: str | Path,
    session_id: str | None,
    mode: str,
    matrix_snapshot: dict | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic read-only Reviewer Edition projection."""

    project = Path(project_root).resolve()
    sessions = Path(sessions_root).resolve()
    current_time = _utc(now or datetime.now(timezone.utc))
    normalized_mode = mode.lower()
    if normalized_mode not in {"quick", "live"}:
        raise ValueError("mode must be quick or live")
    if normalized_mode == "quick":
        return _quick_state(project, current_time)
    if not isinstance(session_id, str) or SESSION_ID.fullmatch(session_id) is None:
        return _blocked_live_state(session_id, current_time, "invalid or missing live session ID")
    session_root = (sessions / session_id).resolve()
    try:
        session_root.relative_to(sessions)
    except ValueError:
        return _blocked_live_state(session_id, current_time, "live session escapes the sessions root")
    manifest = _read_object(session_root / "session.json")
    if not manifest:
        return _blocked_live_state(session_id, current_time, "live session manifest is missing or invalid")

    snapshot = matrix_snapshot if isinstance(matrix_snapshot, dict) else {}
    matrix_status = classify_source_status(
        "live",
        snapshot.get("connected") is True,
        snapshot.get("last_success_at") if isinstance(snapshot.get("last_success_at"), str) else None,
        current_time,
    )
    verifier = verify_session(project, sessions, session_id)
    verifier_status = verifier.get("status") if isinstance(verifier, dict) else "BLOCKED"
    timeline = _live_timeline(snapshot)
    artifacts = _load_live_artifacts(session_root, timeline, str(verifier_status))
    agents = _agent_nodes(timeline)
    incident = _live_incident(manifest, timeline)
    if verifier_status == "VERIFIED":
        incident["workflow_state"] = "RESOLVED"
        incident["current_owner"] = "Incident Commander"
        incident["last_active_agent"] = "Verification Auditor"
        incident["last_event"] = "terminal_decided"
        for node in agents:
            if node["agent_id"] == "verification-auditor":
                node["workflow_state"] = "RESOLVED"
                node["evidence_state"] = "VERIFIED"

    if matrix_status == "LIVE":
        source_summary = "LIVE" if verifier_status == "VERIFIED" else "LIVE_PARTIAL"
    else:
        source_summary = matrix_status
    approval = artifacts["approval"]
    if approval:
        approval_status = "VERIFIED" if verifier_status == "VERIFIED" else "OBSERVED"
    elif incident["workflow_state"] == "APPROVAL_PENDING":
        approval_status = "WAITING"
    else:
        approval_status = "NOT_OBSERVED"
    gateway = artifacts["gateway"]
    run = artifacts["run"]
    verification = artifacts["verification"]
    state = {
        "schema_version": "1.0",
        "mode": "LIVE",
        "read_only": True,
        "source_summary": source_summary,
        "sources": {
            "matrix": {
                "status": matrix_status,
                "connected": snapshot.get("connected") is True,
                "last_success_at": snapshot.get("last_success_at"),
                "live_threshold_seconds": 15,
                "disconnect_threshold_seconds": 60,
            },
            "live_evidence": {
                "status": verifier_status,
                "evidence_digest": verifier.get("evidence_digest"),
            },
        },
        "session": {
            "classification": manifest.get("classification"),
            "session_id": manifest.get("session_id"),
        },
        "incident": incident,
        "agents": agents,
        "approval": {
            "status": approval_status,
            "decision": approval.get("decision"),
            "approval_id": approval.get("approval_id"),
            "decided_by": approval.get("decided_by"),
            "approved_at": approval.get("approved_at"),
        },
        "timeline": timeline,
        "tool_contract": _tool_contract_projection(project, gateway, verifier),
        "recovery": _recovery_projection(session_root),
        "runner": {
            "status": "VERIFIED" if verifier_status == "VERIFIED" else ("OBSERVED" if run else "NOT_OBSERVED"),
            "run_id": run.get("run_id"),
            "network": run.get("network"),
            "sandbox_only": run.get("sandbox_only"),
        },
        "audit": {
            "status": "VERIFIED" if verifier_status == "VERIFIED" else ("OBSERVED" if verification else "NOT_OBSERVED"),
            "decision": verification.get("decision"),
            "resolution_status": verification.get("resolution_status"),
            "verified_by": verification.get("verified_by"),
        },
        "limitations": list(verifier.get("errors", [])) if isinstance(verifier.get("errors"), list) else [],
        "updated_at": _iso(current_time),
    }
    return state
