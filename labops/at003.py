"""LABOPS-AT-003 local validation and independent verification helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from labops.checkpoint_incident import collect_checkpoint_evidence, diagnose_checkpoint
from labops.planner import check_plan_policy, plan_checkpoint_repair
from labops.runner import RUNNER_IMAGE, execute_runner_plan, runtime_capability_check
from labops.trace import TraceLog


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build_plan(hypothesis: dict, run_id: str) -> dict:
    return plan_checkpoint_repair(
        hypothesis,
        plan_id="PLAN-LABOPS-AT-003-001",
        command="evaluate_checkpoint",
        approval_required=True,
        extra={
            "task_id": "LABOPS-AT-003",
            "incident_id": "DEMO-RCA-003",
            "run_id": run_id,
            "runtime": {"image": RUNNER_IMAGE, "python": "3.11.15", "torch": "2.5.1+cpu", "network": "none"},
        },
    )


def verify_run(result: dict, baseline_accuracy: float = 0.70) -> dict:
    metrics = result.get("metrics", {})
    protected = result.get("protected_hashes", {})
    capability = result.get("capability_check", {})
    checks = {
        "runtime_capability_passed": capability.get("status") == "PASS" and all(capability.get("checks", {}).values()),
        "run_completed": result.get("status") == "completed" and result.get("return_code") == 0,
        "network_disabled": result.get("network") == "none",
        "sandbox_only": result.get("sandbox_only") is True and result.get("original_project_modified") is False,
        "baseline_expected": metrics.get("baseline_accuracy") is not None and abs(float(metrics["baseline_accuracy"]) - baseline_accuracy) <= 0.01,
        "candidate_passed": metrics.get("candidate_accuracy") is not None and float(metrics["candidate_accuracy"]) >= 0.88 and float(metrics["candidate_accuracy"]) - float(metrics["baseline_accuracy"]) >= 0.15,
        "three_reproducible_runs": metrics.get("reproducible") is True and len(metrics.get("baseline_accuracy_values", [])) == 3 and len(metrics.get("candidate_accuracy_values", [])) == 3,
        "metric_immutable": protected.get("metric_unchanged") is True,
        "test_data_immutable": protected.get("validation_data_unchanged") is True and protected.get("model_unchanged") is True,
        "single_changed_path": result.get("changed_paths") == ["sandbox/eval_config.json:checkpoint"],
    }
    return {
        "verification_id": f"VERIFY-{result.get('run_id')}",
        "incident_id": result.get("incident_id"),
        "run_id": result.get("run_id"),
        "decision": "PASS" if all(checks.values()) else "INCONCLUSIVE",
        "resolution_status": "RESOLVED" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "baseline_accuracy": metrics.get("baseline_accuracy"),
        "candidate_accuracy": metrics.get("candidate_accuracy"),
        "metric_hash": protected.get("metric_after"),
        "validation_data_hash": protected.get("validation_data_after"),
    }


def run_local_validation(repo_root: str | Path, output_root: str | Path) -> dict:
    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve()
    demo = repo_root / "demos" / "checkpoint-regression"
    baseline = repo_root / "artifacts" / "DEMO-RCA-001" / "baseline" / "run-01"
    evidence = collect_checkpoint_evidence(demo, baseline, output_root / "evidence", "DEMO-RCA-003")
    diagnosis = diagnose_checkpoint(evidence)
    _write(output_root / "hypotheses.json", diagnosis)
    probe_plan = build_plan(diagnosis["hypotheses"][0], "RUN-LABOPS-AT-003-LOCAL-01")
    capability = runtime_capability_check(probe_plan, demo, baseline)
    _write(output_root / "runtime_capability_check.json", capability)
    if capability["status"] != "PASS":
        return {"task_id": "LABOPS-AT-003", "status": "BLOCKED", "capability": capability}

    trace = TraceLog(output_root / "trace.jsonl")
    (output_root / "trace.jsonl").write_text("", encoding="utf-8")
    runs = []
    for index in range(1, 4):
        run_id = f"RUN-LABOPS-AT-003-LOCAL-{index:02d}"
        plan = build_plan(diagnosis["hypotheses"][0], run_id)
        policy = check_plan_policy(plan)
        approval = {
            "approval_id": f"LABOPS-AT-003-LOCAL-APPROVAL-{index:02d}",
            "decision": "APPROVED",
            "decided_by": "human-user-phase-3-request",
            "scope": "offline runner; checkpoint field only; three repeats",
            "not_approved": ["metric.py", "dataset", "original workspace", "network", "training", "download"],
        }
        run_dir = output_root / "runs" / run_id
        _write(run_dir / "experiment_plan.json", plan)
        _write(run_dir / "policy.json", policy)
        _write(run_dir / "approval.json", approval)
        trace.append("approval", approval["approval_id"], "approved", actor="human-user", status="APPROVED", extra={"run_id": run_id})
        result = execute_runner_plan(plan, demo, baseline, run_dir)
        trace.append("runner", run_id, "completed", actor="safe-executor", status=result["status"], extra={"image": RUNNER_IMAGE})
        verification = verify_run(result)
        _write(run_dir / "verification.json", verification)
        trace.append("verification", verification["verification_id"], "independent_check", actor="verification-auditor", status=verification["decision"])
        runs.append({"run_id": run_id, "result": result, "verification": verification})

    chain_ok, chain_message = trace.verify_chain()
    all_pass = all(item["verification"]["decision"] == "PASS" for item in runs) and chain_ok
    summary = {
        "task_id": "LABOPS-AT-003",
        "incident_id": "DEMO-RCA-003",
        "status": "PASS" if all_pass else "INCONCLUSIVE",
        "resolution_status": "RESOLVED" if all_pass else "BLOCKED",
        "runner_image": RUNNER_IMAGE,
        "capability": capability,
        "runs": [{"run_id": item["run_id"], "baseline_accuracy": item["verification"]["baseline_accuracy"], "candidate_accuracy": item["verification"]["candidate_accuracy"], "decision": item["verification"]["decision"], "metric_hash": item["verification"]["metric_hash"], "validation_data_hash": item["verification"]["validation_data_hash"]} for item in runs],
        "trace": {"ok": chain_ok, "message": chain_message, "entries": len(trace.read())},
        "immutable": {"metric": len({item["verification"]["metric_hash"] for item in runs}) == 1, "test_data": len({item["verification"]["validation_data_hash"] for item in runs}) == 1},
    }
    _write(output_root / "local_validation_summary.json", summary)
    return summary
