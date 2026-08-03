"""Local-only dashboard for LabOps Guard.

The server uses only Python's standard library and exposes read-only demo state.
It never serves arbitrary files from the workspace and never reads excluded data.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from labops.trace import TraceLog


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _counts(records: list[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        value = str(record.get(key, "UNKNOWN"))
        result[value] = result.get(value, 0) + 1
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_trace_bytes(data: bytes) -> dict:
    """Verify a non-empty TraceLog-compatible JSONL payload without extracting it."""
    try:
        records = [json.loads(line) for line in data.decode("utf-8").splitlines() if line]
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "entries": 0, "message": f"trace unreadable: {exc}"}
    if not records:
        return {"ok": False, "entries": 0, "message": "empty trace is not evidence"}
    previous_hash = None
    for record in records:
        if record.get("prev_hash") != previous_hash:
            return {"ok": False, "entries": len(records), "message": f"chain break at seq={record.get('seq')}"}
        canonical = json.dumps({k: v for k, v in record.items() if k != "hash"}, ensure_ascii=False, sort_keys=True)
        if _sha256(canonical.encode("utf-8")) != record.get("hash"):
            return {"ok": False, "entries": len(records), "message": f"hash mismatch at seq={record.get('seq')}"}
        previous_hash = record.get("hash")
    return {"ok": True, "entries": len(records), "message": f"chain ok, {len(records)} entries"}


def build_agentteams_v2_state(evidence_root: str | Path | None) -> dict:
    """Read and independently validate the allowlisted LABOPS-AT-002 evidence bundle."""
    if evidence_root is None:
        return {"ready": False}
    evidence_root = Path(evidence_root)
    top_manifest = _read_json(evidence_root / "evidence_bundle_manifest.json", {})
    bundle_path = evidence_root / "LABOPS-AT-002-evidence-bundle.zip"
    if not top_manifest or not bundle_path.is_file():
        return {"ready": False}

    names = {
        "handoff": "artifacts/handoff_manifest.json",
        "approval": "artifacts/approval_request_LABOPS-AT-002.json",
        "valid_verification": "artifacts/DEMO-RCA-001/verification.json",
        "unsafe_verification": "artifacts/DEMO-RCA-002/verification.json",
        "valid_plan": "artifacts/DEMO-RCA-001/plan.json",
        "unsafe_policy": "artifacts/DEMO-RCA-002/approvals/POLICY-REJECTION.json",
        "valid_run": "artifacts/DEMO-RCA-001/runs/RUN-DEMO-001/run_manifest.json",
        "unsafe_rollback": "artifacts/DEMO-RCA-002/runs/RUN-DEMO-UNSAFE-001/rollback.json",
        "valid_trace": "artifacts/DEMO-RCA-001/trace.jsonl",
        "unsafe_trace": "artifacts/DEMO-RCA-002/trace.jsonl",
    }
    payloads: dict[str, Any] = {}
    traces: dict[str, dict] = {}
    artifact_hashes_ok = True
    artifact_hash_errors: list[str] = []
    try:
        bundle_bytes = bundle_path.read_bytes()
        zip_hash_ok = _sha256(bundle_bytes) == top_manifest.get("zip_sha256")
        with zipfile.ZipFile(bundle_path) as bundle:
            expected_hashes = top_manifest.get("artifacts", {})
            for artifact_name, expected_hash in expected_hashes.items():
                try:
                    if _sha256(bundle.read(artifact_name)) != expected_hash:
                        artifact_hashes_ok = False
                        artifact_hash_errors.append(artifact_name)
                except KeyError:
                    artifact_hashes_ok = False
                    artifact_hash_errors.append(artifact_name)
            for key, artifact_name in names.items():
                raw = bundle.read(artifact_name)
                if key.endswith("trace"):
                    traces[key] = _verify_trace_bytes(raw)
                else:
                    payloads[key] = json.loads(raw)
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, ValueError) as exc:
        return {"ready": False, "error": str(exc)}

    handoff = payloads["handoff"]
    approval = payloads["approval"]
    valid_verification = payloads["valid_verification"]
    unsafe_verification = payloads["unsafe_verification"]
    valid_plan = payloads["valid_plan"]
    valid_run = payloads["valid_run"]
    unsafe_rollback = payloads["unsafe_rollback"]
    unsafe_policy = payloads["unsafe_policy"]
    changes = valid_plan.get("changes", [])
    budget = valid_plan.get("budget", {})
    forbidden = set(valid_plan.get("forbidden_changes", []))
    planner_checks = {
        "single_variable": len(changes) == 1 and changes[0].get("file") == "eval_config.json" and changes[0].get("field") == "checkpoint",
        "limited_budget": budget.get("max_runtime_seconds", 10**9) <= 30 and budget.get("device") == "cpu" and budget.get("network") is False,
        "evaluation_logic_immutable": "metric.py" in forbidden and all(change.get("file") != "metric.py" for change in changes),
        "rollback_defined": bool(valid_plan.get("rollback")),
        "unsafe_plan_rejected": unsafe_policy.get("decision") == "POLICY_REJECTED",
    }
    role_labels = {
        "labops-manager": "Incident Commander",
        "evidence-collector": "Evidence Collector",
        "rca-analyst": "RCA Analyst",
        "experiment-planner": "Experiment Planner",
        "safe-executor": "Safe Executor",
        "verification-auditor": "Verification Auditor",
    }
    roles_mapping = handoff.get("roles_mapping", {})
    role_order = ["labops-manager", "evidence-collector", "rca-analyst", "experiment-planner", "safe-executor", "verification-auditor"]
    roles = [
        {"role": role_labels[role], "logical_id": role, "worker": roles_mapping.get(role), "status": "RAN"}
        for role in role_order if roles_mapping.get(role)
    ]
    valid_checks = valid_verification.get("checks", {})
    unsafe_checks = unsafe_verification.get("checks", {})
    valid_trace = traces.get("valid_trace", {"ok": False, "entries": 0})
    unsafe_trace = traces.get("unsafe_trace", {"ok": False, "entries": 0})
    return {
        "ready": True,
        "task_id": top_manifest.get("task_id"),
        "final_state": top_manifest.get("final_state"),
        "created_at": top_manifest.get("created_at"),
        "six_roles_run": handoff.get("six_roles_run") is True and len(roles) == 6,
        "roles": roles,
        "handoffs": handoff.get("handoffs", []),
        "planner_checks": planner_checks,
        "approval": {
            "approval_id": approval.get("approval_id"),
            "decision": approval.get("decision"),
            "decided_by": approval.get("decided_by"),
            "approved_at": approval.get("approved_at"),
            "scope": approval.get("scope", {}),
            "not_approved": approval.get("not_approved", []),
            "before_execution": valid_checks.get("approval_before_execution", {}).get("pass") is True,
        },
        "valid_case": {
            "incident_id": "DEMO-RCA-001",
            "decision": valid_verification.get("decision"),
            "resolution_status": valid_verification.get("resolution_status"),
            "resolved": bool(valid_verification.get("resolved", False)),
            "reason": valid_verification.get("reason"),
            "run_status": valid_run.get("status"),
            "failure": valid_checks.get("concrete_postcondition", {}).get("failure"),
            "single_change_only": valid_checks.get("changed_paths_within_sandbox", {}).get("pass") is True,
            "metric_unchanged": valid_checks.get("metric_immutability", {}).get("hash_unchanged") is True,
        },
        "unsafe_case": {
            "incident_id": "DEMO-RCA-002",
            "decision": unsafe_verification.get("decision"),
            "resolution_status": unsafe_verification.get("resolution_status"),
            "resolved": bool(unsafe_verification.get("resolved", False)),
            "tamper_detected": unsafe_checks.get("tamper_detected", {}).get("pass") is True,
            "rollback_ok": unsafe_rollback.get("metric_hash_restored") is True,
            "hash_restored": unsafe_checks.get("restored_hash_matches_frozen", {}).get("hash_match") is True,
            "restored_hash": unsafe_checks.get("restored_hash_matches_frozen", {}).get("restored_metric_hash"),
            "original_hash": unsafe_checks.get("restored_hash_matches_frozen", {}).get("frozen_baseline_hash"),
        },
        "trace_chains": {"DEMO-RCA-001": valid_trace, "DEMO-RCA-002": unsafe_trace},
        "bundle": {
            "filename": bundle_path.name,
            "artifact_count": len(top_manifest.get("artifacts", {})),
            "zip_sha256": top_manifest.get("zip_sha256"),
            "zip_hash_ok": zip_hash_ok,
            "artifact_hashes_ok": artifact_hashes_ok,
            "artifact_hash_errors": artifact_hash_errors,
        },
        "source": {
            "matrix": "AgentTeams Element rooms",
            "minio": "shared/tasks/LABOPS-AT-002/",
            "artifact": "read-only evidence bundle",
        },
        "unresolved_limitations": handoff.get("unresolved_limitations", []),
    }


def build_agentteams_v3_state(evidence_root: str | Path | None) -> dict:
    """Read and independently validate the allowlisted LABOPS-AT-003 evidence bundle."""
    if evidence_root is None:
        return {"ready": False}
    evidence_root = Path(evidence_root)
    package_root = evidence_root / "artifacts" / "DEMO-RCA-003"
    if not package_root.is_dir():
        package_root = evidence_root
    top_manifest = _read_json(package_root / "evidence_bundle_manifest.json", {})
    bundle_path = package_root / "LABOPS-AT-003-evidence-bundle.zip"
    if not top_manifest or not bundle_path.is_file():
        return {"ready": False}

    json_names = {
        "handoff": "handoff_manifest.json",
        "approval": "approval.json",
        "plan": "plan.json",
        "run": "run_result.json",
        "metrics": "metrics.json",
        "runner_manifest": "artifact_manifest.json",
        "capability": "host_capability_check.json",
        "verification": "verification.json",
        "trace_issue": "agentteams_trace_audit.json",
        "trace_final": "agentteams_trace_audit_final.json",
    }
    payloads: dict[str, Any] = {}
    artifact_hashes_ok = True
    artifact_hash_errors: list[str] = []
    runner_artifact_hashes_ok = True
    runner_artifact_hash_errors: list[str] = []
    try:
        bundle_bytes = bundle_path.read_bytes()
        zip_hash_ok = _sha256(bundle_bytes) == top_manifest.get("zip_sha256")
        with zipfile.ZipFile(bundle_path) as bundle:
            expected_hashes = top_manifest.get("artifacts", {})
            for artifact_name, expected_hash in expected_hashes.items():
                try:
                    if _sha256(bundle.read(artifact_name)) != expected_hash:
                        artifact_hashes_ok = False
                        artifact_hash_errors.append(artifact_name)
                except KeyError:
                    artifact_hashes_ok = False
                    artifact_hash_errors.append(artifact_name)
            for key, artifact_name in json_names.items():
                payloads[key] = json.loads(bundle.read(artifact_name))
            trace_raw = bundle.read("agentteams_trace.jsonl")
            trace = _verify_trace_bytes(trace_raw)
            trace_records = [json.loads(line) for line in trace_raw.decode("utf-8").splitlines() if line]
            event_ids = [record.get("event_id") for record in trace_records]
            trace["event_ids_unique"] = bool(event_ids) and len(event_ids) == len(set(event_ids))

            runner_manifest = payloads["runner_manifest"].get("artifacts", {})
            for artifact_name, record in runner_manifest.items():
                try:
                    raw = bundle.read(artifact_name)
                except KeyError:
                    runner_artifact_hashes_ok = False
                    runner_artifact_hash_errors.append(artifact_name)
                    continue
                if _sha256(raw) != record.get("sha256") or len(raw) != record.get("size"):
                    runner_artifact_hashes_ok = False
                    runner_artifact_hash_errors.append(artifact_name)
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, ValueError) as exc:
        return {"ready": False, "error": str(exc)}

    handoff = payloads["handoff"]
    approval = payloads["approval"]
    plan = payloads["plan"]
    run = payloads["run"]
    metrics = payloads["metrics"]
    capability = payloads["capability"]
    verification = payloads["verification"]
    trace_issue = payloads["trace_issue"]
    trace_final = payloads["trace_final"]
    changes = plan.get("changes", [])
    budget = plan.get("budget", {})
    forbidden = set(plan.get("forbidden_changes", []))
    verification_checks = verification.get("checks", {})
    checks_all_pass = bool(verification_checks) and all(
        isinstance(item, dict) and item.get("passed") is True for item in verification_checks.values()
    )
    planner_checks = {
        "single_variable": len(changes) == 1 and changes[0].get("file") == "eval_config.json" and changes[0].get("field") == "checkpoint",
        "limited_budget": budget.get("max_runtime_seconds", 10**9) <= 30 and budget.get("device") == "cpu" and budget.get("network") is False,
        "evaluation_logic_immutable": "metric.py" in forbidden and all(change.get("file") != "metric.py" for change in changes),
        "original_workspace_forbidden": "original_workspace" in forbidden,
        "rollback_defined": bool(plan.get("rollback")),
        "approval_required": plan.get("approval_required") is True,
    }
    role_details = {
        "evidence-collector": ("Evidence Collector", "evidence-collector"),
        "rca-analyst": ("RCA Analyst", "rca-analyst"),
        "experiment-planner(researcher)": ("Experiment Planner", "researcher"),
        "safe-executor(controlled-executor)": ("Safe Executor", "controlled-executor"),
        "verification-auditor": ("Verification Auditor", "verification-auditor"),
        "manager": ("Incident Commander", "labops-manager"),
    }
    roles = [
        {"role": role_details[item["role"]][0], "logical_id": item["role"], "worker": role_details[item["role"]][1], "status": "RAN"}
        for item in handoff.get("handoffs", []) if item.get("role") in role_details
    ]
    protected = run.get("protected_hashes", {})
    cap_checks = capability.get("checks", {})
    approval_before_execution = bool(approval.get("approved_at") and run.get("start_time") and approval["approved_at"] < run["start_time"])
    return {
        "ready": True,
        "task_id": top_manifest.get("task_id"),
        "incident_id": top_manifest.get("incident_id"),
        "run_id": top_manifest.get("run_id"),
        "final_state": top_manifest.get("final_status"),
        "created_at": top_manifest.get("created_at"),
        "six_roles_run": len(roles) == 6,
        "roles": roles,
        "handoffs": handoff.get("handoffs", []),
        "planner_checks": planner_checks,
        "approval": {
            "approval_id": approval.get("approval_id"),
            "decision": approval.get("decision"),
            "decided_by": approval.get("decided_by"),
            "approved_at": approval.get("approved_at"),
            "before_execution": approval_before_execution,
            "approved_scope": approval.get("approved_scope", []),
            "not_approved": approval.get("not_approved", []),
        },
        "runner": {
            "image": plan.get("runtime", {}).get("image"),
            "status": run.get("status"),
            "return_code": run.get("return_code"),
            "network": run.get("network"),
            "sandbox_only": run.get("sandbox_only") is True,
            "original_project_modified": run.get("original_project_modified"),
            "changed_paths": run.get("changed_paths", []),
            "baseline_accuracy": metrics.get("baseline_accuracy"),
            "candidate_accuracy": metrics.get("candidate_accuracy"),
            "baseline_values": metrics.get("baseline_accuracy_values", []),
            "candidate_values": metrics.get("candidate_accuracy_values", []),
            "reproducible": metrics.get("reproducible") is True,
            "metric_hash": protected.get("metric_after"),
            "metric_unchanged": protected.get("metric_unchanged") is True,
            "validation_data_hash": protected.get("validation_data_after"),
            "validation_data_unchanged": protected.get("validation_data_unchanged") is True,
        },
        "capability": {
            "status": capability.get("status"),
            "checks": cap_checks,
            "all_pass": bool(cap_checks) and all(cap_checks.values()),
            "runtime": capability.get("runtime", {}),
        },
        "verification": {
            "decision": verification.get("decision"),
            "resolution_status": verification.get("resolution_status"),
            "verified_by": verification.get("verified_by"),
            "verified_at": verification.get("verified_at"),
            "checks_all_pass": checks_all_pass,
        },
        "trace": {
            **trace,
            "issue_preserved": trace_issue.get("decision") == "ISSUE",
            "final_audit": trace_final.get("decision"),
            "final_audit_ok": trace_final.get("chain_ok") is True and trace_final.get("decision") == "CHAIN_OK",
            "roles_covered": trace_final.get("roles_covered", []),
            "timeline_monotonic": trace_final.get("timeline_monotonic") is True,
        },
        "bundle": {
            "filename": bundle_path.name,
            "artifact_count": len(top_manifest.get("artifacts", {})),
            "size_bytes": top_manifest.get("zip_size_bytes"),
            "zip_sha256": top_manifest.get("zip_sha256"),
            "zip_hash_ok": zip_hash_ok,
            "artifact_hashes_ok": artifact_hashes_ok,
            "artifact_hash_errors": artifact_hash_errors,
            "runner_artifact_hashes_ok": runner_artifact_hashes_ok,
            "runner_artifact_hash_errors": runner_artifact_hash_errors,
        },
        "source": {
            "matrix": "AgentTeams Element rooms",
            "minio": "shared/tasks/LABOPS-AT-003/",
            "artifact": "read-only LABOPS-AT-003 evidence bundle",
            "runner": "control-plane raw five files",
        },
    }


def build_checkpoint_demo_state(artifacts_root: str | Path | None) -> dict:
    """Return an allowlisted summary of the two checkpoint demo incidents."""
    if artifacts_root is None:
        return {"ready": False}
    artifacts_root = Path(artifacts_root)
    valid_root = artifacts_root / "DEMO-RCA-001"
    unsafe_root = artifacts_root / "DEMO-RCA-002"
    stability = _read_json(valid_root / "baseline" / "stability_report.json", {})
    valid_state = _read_json(valid_root / "state.json", {})
    valid_verification = _read_json(valid_root / "verification.json", {})
    unsafe_state = _read_json(unsafe_root / "state.json", {})
    unsafe_verification = _read_json(unsafe_root / "verification.json", {})
    rollback = _read_json(unsafe_root / "runs" / "RUN-DEMO-UNSAFE-001" / "rollback.json", {})
    ready = bool(stability and valid_state and valid_verification and unsafe_state and unsafe_verification)

    def trace_status(path: Path) -> dict:
        trace = TraceLog(path)
        try:
            records = trace.read()
            ok, message = trace.verify_chain()
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            return {"ok": False, "entries": 0, "message": str(exc)}
        return {"ok": ok, "entries": len(records), "message": message}

    return {
        "ready": ready,
        "baseline": {
            "best_accuracy": stability.get("best_accuracy"),
            "current_accuracy": stability.get("current_accuracy"),
            "target_accuracy": stability.get("target_accuracy"),
            "repeats": stability.get("repeats"),
            "stable": bool(stability.get("stable", False)),
            "passed": bool(stability.get("passed", False)),
            "configured_checkpoint": stability.get("configured_checkpoint"),
        },
        "valid_case": {
            "incident_id": "DEMO-RCA-001",
            "state": valid_state.get("state"),
            "decision": valid_verification.get("decision"),
            "baseline_accuracy": valid_verification.get("baseline_accuracy"),
            "candidate_accuracy": valid_verification.get("candidate_accuracy"),
            "improvement": valid_verification.get("improvement"),
            "trace": trace_status(valid_root / "trace.jsonl"),
        },
        "unsafe_case": {
            "incident_id": "DEMO-RCA-002",
            "state": unsafe_state.get("state"),
            "decision": unsafe_verification.get("decision"),
            "claimed_accuracy": unsafe_verification.get("claimed_accuracy"),
            "rollback_ok": bool(rollback.get("metric_hash_restored", False)),
            "trace": trace_status(unsafe_root / "trace.jsonl"),
        },
    }


def build_dashboard_state(
    workspace: str | Path,
    checkpoint_workspace: str | Path | None = None,
    agentteams_v2_workspace: str | Path | None = None,
    agentteams_v3_workspace: str | Path | None = None,
) -> dict:
    """Build the allowlisted dashboard payload from generated demo artifacts."""
    workspace = Path(workspace)
    summary = _read_json(workspace / "demo" / "demo_summary.json", {})
    manifest = _read_json(workspace / "evidence_bundle_manifest.json", {})
    registry = _read_json(workspace / "registry_record.json", {})
    collected = _read_json(workspace / "collected_evidence.json", {})
    diagnosis = _read_json(workspace / "diagnosis_candidates.json", {})
    approvals = _read_json(workspace / "approval_requests.json", [])
    execution = _read_json(workspace / "execution_result.json", {})
    verification = _read_json(workspace / "verification_result.json", {})

    trace = TraceLog(workspace / "trace.jsonl")
    try:
        trace_records = trace.read()
        trace_ok, trace_message = trace.verify_chain()
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        trace_records = []
        trace_ok, trace_message = False, f"trace unreadable: {exc}"

    hypotheses = diagnosis.get("hypotheses", [])
    evidence = collected.get("evidence", [])
    gaps = collected.get("gaps", [])
    is_agentteams = bool(manifest.get("task_id") and manifest.get("participating_agents"))
    ready = bool(registry and collected and diagnosis and verification and (summary or is_agentteams))
    approval_counts = _counts(approvals, "status")
    action_events = [r for r in trace_records if r.get("entity_type") == "action"]
    manifest_counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    manifest_verification = manifest.get("verification", {}) if isinstance(manifest.get("verification"), dict) else {}
    execution_result = execution.get("result", {}) if isinstance(execution.get("result"), dict) else {}

    agent_roles = {
        "labops-manager": "编排、状态治理与证据打包",
        "evidence-collector": "白名单证据采集",
        "rca-analyst": "证据约束 RCA",
        "controlled-executor": "审批门禁与受控执行",
        "verification-auditor": "独立验证与闭环裁决",
    }
    participating_agents = manifest.get("participating_agents", []) if is_agentteams else []
    agents = [
        {"id": agent_id, "role": agent_roles.get(agent_id, "受控协作角色"), "status": "COMPLETED"}
        for agent_id in participating_agents
    ]
    handoffs = []
    if is_agentteams:
        handoffs = [
            {"from": "labops-manager", "to": "evidence-collector", "result": "EVIDENCE_READY"},
            {"from": "evidence-collector", "to": "rca-analyst", "result": "DIAGNOSIS_READY"},
            {"from": "rca-analyst", "to": "controlled-executor", "result": "SIMULATED_SUCCEEDED"},
            {"from": "controlled-executor", "to": "verification-auditor", "result": "DEMO_PASSED_NOT_RESOLVED"},
            {"from": "verification-auditor", "to": "labops-manager", "result": "EVIDENCE_PACKAGED"},
        ][: int(manifest.get("handoff_count", 0))]

    allowed_files = summary.get("allowed_files", manifest_counts.get("allowed_files", registry.get("allowed_file_count", 0)))
    evidence_count = summary.get("evidence_count", manifest_counts.get("evidence", collected.get("evidence_count", 0)))
    gaps_count = summary.get("gaps_count", manifest_counts.get("gaps", collected.get("gaps_count", 0)))
    demo_verification = summary.get("demo_verification", manifest_verification.get("demo_verification", verification.get("demo_verification", "NOT_RUN")))
    incident_state = summary.get("incident_state", manifest.get("final_state", verification.get("incident_state", "NOT_RUN")))
    underlying_issue_resolved = bool(summary.get("underlying_issue_resolved", manifest_verification.get("underlying_issue_resolved", verification.get("underlying_issue_resolved", False))))

    return {
        "schema_version": "1.1",
        "ready": ready,
        "project": "polar-baseline",
        "source": {
            "mode": "AGENTTEAMS_RUN" if is_agentteams else "LOCAL_DEMO",
            "label": "AgentTeams 真实协作记录" if is_agentteams else "本地内置演示",
            "read_only": True,
        },
        "principles": ["无证据不诊断", "无审批不执行", "无验证不闭环"],
        "summary": {
            "allowed_files": allowed_files,
            "snapshot_status": summary.get("verification_status", registry.get("verification_status", "NOT_RUN")),
            "evidence_count": evidence_count,
            "gaps_count": gaps_count,
            "demo_verification": demo_verification,
            "incident_state": incident_state,
            "underlying_issue_resolved": underlying_issue_resolved,
            "trace_chain_ok": bool(summary.get("trace_chain_ok", trace_ok)) and trace_ok,
        },
        "stages": [
            {"id": "snapshot", "label": "快照登记", "value": registry.get("verification_status", "NOT_RUN"), "ok": registry.get("verification_status") == "VERIFIED"},
            {"id": "evidence", "label": "证据采集", "value": f"{len(evidence)} 项证据", "ok": bool(evidence)},
            {"id": "diagnosis", "label": "受控诊断", "value": f"{len(hypotheses)} 个假设", "ok": bool(hypotheses)},
            {"id": "approval", "label": "人工审批", "value": f"{len(approvals)} 个请求", "ok": bool(approvals)},
            {"id": "action", "label": "受控动作", "value": f"{len(action_events)} 条记录", "ok": bool(action_events)},
            {"id": "verify", "label": "验证闭环", "value": incident_state, "ok": demo_verification == "PASSED"},
        ],
        "evidence": evidence,
        "gaps": gaps,
        "hypotheses": hypotheses,
        "hypothesis_counts": _counts(hypotheses, "state"),
        "approvals": approvals,
        "approval_counts": approval_counts,
        "verification": verification,
        "agentteams": {
            "enabled": is_agentteams,
            "task_id": manifest.get("task_id"),
            "incident_id": manifest.get("incident_id", verification.get("incident_id")),
            "agents": agents,
            "handoff_count": int(manifest.get("handoff_count", 0)) if is_agentteams else 0,
            "handoffs": handoffs,
            "package_time": manifest.get("package_time"),
            "execution": {
                "owner": execution.get("owner"),
                "mode": execution.get("mode"),
                "status": execution_result.get("status"),
                "simulated": bool(execution_result.get("simulated", False)),
                "approval_id": execution.get("approval", {}).get("approval_id") if isinstance(execution.get("approval"), dict) else None,
                "decided_by": execution.get("approval", {}).get("decided_by") if isinstance(execution.get("approval"), dict) else None,
            },
            "unresolved_limitations": manifest.get("unresolved_limitations", []) if is_agentteams else [],
        },
        "checkpoint_demo": build_checkpoint_demo_state(checkpoint_workspace),
        "agentteams_v2": build_agentteams_v2_state(agentteams_v2_workspace),
        "agentteams_v3": build_agentteams_v3_state(agentteams_v3_workspace),
        "trace": {
            "ok": trace_ok,
            "message": trace_message,
            "entries": len(trace_records),
            "recent": trace_records[-12:][::-1],
        },
        "safety": {
            "excluded_data_not_read": bool(summary.get("excluded_data_not_read", registry.get("excluded_data_not_read", False))),
            "no_fabricated_faults": bool(summary.get("no_fabricated_faults", False)),
            "no_polar_root_cause_claim": bool(summary.get("no_polar_root_cause_claim", False)),
            "no_model_optimization": bool(summary.get("no_model_optimization", False)),
            "network_required": False,
            "risky_actions_simulated": True,
            "prohibited_operations_zero": bool(is_agentteams and all(
                value == 0 for value in manifest.get("prohibited_operations_zero", {}).values()
            )),
        },
    }


def run_bundled_demo(workspace: str | Path, project_root: str | Path) -> int:
    """Generate demo output once when a workspace has no existing summary."""
    from labops.demo import run_demo

    workspace = Path(workspace)
    project_root = Path(project_root)
    summary = workspace / "demo" / "demo_summary.json"
    if summary.exists():
        return 0
    fixtures = project_root / "demo" / "fixtures"
    return run_demo(
        workspace=workspace,
        snapshot_dir=fixtures / "project_snapshot_lite",
        audit_dir=fixtures / "audit",
        verification_json=fixtures / "snapshot_verification.json",
        allowed_list=project_root / "demo" / "allowed_files.json",
        trace=TraceLog(workspace / "trace.jsonl"),
    )


def make_handler(
    workspace: str | Path,
    checkpoint_workspace: str | Path | None = None,
    agentteams_v2_workspace: str | Path | None = None,
    agentteams_v3_workspace: str | Path | None = None,
):
    workspace = Path(workspace).resolve()
    checkpoint_workspace = Path(checkpoint_workspace).resolve() if checkpoint_workspace else None
    agentteams_v2_workspace = Path(agentteams_v2_workspace).resolve() if agentteams_v2_workspace else None
    agentteams_v3_workspace = Path(agentteams_v3_workspace).resolve() if agentteams_v3_workspace else None
    dashboard_html = Path(__file__).with_name("dashboard.html")

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "LabOpsGuard/1.0"

        def _headers(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
            self.end_headers()

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self._headers(status, content_type, len(body))
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            path = self.path.split("?", 1)[0]
            if path == "/":
                try:
                    body = dashboard_html.read_bytes()
                except OSError as exc:
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                self._send(200, "text/html; charset=utf-8", body)
            elif path == "/api/status":
                self._json(200, build_dashboard_state(workspace, checkpoint_workspace, agentteams_v2_workspace, agentteams_v3_workspace))
            elif path == "/healthz":
                state = build_dashboard_state(workspace, checkpoint_workspace, agentteams_v2_workspace, agentteams_v3_workspace)
                self._json(200 if state["ready"] else 503, {"ok": state["ready"], "service": "labops-guard"})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            # Drain the request body before rejecting it. On Windows, closing a
            # socket with unread request bytes can reset the connection before
            # urllib receives the intended HTTP 405 response.
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 0:
                self.rfile.read(content_length)
            self._json(405, {"ok": False, "error": "dashboard is read-only"})

        def log_message(self, fmt: str, *args) -> None:
            print(f"[dashboard] {self.client_address[0]} {fmt % args}")

    return DashboardHandler


def serve(
    workspace: str | Path,
    host: str = "127.0.0.1",
    port: int = 8787,
    checkpoint_workspace: str | Path | None = None,
    agentteams_v2_workspace: str | Path | None = None,
    agentteams_v3_workspace: str | Path | None = None,
) -> None:
    """Serve the dashboard until interrupted."""
    server = ThreadingHTTPServer((host, port), make_handler(workspace, checkpoint_workspace, agentteams_v2_workspace, agentteams_v3_workspace))
    print(f"LabOps Guard dashboard: http://{host}:{port}")
    print(f"Workspace: {Path(workspace).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
