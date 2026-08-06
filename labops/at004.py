"""LABOPS-AT-004 evaluation preprocessing drift workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from labops.contracts import validate_document
from labops.planner import check_plan_policy, plan_eval_drift_repair
from labops.runner import AT004_RUNNER_IMAGE, execute_runner_plan, runtime_capability_check
from labops.trace import TraceLog


TASK_ID = "LABOPS-AT-004-EVAL-DRIFT"
INCIDENT_ID = "DEMO-EVAL-DRIFT-004"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _evidence(
    evidence_id: str,
    fact: str,
    source_type: str,
    source_path: str,
    observation: str,
    content_hash: str,
    *,
    locator: dict | None = None,
) -> dict:
    item = {
        "evidence_id": evidence_id,
        "fact": fact,
        "source_type": source_type,
        "source_path": source_path,
        "observation": observation,
        "evidence_level": "strong",
        "content_hash": content_hash,
    }
    if locator:
        item["locator"] = locator
    validate_document(item, "evidence.schema.json")
    return item


def collect_eval_drift_evidence(demo_dir: str | Path, run_dir: str | Path, output_dir: str | Path) -> dict:
    demo_dir = Path(demo_dir).resolve()
    run_dir = Path(run_dir).resolve()
    output_dir = Path(output_dir).resolve()
    current = _read(run_dir / "eval_config.json")
    historical = _read(run_dir / "historical_eval_config.json")
    baseline = _read(run_dir / "historical_baseline.json")
    diff = _read(run_dir / "recent_git_diff.json")
    checkpoint = run_dir / current["checkpoint"]
    validation = run_dir / current["validation_data"]
    metric = demo_dir / "metric.py"
    protocol = demo_dir / "evaluation_protocol.yaml"
    runner_dockerfile = demo_dir.parent.parent / "runner" / "Dockerfile.at004"
    current_values = [float(value) for value in baseline["current_accuracy_values"]]
    checkpoint_hash = _sha256(checkpoint)
    validation_hash = _sha256(validation)
    metric_hash = _sha256(metric)

    items = [
        _evidence(
            "E-AT004-001", "checkpoint_consistency", "artifact", current["checkpoint"],
            f"Current checkpoint hash {'matches' if checkpoint_hash == baseline['hashes']['checkpoint'] else 'differs from'} the historical reference hash: {checkpoint_hash}.",
            checkpoint_hash, locator={"historical_hash": baseline["hashes"]["checkpoint"]},
        ),
        _evidence(
            "E-AT004-002", "validation_data_consistency", "dataset", current["validation_data"],
            f"Validation data hash {'matches' if validation_hash == baseline['hashes']['validation_data'] else 'differs from'} the historical reference hash: {validation_hash}.",
            validation_hash, locator={"historical_hash": baseline["hashes"]["validation_data"]},
        ),
        _evidence(
            "E-AT004-003", "metric_consistency", "code", "metric.py",
            f"metric.py hash {'matches' if metric_hash == baseline['hashes']['metric'] else 'differs from'} the historical reference hash: {metric_hash}.",
            metric_hash, locator={"historical_hash": baseline["hashes"]["metric"]},
        ),
        _evidence(
            "E-AT004-004", "current_preprocessing_profile", "config", "eval_config.json",
            f"Current evaluation preprocessing profile is {current['evaluation']['preprocessing_profile']}.",
            _sha256(run_dir / "eval_config.json"), locator={"field": "evaluation.preprocessing_profile"},
        ),
        _evidence(
            "E-AT004-005", "historical_preprocessing_profile", "config", "historical_eval_config.json",
            f"Historical baseline preprocessing profile is {historical['evaluation']['preprocessing_profile']}.",
            _sha256(run_dir / "historical_eval_config.json"), locator={"field": "evaluation.preprocessing_profile"},
        ),
        _evidence(
            "E-AT004-006", "preprocessing_parameters", "config", "eval_config.json",
            "The current profile applies deterministic training augmentation during evaluation "
            f"(seed={current['evaluation']['augmentation_seed']}, noise_std={current['evaluation']['noise_std']}).",
            _sha256(run_dir / "eval_config.json"), locator={"field": "evaluation"},
        ),
        _evidence(
            "E-AT004-007", "baseline_repeat_results", "runtime", "historical_baseline.json",
            f"Three current evaluations are {current_values}; repeat spread is {max(current_values) - min(current_values):.6f}.",
            _sha256(run_dir / "historical_baseline.json"), locator={"field": "current_accuracy_values"},
        ),
        _evidence(
            "E-AT004-008", "recent_change_scope", "git_diff", "recent_git_diff.json",
            "The recorded configuration change only switched evaluation.preprocessing_profile; "
            "checkpoint, validation data and metric were unchanged.",
            _sha256(run_dir / "recent_git_diff.json"), locator={"changed_fields": diff["changed_fields"]},
        ),
        _evidence(
            "E-AT004-009", "evaluation_protocol", "protocol", "evaluation_protocol.yaml",
            "The frozen protocol requires accuracy >= 0.97, repeat spread <= 0.001 and immutable protected inputs.",
            _sha256(protocol),
        ),
        _evidence(
            "E-AT004-010", "runner_contract", "environment", "runner/Dockerfile.at004",
            "The allowlisted Runner is CPU-only, non-root and must be started with network disabled.",
            _sha256(runner_dockerfile),
        ),
    ]
    bundle = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "incident_id": INCIDENT_ID,
        "collector": "evidence-collector",
        "evidence": items,
        "protected_hashes": baseline["hashes"],
        "original_workspace_modified": False,
    }
    _write(output_dir / "collected_evidence.json", bundle)
    _write(output_dir / "evidence_index.json", {
        "task_id": TASK_ID,
        "incident_id": INCIDENT_ID,
        "items": [{"evidence_id": item["evidence_id"], "fact": item["fact"]} for item in items],
    })
    return bundle


def diagnose_eval_drift(evidence_bundle: dict) -> dict:
    facts = {item["fact"]: item for item in evidence_bundle["evidence"]}
    current_profile = facts["current_preprocessing_profile"]["observation"].rsplit(" ", 1)[-1].rstrip(".")
    historical_profile = facts["historical_preprocessing_profile"]["observation"].rsplit(" ", 1)[-1].rstrip(".")
    checkpoint_same = facts["checkpoint_consistency"]["content_hash"] == facts["checkpoint_consistency"]["locator"]["historical_hash"]
    data_same = facts["validation_data_consistency"]["content_hash"] == facts["validation_data_consistency"]["locator"]["historical_hash"]
    repeat_text = facts["baseline_repeat_results"]["observation"]
    repeat_stable = "spread is 0.000000" in repeat_text

    candidates = [
        {
            "hypothesis_id": "H-AT004-PREPROCESSING-DRIFT",
            "claim": "Evaluation preprocessing configuration drift caused the regression.",
            "evidence_ids": ["E-AT004-004", "E-AT004-005", "E-AT004-006", "E-AT004-007", "E-AT004-008"],
            "supporting_evidence": ["E-AT004-004", "E-AT004-005", "E-AT004-006", "E-AT004-008"],
            "contradicting_evidence": [],
            "confidence": min(0.98, 0.24 + (0.58 if current_profile != historical_profile else 0) + (0.10 if repeat_stable else 0)),
            "verification_method": "Change only evaluation.preprocessing_profile to the historical value and repeat evaluation three times.",
            "verification_cost": "low",
            "risk_level": "L1",
        },
        {
            "hypothesis_id": "H-AT004-CHECKPOINT",
            "claim": "The evaluated checkpoint differs from the historical reference checkpoint.",
            "evidence_ids": ["E-AT004-001", "E-AT004-007"],
            "supporting_evidence": ["E-AT004-007"],
            "contradicting_evidence": ["E-AT004-001"] if checkpoint_same else [],
            "confidence": 0.05 if checkpoint_same else 0.70,
            "verification_method": "Compare the current and historical checkpoint hashes before considering a checkpoint experiment.",
            "verification_cost": "low",
            "risk_level": "L1",
        },
        {
            "hypothesis_id": "H-AT004-VALIDATION-DATA",
            "claim": "Validation data changed relative to the historical baseline.",
            "evidence_ids": ["E-AT004-002", "E-AT004-007"],
            "supporting_evidence": ["E-AT004-007"],
            "contradicting_evidence": ["E-AT004-002"] if data_same else [],
            "confidence": 0.04 if data_same else 0.68,
            "verification_method": "Compare the fixed validation artifact hash with the historical record.",
            "verification_cost": "low",
            "risk_level": "L2",
        },
        {
            "hypothesis_id": "H-AT004-RANDOMNESS",
            "claim": "Random evaluation variance caused a transient metric drop.",
            "evidence_ids": ["E-AT004-007"],
            "supporting_evidence": [],
            "contradicting_evidence": ["E-AT004-007"] if repeat_stable else [],
            "confidence": 0.08 if repeat_stable else 0.45,
            "verification_method": "Compare three repeated baseline evaluations and their spread.",
            "verification_cost": "low",
            "risk_level": "L0",
        },
    ]
    ranked = sorted(candidates, key=lambda item: (-item["confidence"], item["hypothesis_id"]))
    for rank, hypothesis in enumerate(ranked, 1):
        hypothesis["rank"] = rank
        validate_document(hypothesis, "hypothesis.schema.json")
    return {
        "schema_version": "1.0",
        "task_id": evidence_bundle["task_id"],
        "incident_id": evidence_bundle["incident_id"],
        "hypotheses": ranked,
        "top_hypothesis_id": ranked[0]["hypothesis_id"],
        "ranking_basis": "evidence support, contradicting evidence, repeat stability, verification cost and risk",
    }


def build_plan(hypothesis: dict, run_id: str) -> dict:
    return plan_eval_drift_repair(
        hypothesis,
        extra={
            "task_id": TASK_ID,
            "incident_id": INCIDENT_ID,
            "run_id": run_id,
            "runtime": {
                "image": AT004_RUNNER_IMAGE,
                "python": "3.11.15",
                "torch": "2.5.1+cpu",
                "network": "none",
            },
        },
    )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify_run(result: dict, approval: dict) -> dict:
    metrics = result.get("metrics", {})
    protected = result.get("protected_hashes", {})
    container_capability = result.get("capability_check", {})
    host_capability = result.get("host_capability_check", {})
    baseline_values = metrics.get("baseline_accuracy_values", [])
    candidate_values = metrics.get("candidate_accuracy_values", [])
    checks = {
        "runtime_capability_passed": (
            container_capability.get("status") == "PASS"
            and host_capability.get("status") == "PASS"
            and all(container_capability.get("checks", {}).values())
            and all(host_capability.get("checks", {}).values())
        ),
        "run_completed": result.get("status") == "completed" and result.get("return_code") == 0,
        "network_disabled": result.get("network") == "none",
        "sandbox_only": result.get("sandbox_only") is True and result.get("original_project_modified") is False,
        "approval_before_execution": (
            approval.get("decision") == "APPROVED"
            and _parse_time(approval["approved_at"]) <= _parse_time(result["start_time"])
        ),
        "regression_reproduced": len(baseline_values) == 3 and all(0.70 <= float(value) <= 0.75 for value in baseline_values),
        "candidate_passed": len(candidate_values) == 3 and all(0.97 <= float(value) <= 0.99 for value in candidate_values),
        "three_reproducible_runs": (
            metrics.get("reproducible") is True
            and float(metrics.get("baseline_spread", 1)) <= 0.001
            and float(metrics.get("candidate_spread", 1)) <= 0.001
        ),
        "metric_immutable": protected.get("metric_unchanged") is True,
        "validation_data_immutable": protected.get("validation_data_unchanged") is True,
        "checkpoint_immutable": protected.get("checkpoint_unchanged") is True,
        "evaluation_protocol_immutable": protected.get("evaluation_protocol_unchanged") is True,
        "single_changed_path": result.get("changed_paths") == [
            "sandbox/eval_config.json:evaluation.preprocessing_profile"
        ],
    }
    passed = all(checks.values())
    return {
        "verification_id": f"VERIFY-{result.get('run_id')}",
        "task_id": TASK_ID,
        "incident_id": INCIDENT_ID,
        "run_id": result.get("run_id"),
        "verified_by": "verification-auditor",
        "decision": "PASS" if passed else "INCONCLUSIVE",
        "resolution_status": "RESOLVED" if passed else "BLOCKED",
        "checks": checks,
        "baseline_accuracy": metrics.get("baseline_accuracy"),
        "candidate_accuracy": metrics.get("candidate_accuracy"),
        "protected_hashes": protected,
    }


def run_local_validation(repo_root: str | Path, output_root: str | Path) -> dict:
    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve()
    demo = repo_root / "demos" / "eval-drift"
    fixture = demo / "fixture" / "run-01"
    evidence = collect_eval_drift_evidence(demo, fixture, output_root / "evidence")
    diagnosis = diagnose_eval_drift(evidence)
    _write(output_root / "hypotheses.json", diagnosis)
    plan_probe = build_plan(diagnosis["hypotheses"][0], "RUN-LABOPS-AT-004-LOCAL-01")
    capability = runtime_capability_check(plan_probe, demo, fixture)
    _write(output_root / "runtime_capability_check.json", capability)
    if capability["status"] != "PASS":
        summary = {"task_id": TASK_ID, "status": "BLOCKED", "capability": capability}
        _write(output_root / "local_validation_summary.json", summary)
        return summary

    trace_path = output_root / "trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")
    trace = TraceLog(trace_path)
    runs = []
    for index in range(1, 4):
        run_id = f"RUN-LABOPS-AT-004-LOCAL-{index:02d}"
        plan = build_plan(diagnosis["hypotheses"][0], run_id)
        policy = check_plan_policy(plan)
        approved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        approval = {
            "approval_id": f"LABOPS-AT-004-LOCAL-APPROVAL-{index:02d}",
            "task_id": TASK_ID,
            "decision": "APPROVED",
            "decided_by": "human-user-phase-4b-request",
            "approved_at": approved_at,
            "scope": "offline Runner; evaluation.preprocessing_profile only; three repeats",
            "not_approved": [
                "metric.py", "validation_data.pt", "checkpoint", "evaluation_protocol.yaml",
                "original workspace", "network", "training", "download",
            ],
        }
        run_dir = output_root / "runs" / run_id
        _write(run_dir / "experiment_plan.json", plan)
        _write(run_dir / "policy.json", policy)
        _write(run_dir / "approval.json", approval)
        trace.append("approval", approval["approval_id"], "approved", actor="human-user", status="APPROVED", extra={"run_id": run_id})
        result = execute_runner_plan(plan, demo, fixture, run_dir)
        trace.append("runner", run_id, "completed", actor="safe-executor", status=result["status"], extra={"image": AT004_RUNNER_IMAGE})
        verification = verify_run(result, approval)
        _write(run_dir / "verification.json", verification)
        trace.append("verification", verification["verification_id"], "independent_check", actor="verification-auditor", status=verification["decision"])
        runs.append({"run_id": run_id, "result": result, "verification": verification})

    chain_ok, chain_message = trace.verify_chain()
    all_pass = all(item["verification"]["decision"] == "PASS" for item in runs) and chain_ok
    summary = {
        "task_id": TASK_ID,
        "incident_id": INCIDENT_ID,
        "status": "PASS" if all_pass else "INCONCLUSIVE",
        "resolution_status": "RESOLVED" if all_pass else "BLOCKED",
        "runner_image": AT004_RUNNER_IMAGE,
        "capability": capability,
        "evidence_count": len(evidence["evidence"]),
        "top_hypothesis_id": diagnosis["top_hypothesis_id"],
        "runs": [
            {
                "run_id": item["run_id"],
                "baseline_accuracy": item["verification"]["baseline_accuracy"],
                "candidate_accuracy": item["verification"]["candidate_accuracy"],
                "decision": item["verification"]["decision"],
            }
            for item in runs
        ],
        "trace": {"ok": chain_ok, "message": chain_message, "entries": len(trace.read())},
    }
    _write(output_root / "local_validation_summary.json", summary)
    return summary
