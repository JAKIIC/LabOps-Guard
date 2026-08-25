"""Cross-layer Trust Contract validation and evidence-backed snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from labops.contracts import validate_document
from labops.skill_registry import list_skills


POSITIONING = "Trustworthy Agent Execution & Governance Infrastructure for AI Engineering"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_trust_contract(project_root: str | Path) -> list[str]:
    """Return deterministic cross-reference errors; an empty list is valid."""

    root = Path(project_root)
    errors: list[str] = []
    try:
        contract = _read(root / "agentteams" / "trust_contract_v1.json")
        validate_document(contract, "trust_contract.schema.json", root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"trust_contract: {exc}"]

    referenced = [
        "identity_source",
        "worker_aliases",
        "state_machine",
        "skill_registry",
        "tool_contract",
        "trust_snapshot",
    ]
    for field in referenced:
        value = contract.get(field)
        if not value or not (root / value).is_file():
            errors.append(f"{field}: missing {value}")

    if errors:
        return sorted(errors)

    identities = _read(root / contract["identity_source"])
    identity_ids = [item["agent_id"] for item in identities.get("agents", [])]
    active_ids = contract["active_agent_ids"]
    if identity_ids != active_ids:
        errors.append("identity_source: active Agent order or IDs differ")

    aliases = _read(root / contract["worker_aliases"]).get("aliases", {})
    if not set(aliases.values()).issubset(active_ids):
        errors.append("worker_aliases: alias target is not an active Agent")

    machine = _read(root / contract["state_machine"])
    allowed_actors = set(active_ids) | {"human-approver"}
    for transition in machine.get("transitions", []):
        if transition.get("actor") not in allowed_actors:
            errors.append(f"state_machine: unknown actor {transition.get('actor')}")
        if transition.get("to") in {"RESOLVED", "ROLLED_BACK", "BLOCKED"} and transition.get("actor") != contract["terminal_authority"]:
            errors.append(f"state_machine: {transition.get('to')} is not Auditor-owned")

    try:
        skills = list_skills(root)
    except ValueError as exc:
        errors.append(f"skill_registry: {exc}")
        skills = []
    for skill in skills:
        unknown = set(skill["owner_agents"]) - set(active_ids)
        if unknown:
            errors.append(f"skill_registry: {skill['skill_id']} has unknown owners")

    task = _read(root / "agentteams" / "tasks" / "LABOPS-AT-004-EVAL-DRIFT.json")
    if task.get("assigned_agents") != active_ids:
        errors.append("AT-004 task: assigned_agents are not canonical")
    if task.get("state_machine") != contract["state_machine"]:
        errors.append("AT-004 task: state machine is not canonical")
    return sorted(set(errors))


def _domain(
    status: str,
    summary: str,
    checks: dict[str, bool],
    evidence_refs: list[str],
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "checks": checks,
        "evidence_refs": evidence_refs,
        "limitations": limitations or [],
    }


def build_trust_snapshot(
    project_root: str | Path,
    at004_root: str | Path,
    at002_root: str | Path,
) -> dict[str, Any]:
    """Build a deterministic, public-safe Trust Layer projection."""

    root = Path(project_root)
    contract_errors = validate_trust_contract(root)
    identities = _read(root / "agentteams" / "agent_identities_v2.json")
    skills = list_skills(root)

    from labops.web import build_agentteams_v2_state, build_at004_state

    at004 = build_at004_state(at004_root)
    at002 = build_agentteams_v2_state(at002_root)
    ready = at004.get("ready") is True
    run = at004.get("runs", [{}])[0] if ready else {}
    unsafe = at002.get("unsafe_case", {}) if at002.get("ready") else {}

    execution_checks = {
        "approved_before_execution": bool(run.get("approval_before_execution")),
        "network_disabled": run.get("network") == "none",
        "sandbox_only": run.get("sandbox_only") is True,
        "protected_hashes": run.get("protected_hashes_ok") is True,
    }
    evidence_checks = {
        "bundle_hash": at004.get("bundle", {}).get("sha256")
        == "4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd",
        "artifact_count": at004.get("bundle", {}).get("artifact_count") == 27,
        "trace_chain": at004.get("trace", {}).get("ok") is True,
    }
    audit_checks = {
        "independent_pass": at004.get("status") == "PASS",
        "resolved": at004.get("resolution_status") == "RESOLVED",
        "unsafe_action_detected": unsafe.get("decision") == "POLICY_VIOLATION",
        "rollback_verified": unsafe.get("rollback_ok") is True,
    }

    domains = {
        "identity": _domain(
            "CONFIGURED" if not contract_errors else "BLOCKED",
            f"{len(identities.get('agents', []))} policy-backed Agent identities",
            {"six_distinct_agents": len(identities.get("agents", [])) == 6, "cross_references_valid": not contract_errors},
            ["agentteams/agent_identities_v2.json", "agentteams/worker_aliases.json"],
            ["Policy identity; no mTLS/OIDC workload identity"],
        ),
        "skills": _domain(
            "CONFIGURED" if len(skills) == 7 and not contract_errors else "BLOCKED",
            f"{len(skills)} versioned repository-native Skills",
            {"seven_registered": len(skills) == 7, "owners_resolve": not contract_errors},
            ["skills/registry.json"],
            ["Registry provides discovery and validation, not a remote marketplace"],
        ),
        "policy": _domain(
            "VERIFIED" if ready and unsafe.get("decision") == "POLICY_VIOLATION" else "BLOCKED",
            "Human approval gates legal action; protected metric tampering is rejected",
            {"approval_before_run": bool(run.get("approval_before_execution")), "unsafe_branch_blocked": unsafe.get("decision") == "POLICY_VIOLATION"},
            ["AT-004 approval.json", "AT-002 policy rejection and rollback"],
        ),
        "execution": _domain(
            "VERIFIED" if ready and all(execution_checks.values()) else "BLOCKED",
            "Allowlisted offline Runner with sandbox and resource boundaries",
            execution_checks,
            ["AT-004 run_result.json", "AT-004 artifact_manifest.json"],
            ["Single-host deterministic CPU runtime"],
        ),
        "evidence": _domain(
            "VERIFIED" if ready and all(evidence_checks.values()) else "BLOCKED",
            "Hash-chained Trace and 27-member Evidence Bundle",
            evidence_checks,
            ["AT-004 evidence bundle", "AT-004 agentteams_trace.jsonl"],
        ),
        "audit": _domain(
            "VERIFIED" if ready and all(audit_checks.values()) else "BLOCKED",
            "Independent Auditor owns closure and rollback decisions",
            audit_checks,
            ["AT-004 verification.json", "AT-002 rollback.json"],
        ),
    }
    snapshot = {
        "schema_version": "1.0",
        "positioning": POSITIONING,
        "contract_status": "CONFIGURED" if not contract_errors else "BLOCKED",
        "domains": domains,
    }
    validate_document(snapshot, "trust_snapshot.schema.json", root)
    return snapshot
