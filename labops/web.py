"""Local-only dashboard for LabOps Guard.

The server uses only Python's standard library and exposes read-only demo state.
It never serves arbitrary files from the workspace and never reads excluded data.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

from labops.live_demo import ROLE_ORDER, SESSION_ID
from labops.reviewer_state import EVENT_KINDS
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


def _build_at004_agentteams_state(root: Path) -> dict:
    """Validate and summarize the immutable AT-004 AgentTeams evidence bundle."""
    manifest_path = root / "evidence_manifest.json"
    bundle_path = root / "LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip"
    manifest = _read_json(manifest_path, {})
    if manifest.get("task_id") != "LABOPS-AT-004-EVAL-DRIFT" or not bundle_path.is_file():
        return {"ready": False}

    run_prefix = "runs/RUN-LABOPS-AT-004-AGENTTEAMS-001/"
    json_names = {
        "handoff": "handoff_manifest.json",
        "approval": "approval.json",
        "hypotheses": "hypotheses.json",
        "plan": "plan.json",
        "verification": "verification.json",
        "trace_issue": "agentteams_trace_audit.json",
        "trace_final": "agentteams_trace_audit_final.json",
        "evidence": "evidence/collected_evidence.json",
        "run": run_prefix + "run_result.json",
        "metrics": run_prefix + "metrics.json",
        "runner_manifest": run_prefix + "artifact_manifest.json",
        "capability": run_prefix + "host_capability_check.json",
    }
    payloads: dict[str, Any] = {}
    artifact_hash_errors: list[str] = []
    runner_hash_errors: list[str] = []
    member_set_ok = False
    manifest_copy_ok = False
    try:
        bundle_bytes = bundle_path.read_bytes()
        with zipfile.ZipFile(bundle_path) as bundle:
            names = bundle.namelist()
            expected = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
            expected_names = set(expected) | {"evidence_manifest.json"}
            member_set_ok = len(names) == len(set(names)) and set(names) == expected_names and all(
                not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts for name in names
            )
            for name, expected_hash in expected.items():
                try:
                    if _sha256(bundle.read(name)) != expected_hash:
                        artifact_hash_errors.append(name)
                except KeyError:
                    artifact_hash_errors.append(name)
            manifest_copy_ok = bundle.read("evidence_manifest.json") == manifest_path.read_bytes()
            for key, name in json_names.items():
                payloads[key] = json.loads(bundle.read(name))
            trace_raw = bundle.read("agentteams_trace.jsonl")
            trace = _verify_trace_bytes(trace_raw)
            trace_records = [json.loads(line) for line in trace_raw.decode("utf-8").splitlines() if line]
            runner_manifest = payloads["runner_manifest"].get("artifacts", {})
            for name, record in runner_manifest.items():
                try:
                    raw = bundle.read(run_prefix + name)
                except KeyError:
                    runner_hash_errors.append(name)
                    continue
                if _sha256(raw) != record.get("sha256") or len(raw) != record.get("size"):
                    runner_hash_errors.append(name)
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, ValueError) as exc:
        return {"ready": False, "error": str(exc)}

    handoff = payloads["handoff"]
    approval = payloads["approval"]
    hypotheses_doc = payloads["hypotheses"]
    plan = payloads["plan"]
    verification = payloads["verification"]
    trace_issue = payloads["trace_issue"]
    trace_final = payloads["trace_final"]
    evidence_doc = payloads["evidence"]
    run = payloads["run"]
    metrics = payloads["metrics"]
    capability = payloads["capability"]
    changes = plan.get("changes", [])
    budget = plan.get("budget", {})
    forbidden = set(plan.get("forbidden_changes", []))
    protected = run.get("protected_hashes", {})
    expected_roles = [
        "labops-manager", "evidence-collector", "rca-analyst",
        "experiment-planner", "safe-executor", "verification-auditor",
    ]
    role_labels = {
        "labops-manager": "Incident Commander",
        "evidence-collector": "Evidence Collector",
        "rca-analyst": "RCA Analyst",
        "experiment-planner": "Experiment Planner",
        "safe-executor": "Safe Executor",
        "verification-auditor": "Verification Auditor",
    }
    actual_roles = handoff.get("agent_roles_actual_order", [])
    trace_event_ids = [record.get("event_id") for record in trace_records]
    final_checks = trace_final.get("checks", {})
    verification_checks = verification.get("checks", {})
    plan_checks = {
        "single_variable": len(changes) == 1 and changes[0] == {
            "file": "eval_config.json",
            "field": "evaluation.preprocessing_profile",
            "before": "train_augmented",
            "after": "eval_standard",
        },
        "limited_budget": budget.get("max_runtime_seconds", 10**9) <= 30 and budget.get("device") == "cpu" and budget.get("network") is False,
        "protected_inputs_forbidden": {"metric.py", "validation_data.pt", "checkpoint", "evaluation_protocol.yaml", "thresholds", "target_metric", "original_workspace"}.issubset(forbidden),
        "rollback_defined": bool(plan.get("rollback")),
        "approval_required": plan.get("approval_required") is True,
    }
    approval_before_execution = bool(
        approval.get("decision") == "APPROVED"
        and approval.get("approved_at")
        and run.get("start_time")
        and approval["approved_at"] < run["start_time"]
    )
    protected_ok = all(protected.get(name) is True for name in (
        "checkpoint_unchanged", "validation_data_unchanged", "metric_unchanged",
        "evaluation_protocol_unchanged", "model_unchanged", "preprocessing_unchanged",
    ))
    hypotheses = hypotheses_doc.get("hypotheses", [])
    top_id = hypotheses_doc.get("top_hypothesis_id")
    top = next((item for item in hypotheses if item.get("hypothesis_id") == top_id), hypotheses[0] if hypotheses else {})
    run_view = {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "decision": verification.get("decision"),
        "baseline_accuracy": metrics.get("baseline_accuracy"),
        "candidate_accuracy": metrics.get("candidate_accuracy"),
        "baseline_values": metrics.get("baseline_accuracy_values", []),
        "candidate_values": metrics.get("candidate_accuracy_values", []),
        "network": run.get("network"),
        "sandbox_only": run.get("sandbox_only") is True,
        "changed_paths": run.get("changed_paths", []),
        "approval_before_execution": approval_before_execution,
        "protected_hashes_ok": protected_ok,
        "artifact_hashes_ok": not runner_hash_errors,
    }
    integrity = {
        "bundle_member_set_ok": member_set_ok,
        "manifest_copy_ok": manifest_copy_ok,
        "artifact_hashes_ok": not artifact_hash_errors,
        "runner_artifact_hashes_ok": not runner_hash_errors,
        "protected_hashes_ok": protected_ok,
        "approval_order_ok": approval_before_execution,
        "trace_ok": trace.get("ok") is True,
        "trace_final_audit_ok": trace_final.get("decision") == "CHAIN_OK" and trace_final.get("acceptance") == "ACCEPTED" and all(
            isinstance(check, dict) and check.get("passed") is True for check in final_checks.values()
        ),
    }
    return {
        "ready": True,
        "source_mode": "AGENTTEAMS_RUN",
        "source_label": "AT-004 六角色 AgentTeams 真实运行与离线 Runner 证据",
        "task_id": manifest.get("task_id"),
        "incident_id": manifest.get("incident_id"),
        "status": verification.get("decision"),
        "resolution_status": verification.get("resolution_status"),
        "runner_image": plan.get("runtime", {}).get("image"),
        "evidence": evidence_doc.get("evidence", []),
        "evidence_count": len(evidence_doc.get("evidence", [])),
        "hypotheses": hypotheses,
        "top_hypothesis": top,
        "plan": plan,
        "plan_checks": plan_checks,
        "approval": {
            "approval_id": approval.get("approval_id"),
            "decision": approval.get("decision"),
            "decided_by": approval.get("decided_by"),
            "approved_at": approval.get("approved_at"),
            "before_execution": approval_before_execution,
        },
        "verification": {
            "decision": verification.get("decision"),
            "resolution_status": verification.get("resolution_status"),
            "verified_by": verification.get("verified_by"),
            "checks_all_pass": bool(verification_checks) and all(
                isinstance(check, dict) and check.get("pass") is True for check in verification_checks.values()
            ),
        },
        "capability": {
            "status": capability.get("status"),
            "checks": capability.get("checks", {}),
            "runtime": capability.get("runtime", {}),
            "all_pass": bool(capability.get("checks")) and all(capability.get("checks", {}).values()),
        },
        "runs": [run_view],
        "integrity": integrity,
        "trace": {
            **trace,
            "event_ids_unique": bool(trace_event_ids) and len(trace_event_ids) == len(set(trace_event_ids)),
            "final_audit": trace_final.get("decision"),
            "final_acceptance": trace_final.get("acceptance"),
            "first_issue_preserved": trace_issue.get("decision") == "ISSUE",
        },
        "agentteams": {
            "six_roles_run": actual_roles == expected_roles and trace_final.get("six_agent_roles_covered") is True,
            "roles": [{"logical_id": role, "role": role_labels[role], "status": "RAN"} for role in actual_roles if role in role_labels],
            "handoffs": handoff.get("handoffs", []),
            "human_approval": handoff.get("human_approval_separate", {}),
            "note": "六个 Agent 角色与人工审批分别记录；Matrix event ID、MinIO 产物、Runner 原始文件和 Auditor 审计共同构成证据。",
        },
        "bundle": {
            "filename": bundle_path.name,
            "size_bytes": len(bundle_bytes),
            "sha256": _sha256(bundle_bytes),
            "artifact_count": len(manifest.get("files", [])) + 1,
            "member_set_ok": member_set_ok,
            "manifest_copy_ok": manifest_copy_ok,
            "artifact_hashes_ok": not artifact_hash_errors,
            "artifact_hash_errors": artifact_hash_errors,
            "runner_artifact_hashes_ok": not runner_hash_errors,
            "runner_artifact_hash_errors": runner_hash_errors,
        },
        "source": {
            "matrix": "7-entry authoritative Matrix trace (6 Agent roles + human approval)",
            "minio": "shared/tasks/LABOPS-AT-004-EVAL-DRIFT/",
            "artifact": "read-only LABOPS-AT-004 evidence bundle",
            "runner": "control-plane original Runner and gateway artifacts",
        },
    }


def build_at004_state(evidence_root: str | Path | None) -> dict:
    """Build an allowlisted story view of AT-004 local validation evidence.

    Local validation is deliberately not represented as an AgentTeams run.  The
    source_mode field is the trust boundary consumed by the dashboard.
    """
    if evidence_root is None:
        return {"ready": False}
    root = Path(evidence_root)
    if (root / "LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip").is_file():
        return _build_at004_agentteams_state(root)
    summary = _read_json(root / "local_validation_summary.json", {})
    evidence_doc = _read_json(root / "evidence" / "collected_evidence.json", {})
    hypotheses_doc = _read_json(root / "hypotheses.json", {})
    capability = _read_json(root / "runtime_capability_check.json", {})
    if not summary or not evidence_doc or not hypotheses_doc or not capability:
        return {"ready": False}
    if summary.get("task_id") != "LABOPS-AT-004-EVAL-DRIFT":
        return {"ready": False, "error": "unexpected AT-004 task_id"}

    trace = TraceLog(root / "trace.jsonl")
    try:
        trace_records = trace.read()
        trace_ok, trace_message = trace.verify_chain()
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        trace_records = []
        trace_ok, trace_message = False, f"trace unreadable: {exc}"

    runs = []
    all_artifact_hashes_ok = True
    all_approval_order_ok = True
    all_protected_hashes_ok = True
    first_plan: dict = {}
    first_approval: dict = {}
    first_verification: dict = {}
    for run_summary in summary.get("runs", []):
        run_id = run_summary.get("run_id")
        if not isinstance(run_id, str) or not run_id.startswith("RUN-LABOPS-AT-004-LOCAL-"):
            continue
        run_root = root / "runs" / run_id
        plan = _read_json(run_root / "experiment_plan.json", {})
        approval = _read_json(run_root / "approval.json", {})
        run_result = _read_json(run_root / "run_result.json", {})
        verification = _read_json(run_root / "verification.json", {})
        manifest = _read_json(run_root / "artifact_manifest.json", {})
        if not first_plan:
            first_plan, first_approval, first_verification = plan, approval, verification

        manifest_ok = bool(manifest) and manifest.get("run_id") == run_id
        for name, metadata in manifest.get("artifacts", {}).items():
            path = run_root / name
            try:
                manifest_ok = manifest_ok and _sha256(path.read_bytes()) == metadata.get("sha256")
            except OSError:
                manifest_ok = False
        all_artifact_hashes_ok = all_artifact_hashes_ok and manifest_ok

        approval_order_ok = bool(
            approval.get("decision") == "APPROVED"
            and approval.get("approved_at")
            and run_result.get("start_time")
            and approval["approved_at"] <= run_result["start_time"]
        )
        all_approval_order_ok = all_approval_order_ok and approval_order_ok
        protected = run_result.get("protected_hashes", {})
        protected_ok = all(
            protected.get(key) is True
            for key in (
                "checkpoint_unchanged",
                "validation_data_unchanged",
                "metric_unchanged",
                "evaluation_protocol_unchanged",
                "model_unchanged",
                "preprocessing_unchanged",
            )
        )
        all_protected_hashes_ok = all_protected_hashes_ok and protected_ok
        runs.append({
            "run_id": run_id,
            "status": run_result.get("status"),
            "decision": verification.get("decision"),
            "baseline_accuracy": run_result.get("metrics", {}).get("baseline_accuracy"),
            "candidate_accuracy": run_result.get("metrics", {}).get("candidate_accuracy"),
            "baseline_values": run_result.get("metrics", {}).get("baseline_accuracy_values", []),
            "candidate_values": run_result.get("metrics", {}).get("candidate_accuracy_values", []),
            "network": run_result.get("network"),
            "sandbox_only": run_result.get("sandbox_only") is True,
            "changed_paths": run_result.get("changed_paths", []),
            "approval_before_execution": approval_order_ok,
            "protected_hashes_ok": protected_ok,
            "artifact_hashes_ok": manifest_ok,
        })

    changes = first_plan.get("changes", [])
    budget = first_plan.get("budget", {})
    forbidden = set(first_plan.get("forbidden_changes", []))
    plan_checks = {
        "single_variable": len(changes) == 1 and changes[0] == {
            "file": "eval_config.json",
            "field": "evaluation.preprocessing_profile",
            "before": "train_augmented",
            "after": "eval_standard",
        },
        "limited_budget": budget.get("max_runtime_seconds", 10**9) <= 30 and budget.get("device") == "cpu" and budget.get("network") is False,
        "protected_inputs_forbidden": {"metric.py", "validation_data.pt", "checkpoint", "evaluation_protocol.yaml", "original_workspace"}.issubset(forbidden),
        "rollback_defined": bool(first_plan.get("rollback")),
    }
    evidence = evidence_doc.get("evidence", [])
    hypotheses = hypotheses_doc.get("hypotheses", [])
    top_id = hypotheses_doc.get("top_hypothesis_id")
    top = next((item for item in hypotheses if item.get("hypothesis_id") == top_id), {})
    return {
        "ready": bool(runs),
        "source_mode": "LOCAL_VALIDATION",
        "source_label": "AT-004 三次离线本地验证（非 AgentTeams 运行）",
        "task_id": summary.get("task_id"),
        "incident_id": summary.get("incident_id"),
        "status": summary.get("status"),
        "resolution_status": summary.get("resolution_status"),
        "runner_image": summary.get("runner_image"),
        "evidence": evidence,
        "evidence_count": len(evidence),
        "hypotheses": hypotheses,
        "top_hypothesis": top,
        "plan": first_plan,
        "plan_checks": plan_checks,
        "approval": {
            "decision": first_approval.get("decision"),
            "decided_by": first_approval.get("decided_by"),
            "before_execution": all_approval_order_ok,
        },
        "verification": {
            "decision": first_verification.get("decision"),
            "resolution_status": first_verification.get("resolution_status"),
            "checks_all_pass": bool(first_verification.get("checks")) and all(first_verification.get("checks", {}).values()),
        },
        "capability": {
            "status": capability.get("status"),
            "checks": capability.get("checks", {}),
            "runtime": capability.get("runtime", {}),
            "all_pass": bool(capability.get("checks")) and all(capability.get("checks", {}).values()),
        },
        "runs": runs,
        "integrity": {
            "artifact_hashes_ok": all_artifact_hashes_ok,
            "protected_hashes_ok": all_protected_hashes_ok,
            "approval_order_ok": all_approval_order_ok,
            "trace_ok": trace_ok,
        },
        "trace": {
            "ok": trace_ok,
            "message": trace_message,
            "entries": len(trace_records),
        },
        "agentteams": {
            "six_roles_run": False,
            "handoffs": [],
            "note": "真实六角色运行尚未开始；本状态不得作为 Matrix/MinIO 交接证据。",
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
    at004_workspace: str | Path | None = None,
    project_root: str | Path | None = None,
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

    trust_root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
    trust_at004 = Path(at004_workspace) if at004_workspace else trust_root / "demo" / "output-agentteams-at004"
    trust_at002 = Path(agentteams_v2_workspace) if agentteams_v2_workspace else trust_root / "demo" / "output-agentteams-at002"
    try:
        from labops.skill_registry import list_skills
        from labops.trust import build_trust_snapshot

        snapshot = build_trust_snapshot(trust_root, trust_at004, trust_at002)
        domains = snapshot["domains"]
        skills = dict(domains["skills"])
        skills["registered_count"] = len(list_skills(trust_root))
        trust_layer = {
            "contract": "Trust Contract v1",
            "state_machine": "Trust State Machine v1",
            "positioning": snapshot["positioning"],
            "contract_status": snapshot["contract_status"],
            "read_only": True,
            "evidence_chain": ["identity", "policy", "execution", "evidence", "audit"],
            "identity": domains["identity"],
            "skills": skills,
            "policy": domains["policy"],
            "execution": domains["execution"],
            "evidence": domains["evidence"],
            "audit": domains["audit"],
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        blocked = {
            "status": "BLOCKED",
            "summary": "Trust evidence is incomplete or unreadable",
            "checks": {"trust_snapshot_available": False},
            "evidence_refs": ["Trust Contract v1"],
            "limitations": ["Trust contract or archived evidence could not be validated"],
        }
        trust_layer = {
            "contract": "Trust Contract v1",
            "state_machine": "Trust State Machine v1",
            "positioning": "Trust Infrastructure for Production Agent Systems",
            "contract_status": "BLOCKED",
            "read_only": True,
            "evidence_chain": ["identity", "policy", "execution", "evidence", "audit"],
            "identity": blocked,
            "skills": {**blocked, "registered_count": 0},
            "policy": blocked,
            "execution": blocked,
            "evidence": blocked,
            "audit": blocked,
        }

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
        "trust_layer": trust_layer,
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
        "main_demo": build_at004_state(at004_workspace),
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
        snapshot_dir=fixtures / "project_snapshot_synthetic",
        audit_dir=fixtures / "synthetic_audit",
        verification_json=fixtures / "synthetic_snapshot_verification.json",
        allowed_list=project_root / "demo" / "synthetic_allowed_files.json",
        trace=TraceLog(workspace / "trace.jsonl"),
    )


class _ReviewerAPIError(ValueError):
    def __init__(self, http_status: int, code: str) -> None:
        super().__init__(code)
        self.http_status = http_status
        self.code = code


def _reviewer_session_root(sessions_root: Path, session_id: str) -> Path:
    if SESSION_ID.fullmatch(session_id) is None:
        raise _ReviewerAPIError(400, "INVALID_SESSION")
    root = sessions_root.resolve()
    candidate = (root / session_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _ReviewerAPIError(400, "INVALID_SESSION") from exc
    if not candidate.is_dir() or not (candidate / "session.json").is_file():
        raise _ReviewerAPIError(404, "SESSION_NOT_FOUND")
    return candidate


def _read_reviewer_json(path: Path, *, maximum_bytes: int = 2 * 1024 * 1024) -> dict:
    try:
        if path.stat().st_size > maximum_bytes:
            raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except _ReviewerAPIError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID") from exc
    if not isinstance(value, dict):
        raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID")
    return value


def _read_reviewer_events(path: Path, *, maximum_bytes: int = 2 * 1024 * 1024) -> list[dict]:
    try:
        if path.stat().st_size > maximum_bytes:
            raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID")
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except _ReviewerAPIError:
        raise
    except (OSError, UnicodeError) as exc:
        raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID") from exc
    if len(lines) > 4096:
        raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID")
    events: list[dict] = []
    seen: set[str] = set()
    for line in lines:
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID") from exc
        room_id = item.get("room_id") if isinstance(item, dict) else None
        actor = item.get("actor") if isinstance(item, dict) else None
        artifact_refs = item.get("artifact_refs") if isinstance(item, dict) else None
        hash_refs = item.get("hash_refs") if isinstance(item, dict) else None
        valid_artifacts = isinstance(artifact_refs, list) and len(artifact_refs) <= 8 and all(
            isinstance(ref, str)
            and 0 < len(ref) <= 512
            and not PurePosixPath(ref.replace("\\", "/")).is_absolute()
            and ".." not in PurePosixPath(ref.replace("\\", "/")).parts
            and re.match(r"^[A-Za-z]:/", ref.replace("\\", "/")) is None
            for ref in artifact_refs
        )
        valid_hashes = isinstance(hash_refs, list) and len(hash_refs) <= 8 and all(
            isinstance(ref, str) and re.fullmatch(r"[0-9a-fA-F]{64}", ref) is not None
            for ref in hash_refs
        )
        if (
            not isinstance(item, dict)
            or item.get("classification") != "NON_AUTHORITATIVE_UI_PROJECTION"
            or not isinstance(item.get("event_id"), str)
            or not item["event_id"].startswith("$")
            or not isinstance(item.get("kind"), str)
            or item["kind"] not in EVENT_KINDS
            or not isinstance(room_id, str)
            or not room_id.startswith("!")
            or actor not in set(ROLE_ORDER) | {"human-approver"}
            or not isinstance(item.get("workflow_from"), str)
            or not isinstance(item.get("workflow_to"), str)
            or item.get("evidence_state") != "OBSERVED"
            or not valid_artifacts
            or not valid_hashes
        ):
            raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID")
        if item["event_id"] in seen:
            continue
        seen.add(item["event_id"])
        events.append({
            "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
            "event_id": item["event_id"],
            "actor": actor,
            "kind": item["kind"],
            "timestamp": item.get("timestamp") if isinstance(item.get("timestamp"), str) else None,
            "workflow_from": item["workflow_from"],
            "workflow_to": item["workflow_to"],
            "evidence_state": "OBSERVED",
            "artifact_refs": list(artifact_refs),
            "hash_refs": [str(ref).lower() for ref in hash_refs],
        })
    return events


def _load_reviewer_snapshot(session_root: Path) -> dict:
    source_path = session_root / "observer" / "source_status.json"
    event_path = session_root / "observer" / "normalized_events.jsonl"
    source = _read_reviewer_json(source_path)
    events = _read_reviewer_events(event_path)
    if source and source.get("classification") != "NON_AUTHORITATIVE_UI_PROJECTION":
        raise _ReviewerAPIError(503, "REVIEWER_SOURCE_INVALID")
    source_status = source.get("source_status")
    connected = source.get("connected") is True and source_status in {"LIVE", "STALE"}
    return {
        "connected": connected,
        "last_success_at": source.get("last_success_at") if isinstance(source.get("last_success_at"), str) else None,
        "events": events,
    }


def _timeline_api_item(item: dict, *, sequence: int | None = None) -> dict:
    summary = {
        "kind": item.get("kind"),
        "timestamp": item.get("timestamp"),
        "actor": item.get("actor"),
        "workflow_from": item.get("workflow_from"),
        "workflow_to": item.get("workflow_to"),
        "evidence_state": item.get("evidence_state"),
        "source": item.get("source", "MATRIX"),
        "details": {
            "event_id": item.get("event_id"),
            "artifact_refs": item.get("artifact_refs") if isinstance(item.get("artifact_refs"), list) else [],
            "hash_refs": item.get("hash_refs") if isinstance(item.get("hash_refs"), list) else [],
            "state_transition": {
                "from": item.get("workflow_from"),
                "to": item.get("workflow_to"),
            },
        },
    }
    if sequence is not None:
        summary["sequence"] = sequence
    return summary


def _reviewer_status_payload(context: dict, session_id: str | None) -> dict:
    from labops.reviewer_state import build_reviewer_state

    mode = str(context["mode"]).lower()
    project_root = Path(context["project_root"]).resolve()
    sessions_root = Path(context["sessions_root"]).resolve()
    snapshot = None
    if mode == "live":
        if session_id is None:
            raise _ReviewerAPIError(400, "SESSION_REQUIRED")
        session_root = _reviewer_session_root(sessions_root, session_id)
        snapshot = _load_reviewer_snapshot(session_root)
    state = build_reviewer_state(
        project_root,
        sessions_root,
        session_id if mode == "live" else None,
        mode,
        snapshot,
    )
    state["timeline"] = [
        _timeline_api_item(item) for item in state.get("timeline", []) if isinstance(item, dict)
    ]
    return state


def _preflight_payload(context: dict) -> dict:
    configured = context.get("preflight")
    if callable(configured):
        configured = configured()
    configured = configured if isinstance(configured, dict) else {}
    status = configured.get("status")
    if status not in {"READY", "PARTIAL", "BLOCKED", "NOT_CHECKED"}:
        status = "NOT_CHECKED"
    requirements = configured.get("requirements")
    safe_requirements: dict[str, Any] = {}
    if isinstance(requirements, dict):
        for name, value in requirements.items():
            if isinstance(name, str) and isinstance(value, (bool, int)) and not isinstance(value, str):
                safe_requirements[name] = value
            elif isinstance(name, str) and value in {"READY", "BLOCKED", "MISSING", "NOT_CHECKED"}:
                safe_requirements[name] = value
    return {
        "read_only": True,
        "mode": str(context["mode"]).upper(),
        "status": status,
        "requirements": safe_requirements,
    }


def _reviewer_events_payload(context: dict, session_id: str | None, after: int) -> dict:
    if after < 0:
        raise _ReviewerAPIError(400, "INVALID_CURSOR")
    mode = str(context["mode"]).lower()
    if mode == "quick":
        state = _reviewer_status_payload(context, None)
        source_events = state.get("timeline", [])
        events = [dict(item) for item in source_events if isinstance(item, dict)]
    else:
        if session_id is None:
            raise _ReviewerAPIError(400, "SESSION_REQUIRED")
        session_root = _reviewer_session_root(Path(context["sessions_root"]), session_id)
        _read_reviewer_json(session_root / "observer" / "source_status.json")
        raw_events = _read_reviewer_events(session_root / "observer" / "normalized_events.jsonl")
        events = [_timeline_api_item(item, sequence=index) for index, item in enumerate(raw_events, 1)]
    page = [item for index, item in enumerate(events, 1) if index > after][:100]
    if mode == "quick":
        for index, item in enumerate(page, after + 1):
            item["sequence"] = index
    next_after = page[-1]["sequence"] if page else after
    return {
        "read_only": True,
        "mode": mode.upper(),
        "session_id": session_id if mode == "live" else None,
        "events": page,
        "next_after": next_after,
        "has_more": next_after < len(events),
    }


def make_handler(
    workspace: str | Path,
    checkpoint_workspace: str | Path | None = None,
    agentteams_v2_workspace: str | Path | None = None,
    agentteams_v3_workspace: str | Path | None = None,
    at004_workspace: str | Path | None = None,
    reviewer_context: dict | None = None,
):
    workspace = Path(workspace).resolve()
    checkpoint_workspace = Path(checkpoint_workspace).resolve() if checkpoint_workspace else None
    agentteams_v2_workspace = Path(agentteams_v2_workspace).resolve() if agentteams_v2_workspace else None
    agentteams_v3_workspace = Path(agentteams_v3_workspace).resolve() if agentteams_v3_workspace else None
    at004_workspace = Path(at004_workspace).resolve() if at004_workspace else None
    if reviewer_context is not None:
        required = {"project_root", "sessions_root", "mode"}
        if not isinstance(reviewer_context, dict) or not required.issubset(reviewer_context):
            raise ValueError("reviewer_context requires project_root, sessions_root and mode")
        if str(reviewer_context["mode"]).lower() not in {"quick", "live"}:
            raise ValueError("Reviewer mode must be quick or live")
        reviewer_context = dict(reviewer_context)
    dashboard_html = Path(__file__).with_name("dashboard.html")
    reviewer_html = Path(__file__).with_name("reviewer.html")

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
            target = urlsplit(self.path)
            path = target.path
            if path == "/":
                try:
                    body = dashboard_html.read_bytes()
                except OSError as exc:
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                self._send(200, "text/html; charset=utf-8", body)
            elif reviewer_context is not None and path == "/reviewer":
                try:
                    body = reviewer_html.read_bytes()
                except OSError:
                    self._json(500, {"ok": False, "error": "reviewer page unavailable"})
                    return
                self._send(200, "text/html; charset=utf-8", body)
            elif path == "/api/status":
                self._json(200, build_dashboard_state(workspace, checkpoint_workspace, agentteams_v2_workspace, agentteams_v3_workspace, at004_workspace))
            elif path == "/healthz":
                state = build_dashboard_state(workspace, checkpoint_workspace, agentteams_v2_workspace, agentteams_v3_workspace, at004_workspace)
                self._json(200 if state["ready"] else 503, {"ok": state["ready"], "service": "labops-guard"})
            elif reviewer_context is not None and path == "/api/reviewer/preflight":
                self._json(200, _preflight_payload(reviewer_context))
            elif reviewer_context is not None and path in {"/api/reviewer/status", "/api/reviewer/events"}:
                try:
                    query = parse_qs(target.query, keep_blank_values=True)
                    sessions = query.get("session", [])
                    if len(sessions) > 1:
                        raise _ReviewerAPIError(400, "INVALID_SESSION")
                    session_id = sessions[0] if sessions else None
                    if path == "/api/reviewer/status":
                        payload = _reviewer_status_payload(reviewer_context, session_id)
                    else:
                        cursors = query.get("after", ["0"])
                        if len(cursors) != 1:
                            raise _ReviewerAPIError(400, "INVALID_CURSOR")
                        try:
                            after = int(cursors[0])
                        except (TypeError, ValueError) as exc:
                            raise _ReviewerAPIError(400, "INVALID_CURSOR") from exc
                        payload = _reviewer_events_payload(reviewer_context, session_id, after)
                except _ReviewerAPIError as exc:
                    error = {
                        "read_only": True,
                        "status": "BLOCKED",
                        "error": exc.code,
                        "archived_replay_used": False,
                    }
                    self._json(exc.http_status, error)
                    return
                self._json(200, payload)
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def _reject_write(self) -> None:
            # Drain the request body before rejecting it. On Windows, closing a
            # socket with unread request bytes can reset the connection before
            # urllib receives the intended HTTP 405 response.
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 0:
                self.rfile.read(content_length)
            self._json(405, {"ok": False, "error": "dashboard is read-only"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            self._reject_write()

        def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
            self._reject_write()

        def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
            self._reject_write()

        def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
            self._reject_write()

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
    at004_workspace: str | Path | None = None,
) -> None:
    """Serve the dashboard until interrupted."""
    server = ThreadingHTTPServer((host, port), make_handler(workspace, checkpoint_workspace, agentteams_v2_workspace, agentteams_v3_workspace, at004_workspace))
    print(f"LabOps Guard dashboard: http://{host}:{port}")
    print(f"Workspace: {Path(workspace).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
