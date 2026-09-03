"""Truth-preserving projection for the read-only Reviewer Edition.

This module never drives AgentTeams, approves plans, invokes tools, or changes
workflow state.  It combines configured contracts with allowlisted evidence and
keeps workflow progress separate from evidence confidence.
"""

from __future__ import annotations

import json
import math
import re
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
    ("terminal_decided", "VERIFYING", "DEMO_PASSED_NOT_RESOLVED"),
    (
        "commander_published",
        "DEMO_PASSED_NOT_RESOLVED",
        "DEMO_PASSED_NOT_RESOLVED",
    ),
]
EVENT_KINDS = {kind for kind, _, _ in EXPECTED_TIMELINE}
HANDOFF_EVENT_KINDS = {
    "manager_to_collector",
    "collector_to_rca",
    "rca_to_planner",
    "approval_pending",
    "executor_to_auditor",
    "verification_completed",
}
EVIDENCE_SYNC_STATUSES = {"NOT_APPLICABLE", "NOT_STARTED", "MIRRORED", "VERIFIED", "BLOCKED"}
EVIDENCE_SYNC_ERRORS = {
    "EVIDENCE_SOURCE_UNAVAILABLE",
    "EVIDENCE_SNAPSHOT_TOO_LARGE",
    "EVIDENCE_PATH_REJECTED",
    "EVIDENCE_BINDING_MISMATCH",
    "EVIDENCE_SCHEMA_INVALID",
    "EVIDENCE_HASH_CONFLICT",
    "EVIDENCE_INCOMPLETE",
}
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
    "terminal_decided": ("verification-auditor", "DEMO_PASSED_NOT_RESOLVED"),
    "commander_published": ("labops-manager", "DEMO_PASSED_NOT_RESOLVED"),
}
VERIFIED_HANDOFF_PROGRESS = {
    "evidence-collector": "EVIDENCE_READY",
    "rca-analyst": "DIAGNOSIS_READY",
    "experiment-planner": "PLAN_READY",
    "safe-executor": "VERIFYING",
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


def _reset_timeline_evidence(timeline: list[dict[str, Any]], kind: str) -> None:
    expected = next(row for row in EXPECTED_TIMELINE if row[0] == kind)
    item = next(row for row in timeline if row["kind"] == kind)
    item.clear()
    item.update(_timeline_event(*expected))


def _timestamp_is_strictly_later(later: object, earlier: object) -> bool:
    if not isinstance(later, str) or not isinstance(earlier, str):
        return False
    try:
        later_at = _parse_utc(later)
        earlier_at = _parse_utc(earlier)
    except (TypeError, ValueError):
        return False
    return later_at is not None and earlier_at is not None and later_at > earlier_at


def _archived_timeline(archived: dict[str, Any], verified: bool) -> list[dict[str, Any]]:
    timeline = _configured_timeline()
    if not verified:
        return timeline
    terminal = next(row for row in timeline if row["kind"] == "terminal_decided")
    terminal["workflow_to"] = "RESOLVED"
    published = next(row for row in timeline if row["kind"] == "commander_published")
    published["workflow_from"] = "RESOLVED"
    published["workflow_to"] = "RESOLVED"
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


def _live_timeline(
    matrix_snapshot: dict[str, Any],
    preferred_attempt_id: str | None = None,
) -> list[dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    events = matrix_snapshot.get("events", [])
    if isinstance(events, list):
        for item in events:
            if not isinstance(item, dict) or item.get("kind") not in EVENT_KINDS:
                continue
            kind = str(item["kind"])
            candidates.setdefault(kind, []).append(item)
    by_kind: dict[str, dict[str, Any]] = {}
    for kind, items in candidates.items():
        current_attempt = [
            item for item in items
            if preferred_attempt_id and item.get("attempt_id") == preferred_attempt_id
        ]
        selected = max(
            current_attempt or items,
            key=lambda item: str(item.get("timestamp") or ""),
        )
        expected = next(row for row in EXPECTED_TIMELINE if row[0] == kind)
        by_kind[kind] = _timeline_event(
                kind,
                str(selected.get("workflow_from") or expected[1]),
                str(selected.get("workflow_to") or expected[2]),
                evidence_state=str(selected.get("evidence_state") or "OBSERVED"),
                source="MATRIX",
                event_id=selected.get("event_id"),
                timestamp=selected.get("timestamp"),
                actor=selected.get("actor"),
                artifact_refs=selected.get("artifact_refs"),
                hash_refs=selected.get("hash_refs"),
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
    if item["evidence_state"] == "VERIFIED":
        return
    if item["evidence_state"] == "OBSERVED" and not verified:
        return
    artifact_refs = _bounded_strings(
        list(item.get("artifact_refs") or []) + [artifact_ref]
    )
    item.update({
        "source": source,
        "evidence_state": "VERIFIED" if verified else "OBSERVED",
        "actor": actor or item.get("actor"),
        "timestamp": timestamp or item.get("timestamp"),
        "artifact_refs": artifact_refs,
    })


def _apply_verified_handoffs(
    timeline: list[dict[str, Any]],
    handoff_manifest: dict[str, Any],
    matrix_evidence: dict[str, Any],
) -> set[str]:
    handoffs = handoff_manifest.get("handoffs")
    events = matrix_evidence.get("events")
    if not isinstance(handoffs, list) or not isinstance(events, list):
        return set()
    event_map = {
        item.get("event_id"): item
        for item in events
        if isinstance(item, dict) and isinstance(item.get("event_id"), str)
    }
    timeline_kinds = {
        1: ("task_dispatched", "manager_to_collector"),
        2: ("collector_to_rca",),
        3: ("hypotheses_ranked", "rca_to_planner"),
        4: ("approval_pending",),
        5: ("executor_to_auditor",),
        6: ("verification_completed",),
    }
    verified_agents: set[str] = set()
    for index, item in enumerate(handoffs, 1):
        if not isinstance(item, dict) or item.get("status") not in {"COMPLETED", "VALID", "PASS"}:
            continue
        actor = item.get("from_agent")
        event_id = item.get("matrix_event_id")
        handoff_number = item.get("handoff", index)
        event = event_map.get(event_id)
        if (
            not isinstance(actor, str)
            or actor not in ROLE_NAMES
            or not isinstance(event, dict)
            or event.get("sender_agent") != actor
        ):
            continue
        verified_agents.add(actor)
        artifact_refs = _bounded_strings(
            list(item.get("input_artifact_refs") or [])
            + list(item.get("output_artifact_refs") or [])
        )
        for kind in timeline_kinds.get(handoff_number, ()):
            row = next(candidate for candidate in timeline if candidate["kind"] == kind)
            row.update({
                "source": "VERIFIED_HANDOFF_MANIFEST",
                "evidence_state": "VERIFIED",
                "event_id": event_id,
                "timestamp": event.get("timestamp"),
                "actor": actor,
                "artifact_refs": artifact_refs,
            })
    return verified_agents


def _verification_terminal_state(verification: dict[str, Any]) -> str | None:
    incident_state = verification.get("incident_state")
    if incident_state == "DEMO_PASSED_NOT_RESOLVED":
        return incident_state
    resolution_status = verification.get("resolution_status")
    if resolution_status in {"RESOLVED", "ROLLED_BACK", "BLOCKED"}:
        return resolution_status
    return None


def _gate_live_terminal_events(
    timeline: list[dict[str, Any]],
    verification: dict[str, Any],
    verifier_status: str,
) -> None:
    terminal = next(row for row in timeline if row["kind"] == "terminal_decided")
    published = next(row for row in timeline if row["kind"] == "commander_published")
    terminal_state = _verification_terminal_state(verification)
    terminal_valid = (
        verifier_status == "VERIFIED"
        and terminal_state is not None
        and verification.get("decision") in {"PASS", "POLICY_VIOLATION", "BLOCKED"}
        and terminal["evidence_state"] == "VERIFIED"
    )
    if not terminal_valid:
        _reset_timeline_evidence(timeline, "terminal_decided")
        _reset_timeline_evidence(timeline, "commander_published")
        return

    terminal["workflow_to"] = terminal_state
    published["workflow_from"] = terminal_state
    published["workflow_to"] = terminal_state
    publication_valid = (
        published["evidence_state"] in {"OBSERVED", "VERIFIED"}
        and published.get("actor") == "labops-manager"
        and _timestamp_is_strictly_later(
            published.get("timestamp"), terminal.get("timestamp")
        )
    )
    if not publication_valid:
        _reset_timeline_evidence(timeline, "commander_published")
        return
    published["evidence_state"] = "VERIFIED"


def _empty_runner_outcome() -> dict[str, Any]:
    return {
        "baseline_accuracy": None,
        "candidate_accuracy": None,
        "baseline_repeats": None,
        "candidate_repeats": None,
        "minimum_accuracy": None,
        "accuracy_improvement": None,
        "changed_paths": [],
        "protected_hashes_unchanged": None,
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _matching_number(
    label: str,
    values: list[object],
    conflicts: list[str],
) -> float | None:
    observed = [number for value in values if (number := _number(value)) is not None]
    if not observed:
        return None
    if any(not math.isclose(observed[0], item, rel_tol=1e-9, abs_tol=1e-12) for item in observed[1:]):
        conflicts.append(label)
        return None
    return observed[0]


def _repeat_count(
    label: str,
    values: list[object],
    conflicts: list[str],
) -> int | None:
    observed: list[list[float]] = []
    for value in values:
        if not isinstance(value, list) or not value:
            continue
        numbers = [_number(item) for item in value]
        if any(item is None for item in numbers):
            conflicts.append(label)
            return None
        observed.append([float(item) for item in numbers if item is not None])
    if not observed:
        return None
    reference = observed[0]
    for candidate in observed[1:]:
        if len(candidate) != len(reference) or any(
            not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)
            for left, right in zip(reference, candidate)
        ):
            conflicts.append(label)
            return None
    return len(reference)


def _minimum_accuracy(success: dict[str, Any], conflicts: list[str]) -> float | None:
    candidates: list[object] = [success.get("minimum_accuracy")]
    for key, value in success.items():
        match = re.fullmatch(r"accuracy_ge_([0-9]+(?:\.[0-9]+)?)", key)
        if match and value is True:
            candidates.append(float(match.group(1)))
    return _matching_number("minimum_accuracy", candidates, conflicts)


def _matching_paths(
    run: dict[str, Any],
    boundaries: dict[str, Any],
    conflicts: list[str],
) -> list[str]:
    observed: list[list[str]] = []
    for value in (run.get("changed_paths"), boundaries.get("changed_paths")):
        if value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            conflicts.append("changed_paths")
            return []
        observed.append(value[:16])
    if not observed:
        return []
    if any(candidate != observed[0] for candidate in observed[1:]):
        conflicts.append("changed_paths")
        return []
    return observed[0]


def _protected_hash_state(
    run: dict[str, Any],
    protected_check: dict[str, Any],
    conflicts: list[str],
) -> bool | None:
    candidates: list[bool] = []
    protected = run.get("protected_hashes")
    if isinstance(protected, dict):
        flags = [value for key, value in protected.items() if key.endswith("_unchanged")]
        if flags:
            if any(not isinstance(value, bool) for value in flags):
                conflicts.append("protected_hashes_unchanged")
                return None
            candidates.append(all(flags))
    for key in ("pass", "all_unchanged_flags_true"):
        value = protected_check.get(key)
        if isinstance(value, bool):
            candidates.append(value)
    if not candidates:
        return None
    if any(value != candidates[0] for value in candidates[1:]):
        conflicts.append("protected_hashes_unchanged")
        return None
    return candidates[0]


def _runner_outcome_projection(
    run: dict[str, Any],
    metrics: dict[str, Any],
    verification: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    outcome = _empty_runner_outcome()
    conflicts: list[str] = []
    run_metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    checks = verification.get("checks") if isinstance(verification.get("checks"), dict) else {}
    recomputed = (
        checks.get("metrics_recomputed_from_raw_stdout")
        if isinstance(checks.get("metrics_recomputed_from_raw_stdout"), dict)
        else {}
    )
    success = checks.get("success_criteria_met") if isinstance(checks.get("success_criteria_met"), dict) else {}
    boundaries = checks.get("boundaries_respected") if isinstance(checks.get("boundaries_respected"), dict) else {}
    protected_check = (
        checks.get("protected_hashes_immutable")
        if isinstance(checks.get("protected_hashes_immutable"), dict)
        else {}
    )

    baseline = _matching_number(
        "baseline_accuracy",
        [metrics.get("baseline_accuracy"), run_metrics.get("baseline_accuracy"), recomputed.get("baseline_accuracy")],
        conflicts,
    )
    candidate = _matching_number(
        "candidate_accuracy",
        [
            metrics.get("candidate_accuracy"),
            run_metrics.get("candidate_accuracy"),
            recomputed.get("candidate_accuracy"),
            success.get("candidate_accuracy"),
        ],
        conflicts,
    )
    outcome["baseline_accuracy"] = baseline
    outcome["candidate_accuracy"] = candidate
    outcome["baseline_repeats"] = _repeat_count(
        "baseline_repeats",
        [
            metrics.get("baseline_accuracy_values"),
            run_metrics.get("baseline_accuracy_values"),
            recomputed.get("baseline_repeats"),
        ],
        conflicts,
    )
    outcome["candidate_repeats"] = _repeat_count(
        "candidate_repeats",
        [
            metrics.get("candidate_accuracy_values"),
            run_metrics.get("candidate_accuracy_values"),
            recomputed.get("candidate_repeats"),
        ],
        conflicts,
    )
    outcome["minimum_accuracy"] = _minimum_accuracy(success, conflicts)

    if baseline is not None and candidate is not None:
        computed_improvement = candidate - baseline
        improvement = _matching_number(
            "accuracy_improvement",
            [computed_improvement, recomputed.get("improvement"), success.get("improvement")],
            conflicts,
        )
        outcome["accuracy_improvement"] = improvement
    outcome["changed_paths"] = _matching_paths(run, boundaries, conflicts)
    outcome["protected_hashes_unchanged"] = _protected_hash_state(
        run, protected_check, conflicts,
    )

    limitations = [f"RUNNER_OUTCOME_CONFLICT: {', '.join(dict.fromkeys(conflicts))}"] if conflicts else []
    return outcome, limitations


def _load_live_artifacts(
    session_root: Path,
    timeline: list[dict[str, Any]],
    verifier_status: str,
) -> dict[str, Any]:
    evidence = session_root / "evidence"
    approval = _read_object(evidence / "approval_grant.json")
    gateway = _read_object(evidence / "gateway_request.json")
    run = _read_object(evidence / "runner" / "run_result.json")
    metrics = _read_object(evidence / "runner" / "metrics.json")
    verification = _read_object(evidence / "verification.json")
    handoff_manifest = _read_object(evidence / "handoff_manifest.json")
    matrix_evidence = _read_object(evidence / "matrix_events.json")
    is_verified = verifier_status == "VERIFIED"
    verified_handoff_agents = (
        _apply_verified_handoffs(timeline, handoff_manifest, matrix_evidence)
        if is_verified
        else set()
    )
    terminal_state = _verification_terminal_state(verification)
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
        if (
            is_verified
            and terminal_state is not None
            and verification.get("decision") in {"PASS", "POLICY_VIOLATION", "BLOCKED"}
        ):
            _put_timeline_evidence(
                timeline,
                "terminal_decided",
                source="AUDITOR_ARTIFACT",
                artifact_ref="evidence/verification.json",
                actor=verification.get("verified_by"),
                timestamp=verification.get("verified_at"),
                verified=is_verified,
            )
    _gate_live_terminal_events(timeline, verification, verifier_status)
    return {
        "approval": approval,
        "gateway": gateway,
        "run": run,
        "metrics": metrics,
        "verification": verification,
        "handoff_manifest": handoff_manifest,
        "verified_handoff_agents": verified_handoff_agents,
    }


def _agent_nodes(
    timeline: list[dict[str, Any]],
    *,
    archived_verified: bool = False,
    verified_agents: set[str] | None = None,
) -> list[dict[str, Any]]:
    nodes = {
        agent_id: {
            "agent_id": agent_id,
            "role_name": ROLE_NAMES[agent_id],
            "workflow_state": "NOT_STARTED",
            "evidence_state": "VERIFIED" if archived_verified else "CONFIGURED",
            "confidence_state": "VERIFIED" if archived_verified else "CONFIGURED",
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
        if event["kind"] == "terminal_decided":
            workflow_state = event["workflow_to"]
        elif event["kind"] == "commander_published":
            workflow_state = "RESULT_PUBLISHED"
        nodes[agent_id]["workflow_state"] = workflow_state
        nodes[agent_id]["evidence_state"] = event["evidence_state"]
    for agent_id in verified_agents or set():
        if agent_id in nodes:
            nodes[agent_id]["evidence_state"] = "VERIFIED"
            if nodes[agent_id]["workflow_state"] == "NOT_STARTED":
                nodes[agent_id]["workflow_state"] = VERIFIED_HANDOFF_PROGRESS.get(
                    agent_id, "NOT_STARTED"
                )
    for node in nodes.values():
        node["confidence_state"] = node["evidence_state"]
    return [nodes[agent_id] for agent_id in ROLE_ORDER]


def _evidence_sync_projection(session_root: Path, verifier_status: str) -> dict[str, Any]:
    if verifier_status == "VERIFIED":
        inferred = {
            "status": "VERIFIED",
            "published": True,
            "errors": [],
            "mirror_digest": None,
            "checked_at": None,
        }
    else:
        inferred = {
            "status": "NOT_STARTED",
            "published": False,
            "errors": [],
            "mirror_digest": None,
            "checked_at": None,
        }
    path = session_root / "observer" / "evidence_sync.json"
    if not path.exists():
        return inferred
    record = _read_object(path)
    if not record:
        return {
            **inferred,
            "status": "BLOCKED",
            "published": False,
            "errors": ["EVIDENCE_SCHEMA_INVALID"],
        }
    status = record.get("status")
    errors = record.get("errors")
    if status not in EVIDENCE_SYNC_STATUSES or not isinstance(errors, list):
        return {
            **inferred,
            "status": "BLOCKED",
            "published": False,
            "errors": ["EVIDENCE_SCHEMA_INVALID"],
        }
    safe_errors = [
        item for item in errors
        if isinstance(item, str) and item in EVIDENCE_SYNC_ERRORS
    ][:8]
    digest = record.get("mirror_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        digest = None
    checked_at = record.get("checked_at")
    return {
        "status": "VERIFIED" if verifier_status == "VERIFIED" else status,
        "published": verifier_status == "VERIFIED" or record.get("published") is True,
        "errors": [] if verifier_status == "VERIFIED" else safe_errors,
        "mirror_digest": digest,
        "checked_at": checked_at if isinstance(checked_at, str) else None,
    }


def _live_incident(
    manifest: dict[str, Any],
    timeline: list[dict[str, Any]],
    effective_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    binding = effective_binding or manifest
    return {
        "task_id": manifest.get("task_instance_id"),
        "incident_id": manifest.get("incident_instance_id"),
        "attempt_id": binding.get("attempt_id"),
        "run_id": binding.get("run_id"),
        "workflow_state": workflow_state,
        "current_owner": current_owner,
        "last_active_agent": last_active,
        "last_event": last.get("kind") if last else None,
        "last_event_at": last.get("timestamp") if last else None,
    }


def _effective_live_binding(
    manifest: dict[str, Any],
    recovery: dict[str, Any],
    verification: dict[str, Any],
    verifier: dict[str, Any],
) -> dict[str, Any]:
    binding = {
        "attempt_id": manifest.get("attempt_id"),
        "run_id": manifest.get("run_id"),
    }
    latest = recovery.get("latest_attempt")
    if recovery.get("status") != "BLOCKED" and isinstance(latest, dict):
        if isinstance(latest.get("attempt_id"), str):
            binding["attempt_id"] = latest["attempt_id"]
        if isinstance(latest.get("run_id"), str):
            binding["run_id"] = latest["run_id"]
    if (
        verifier.get("status") == "VERIFIED"
        and verification.get("attempt_id") == verifier.get("effective_attempt_id")
        and isinstance(verification.get("run_id"), str)
    ):
        binding["attempt_id"] = verification["attempt_id"]
        binding["run_id"] = verification["run_id"]
    return binding


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
    latest = (
        attempts[-1]
        if isinstance(attempts, list) and len(attempts) > 1
        else None
    )
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
        "handoffs": {
            "observed": 6 if verified else 0,
            "verified": 6 if verified else 0,
            "total": 6,
        },
        "evidence_sync": {
            "status": "NOT_APPLICABLE",
            "published": False,
            "errors": [],
            "mirror_digest": None,
            "checked_at": None,
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
            **_empty_runner_outcome(),
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
        "handoffs": {"observed": 0, "verified": 0, "total": 6},
        "evidence_sync": {
            "status": "NOT_STARTED",
            "published": False,
            "errors": [],
            "mirror_digest": None,
            "checked_at": None,
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
        "runner": {
            "status": "NOT_OBSERVED",
            "run_id": None,
            "network": None,
            "sandbox_only": None,
            **_empty_runner_outcome(),
        },
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
    recovery = _recovery_projection(session_root)
    latest_attempt = recovery.get("latest_attempt")
    preferred_attempt_id = (
        latest_attempt.get("attempt_id")
        if isinstance(latest_attempt, dict) and isinstance(latest_attempt.get("attempt_id"), str)
        else None
    )
    timeline = _live_timeline(snapshot, preferred_attempt_id)
    artifacts = _load_live_artifacts(session_root, timeline, str(verifier_status))
    verification = artifacts["verification"]
    effective_binding = _effective_live_binding(manifest, recovery, verification, verifier)
    agents = _agent_nodes(
        timeline,
        verified_agents=artifacts["verified_handoff_agents"],
    )
    observed_handoffs = len({
        row["kind"]
        for row in timeline
        if row["kind"] in HANDOFF_EVENT_KINDS
        and row["evidence_state"] in {"OBSERVED", "VERIFIED"}
    })
    verified_handoffs = len(artifacts["verified_handoff_agents"])
    evidence_sync = _evidence_sync_projection(session_root, str(verifier_status))
    incident = _live_incident(manifest, timeline, effective_binding)
    terminal_state = _verification_terminal_state(verification)
    terminal = next(row for row in timeline if row["kind"] == "terminal_decided")
    terminal_verified = (
        verifier_status == "VERIFIED"
        and terminal_state is not None
        and terminal["evidence_state"] == "VERIFIED"
    )
    if terminal_verified:
        incident["current_owner"] = "Incident Commander"
        incident["last_active_agent"] = "Verification Auditor"
        published = next(row for row in timeline if row["kind"] == "commander_published")
        last = published if published["evidence_state"] == "VERIFIED" else terminal
        incident["last_event"] = last["kind"]
        incident["last_event_at"] = last.get("timestamp")
        incident["workflow_state"] = terminal_state
        for node in agents:
            if node["agent_id"] == "verification-auditor":
                node["evidence_state"] = "VERIFIED"
                node["workflow_state"] = (
                    "AUDIT_PASSED"
                    if verification.get("decision") == "PASS"
                    else terminal_state
                )

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
    runner_outcome, runner_limitations = _runner_outcome_projection(
        run,
        artifacts["metrics"],
        verification,
    )
    verifier_limitations = (
        list(verifier.get("errors", []))
        if isinstance(verifier.get("errors"), list)
        else []
    )
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
        "handoffs": {
            "observed": observed_handoffs,
            "verified": verified_handoffs,
            "total": 6,
        },
        "evidence_sync": evidence_sync,
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
        "recovery": recovery,
        "runner": {
            "status": "VERIFIED" if verifier_status == "VERIFIED" else ("OBSERVED" if run else "NOT_OBSERVED"),
            "run_id": run.get("run_id"),
            "network": run.get("network"),
            "sandbox_only": run.get("sandbox_only"),
            **runner_outcome,
        },
        "audit": {
            "status": "VERIFIED" if verifier_status == "VERIFIED" else ("OBSERVED" if verification else "NOT_OBSERVED"),
            "decision": verification.get("decision"),
            "resolution_status": verification.get("resolution_status") or verification.get("incident_state"),
            "verified_by": verification.get("verified_by"),
        },
        "limitations": verifier_limitations + runner_limitations,
        "updated_at": _iso(current_time),
    }
    return state
