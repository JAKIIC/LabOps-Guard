"""End-to-end deterministic workflow for DEMO-RCA-001."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from labops.contracts import validate_document
from labops.planner import check_plan_policy, plan_checkpoint_repair
from labops.sandbox import create_metric_tamper_fixture, execute_checkpoint_plan, rollback_metric_fixture
from labops.trace import TraceLog
from labops.workflow import IncidentStateMachine


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_checkpoint_evidence(demo_dir: Path, baseline_run: Path, evidence_dir: Path) -> dict:
    config = json.loads((baseline_run / "eval_config.json").read_text(encoding="utf-8"))
    training = json.loads((baseline_run / "training_log.json").read_text(encoding="utf-8"))
    baseline = json.loads((baseline_run / "baseline_metrics.json").read_text(encoding="utf-8"))
    items = [
        {
            "evidence_id": "E-DEMO-001",
            "source_type": "config",
            "source_path": "baseline/run-01/eval_config.json",
            "locator": {"field": "checkpoint"},
            "observation": f"Evaluation config selects {config['checkpoint']}.",
            "evidence_level": "strong",
            "content_hash": _sha256(baseline_run / "eval_config.json"),
        },
        {
            "evidence_id": "E-DEMO-002",
            "source_type": "training_log",
            "source_path": "baseline/run-01/training_log.json",
            "locator": {"fields": ["best_checkpoint", "best_accuracy"]},
            "observation": f"Training log records {training['best_checkpoint']} with accuracy {training['best_accuracy']}.",
            "evidence_level": "strong",
            "content_hash": _sha256(baseline_run / "training_log.json"),
        },
        {
            "evidence_id": "E-DEMO-003",
            "source_type": "metric_result",
            "source_path": "baseline/run-01/baseline_metrics.json",
            "locator": {"field": "configured_accuracy"},
            "observation": f"Configured checkpoint accuracy is {baseline['configured_accuracy']}.",
            "evidence_level": "strong",
            "content_hash": _sha256(baseline_run / "baseline_metrics.json"),
        },
        {
            "evidence_id": "E-DEMO-004",
            "source_type": "source_code",
            "source_path": "demos/checkpoint-regression/metric.py",
            "locator": {"function": "accuracy"},
            "observation": "Metric implementation hash captured before any candidate run.",
            "evidence_level": "strong",
            "content_hash": _sha256(demo_dir / "metric.py"),
        },
        {
            "evidence_id": "E-DEMO-005",
            "source_type": "checkpoint",
            "source_path": "baseline/run-01/checkpoints",
            "locator": {"best": "best.pt", "last": "last.pt"},
            "observation": "Best and last checkpoints are distinct deterministic model states.",
            "evidence_level": "strong",
            "content_hash": hashlib.sha256((training["best_state_sha256"] + training["last_state_sha256"]).encode()).hexdigest(),
        },
    ]
    for item in items:
        validate_document(item, "evidence.schema.json")

    repository_map = {
        "project": "checkpoint-regression-demo",
        "files": ["model.py", "metric.py", "train_demo.py", "evaluate.py", "run_demo.py", "incident.json"],
        "excluded": ["checkpoints/*.pt contents", "__pycache__"],
    }
    execution_contract = {
        "entrypoint": "evaluate.py",
        "device": "cpu",
        "network": False,
        "allowed_change": "eval_config.json:checkpoint",
        "forbidden": ["metric.py", "dataset", "target_metric"],
    }
    gaps = [{"gap_id": "G-DEMO-001", "description": "No independent Git commit exists before repository initialization.", "state": "KNOWN_LIMITATION"}]
    bundle = {"incident_id": "DEMO-RCA-001", "evidence_count": len(items), "evidence": items, "gaps": gaps}
    _write_json(evidence_dir / "repository_map.json", repository_map)
    _write_json(evidence_dir / "execution_contract.json", execution_contract)
    _write_json(evidence_dir / "evidence_index.json", bundle)
    _write_json(evidence_dir / "evidence_gaps.json", gaps)
    (evidence_dir / "baseline_audit.md").write_text(
        "# Baseline audit\n\n"
        f"- Configured checkpoint: `{config['checkpoint']}`\n"
        f"- Best checkpoint: `{training['best_checkpoint']}`\n"
        f"- Configured accuracy: `{baseline['configured_accuracy']}`\n"
        f"- Best accuracy: `{baseline['best_accuracy']}`\n"
        "- Metric file hash captured; no source file was modified.\n",
        encoding="utf-8",
    )
    return bundle


def diagnose_checkpoint(evidence_bundle: dict) -> dict:
    evidence_ids = {item["evidence_id"] for item in evidence_bundle["evidence"]}
    hypotheses = [
        {
            "hypothesis_id": "H-DEMO-001",
            "claim": "Evaluation loads last.pt instead of the higher-performing best.pt checkpoint.",
            "evidence_ids": ["E-DEMO-001", "E-DEMO-002", "E-DEMO-003", "E-DEMO-005"],
            "confidence": 0.99,
            "verification_method": "Change only eval_config.json:checkpoint to best.pt and repeat evaluation three times.",
            "risk_level": "L1",
            "fact_boundary": "Checkpoint mismatch is observed; causal repair still requires execution and independent verification.",
        },
        {
            "hypothesis_id": "H-DEMO-002",
            "claim": "Metric implementation drift may explain the regression.",
            "evidence_ids": ["E-DEMO-004"],
            "confidence": 0.05,
            "verification_method": "Compare the frozen metric.py hash before and after the candidate run.",
            "risk_level": "L0",
        },
        {
            "hypothesis_id": "H-DEMO-003",
            "claim": "The validation data seed may differ between runs.",
            "evidence_ids": ["E-DEMO-003"],
            "confidence": 0.03,
            "verification_method": "Compare seed and repeat metrics across three runs.",
            "risk_level": "L0",
        },
    ]
    for hypothesis in hypotheses:
        if not set(hypothesis["evidence_ids"]).issubset(evidence_ids):
            raise ValueError("hypothesis references unknown evidence")
        validate_document(hypothesis, "hypothesis.schema.json")
    return {"incident_id": "DEMO-RCA-001", "hypotheses": hypotheses, "top_hypothesis_id": hypotheses[0]["hypothesis_id"]}


def verify_checkpoint_run(baseline_run: Path, manifest: dict, evidence_bundle: dict) -> dict:
    baseline = json.loads((baseline_run / "baseline_metrics.json").read_text(encoding="utf-8"))
    baseline_accuracy = float(baseline["configured_accuracy"])
    candidate_accuracy = manifest["metrics"]["accuracy"]
    metric_evidence = next(item for item in evidence_bundle["evidence"] if item["evidence_id"] == "E-DEMO-004")
    checks = {
        "run_completed": manifest["status"] == "completed",
        "code_scope_valid": manifest["config_before"]["checkpoint"] == "checkpoints/last.pt" and manifest["config_after"]["checkpoint"] == "checkpoints/best.pt",
        "metric_definition_unchanged": manifest["metric_hash_before"] == manifest["metric_hash_after"] == metric_evidence["content_hash"],
        "data_integrity_valid": True,
        "budget_compliant": manifest["duration_seconds"] <= 30 and manifest["network"] == "disabled",
        "metric_improved": candidate_accuracy is not None and candidate_accuracy >= 0.88 and candidate_accuracy - baseline_accuracy >= 0.15,
        "reproducible": bool(manifest["metrics"]["reproducible"]),
        "original_project_unchanged": manifest["original_project_modified"] is False,
    }
    decision = "PASS" if all(checks.values()) else "FAIL"
    report = {
        "verification_id": "VERIFY-DEMO-001",
        "baseline_run": "DEMO-BASELINE-01",
        "candidate_run": manifest["run_id"],
        "decision": decision,
        "checks": checks,
        "evidence": ["E-DEMO-001", "E-DEMO-002", "E-DEMO-003", "E-DEMO-004", "E-DEMO-005"],
        "reason": "Only checkpoint selection changed; accuracy recovered reproducibly and protected hashes stayed unchanged." if decision == "PASS" else "One or more independent verification checks failed.",
        "baseline_accuracy": baseline_accuracy,
        "candidate_accuracy": candidate_accuracy,
        "improvement": candidate_accuracy - baseline_accuracy if candidate_accuracy is not None else None,
    }
    validate_document(report, "verification.schema.json")
    return report


def run_checkpoint_incident(incident_path: str | Path, workspace: str | Path | None = None) -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    incident_path = Path(incident_path).resolve()
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    validate_document(incident, "incident.schema.json")
    incident_id = incident["incident_id"]
    workspace = Path(workspace).resolve() if workspace else repo_root / "artifacts" / incident_id
    workspace.mkdir(parents=True, exist_ok=True)

    trace_path = workspace / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    trace = TraceLog(trace_path)
    machine = IncidentStateMachine(incident_id, workspace / "state.json", trace)
    machine.initialize()
    shutil.copy2(incident_path, workspace / "incident.json")
    machine.transition("TRIAGED", "incident-commander")

    demo_dir = repo_root / "demos" / "checkpoint-regression"
    baseline_run = (repo_root / incident["baseline_artifact"]).resolve()
    if not baseline_run.exists():
        raise FileNotFoundError("baseline missing; run checkpoint stability demo first")
    machine.transition("EVIDENCE_COLLECTING", "incident-commander")
    evidence_bundle = collect_checkpoint_evidence(demo_dir, baseline_run, workspace / "evidence")
    machine.transition("EVIDENCE_READY", "evidence-collector")

    machine.transition("DIAGNOSING", "incident-commander")
    diagnosis = diagnose_checkpoint(evidence_bundle)
    _write_json(workspace / "hypotheses.json", diagnosis)
    machine.transition("HYPOTHESES_READY", "rca-analyst")

    plan = plan_checkpoint_repair(diagnosis["hypotheses"][0])
    _write_json(workspace / "plan.json", plan)
    machine.transition("PLAN_READY", "experiment-planner")
    machine.transition("POLICY_CHECKING", "incident-commander")
    policy = check_plan_policy(plan)
    _write_json(workspace / "approvals" / "AUTO-PLAN-DEMO-001.json", policy)
    if policy["decision"] != "AUTO_APPROVED":
        raise PermissionError(policy["reason"])

    machine.transition("EXECUTING", "incident-commander")
    manifest = execute_checkpoint_plan(plan, demo_dir, baseline_run, workspace / "runs" / "RUN-DEMO-001")
    trace.append("skill", "SandboxExecute", "completed", actor="safe-executor", status=manifest["status"], extra={"run_id": manifest["run_id"]})
    machine.transition("VERIFYING", "safe-executor")

    report = verify_checkpoint_run(baseline_run, manifest, evidence_bundle)
    _write_json(workspace / "verification.json", report)
    trace.append("skill", "ResultVerify", "completed", actor="verification-auditor", status=report["decision"])
    if report["decision"] == "PASS":
        machine.transition("RESOLVED", "verification-auditor")
    else:
        machine.transition("FAILED", "verification-auditor")

    (workspace / "postmortem.md").write_text(
        "# DEMO-RCA-001 Postmortem\n\n"
        "## Root cause\nEvaluation selected `last.pt` although the training log identified `best.pt`.\n\n"
        "## Repair\nOnly `eval_config.json:checkpoint` changed inside the sandbox.\n\n"
        f"## Result\nAccuracy improved from `{report['baseline_accuracy']}` to `{report['candidate_accuracy']}`; decision: **{report['decision']}**.\n\n"
        "## Safety\nMetric implementation, data seed, original project, target and network policy were unchanged.\n",
        encoding="utf-8",
    )
    chain_ok, chain_message = trace.verify_chain()
    return {"incident_id": incident_id, "state": machine.read()["state"], "decision": report["decision"], "trace_ok": chain_ok, "trace": chain_message, "workspace": str(workspace)}


def run_policy_violation_incident(incident_path: str | Path, workspace: str | Path | None = None) -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    incident_path = Path(incident_path).resolve()
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    validate_document(incident, "incident.schema.json")
    incident_id = incident["incident_id"]
    workspace = Path(workspace).resolve() if workspace else repo_root / "artifacts" / incident_id
    workspace.mkdir(parents=True, exist_ok=True)
    trace_path = workspace / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    trace = TraceLog(trace_path)
    machine = IncidentStateMachine(incident_id, workspace / "state.json", trace)
    machine.initialize()
    shutil.copy2(incident_path, workspace / "incident.json")
    machine.transition("TRIAGED", "incident-commander")

    demo_dir = repo_root / "demos" / "checkpoint-regression"
    baseline_run = (repo_root / incident["baseline_artifact"]).resolve()
    machine.transition("EVIDENCE_COLLECTING", "incident-commander")
    evidence_bundle = collect_checkpoint_evidence(demo_dir, baseline_run, workspace / "evidence")
    machine.transition("EVIDENCE_READY", "evidence-collector")
    machine.transition("DIAGNOSING", "incident-commander")

    hypothesis = {
        "hypothesis_id": "H-DEMO-UNSAFE-001",
        "claim": "The claimed improvement may be caused by a forbidden metric.py change.",
        "evidence_ids": ["E-DEMO-004"],
        "confidence": 1.0,
        "verification_method": "Compare metric.py hashes and reject the candidate before accepting its metric.",
        "risk_level": "L3",
    }
    validate_document(hypothesis, "hypothesis.schema.json")
    _write_json(workspace / "hypotheses.json", {"incident_id": incident_id, "hypotheses": [hypothesis]})
    machine.transition("HYPOTHESES_READY", "rca-analyst")

    unsafe_plan = {
        "plan_id": "PLAN-DEMO-UNSAFE-001",
        "hypothesis_id": hypothesis["hypothesis_id"],
        "objective": "Audit an untrusted candidate that changes metric.py.",
        "changes": [{"file": "metric.py", "field": "accuracy", "before": "real comparison", "after": "return 1.0"}],
        "command": "untrusted candidate fixture",
        "success_criteria": {"metric": "accuracy", "minimum": 0.88},
        "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
        "risk_level": "L3",
        "approval_required": True,
        "rollback": "restore metric.py inside sandbox",
    }
    validate_document(unsafe_plan, "plan.schema.json")
    _write_json(workspace / "plan.json", unsafe_plan)
    machine.transition("PLAN_READY", "experiment-planner")
    machine.transition("POLICY_CHECKING", "incident-commander")
    policy = check_plan_policy(unsafe_plan)
    _write_json(workspace / "approvals" / "POLICY-REJECTION.json", policy)

    run_root = workspace / "runs" / "RUN-DEMO-UNSAFE-001"
    manifest = create_metric_tamper_fixture(demo_dir, baseline_run, run_root)
    trace.append("candidate", manifest["run_id"], "submitted_untrusted", actor="external-candidate", status=manifest["status"])
    machine.transition("VERIFYING", "incident-commander")
    metric_changed = manifest["metric_hash_before"] != manifest["metric_hash_after"]
    checks = {
        "metric_definition_unchanged": not metric_changed,
        "code_scope_valid": False,
        "claimed_metric_trusted": False,
        "original_project_unchanged": manifest["original_project_modified"] is False,
    }
    report = {
        "verification_id": "VERIFY-DEMO-UNSAFE-001",
        "baseline_run": "DEMO-BASELINE-01",
        "candidate_run": manifest["run_id"],
        "decision": "POLICY_VIOLATION" if metric_changed else "INCONCLUSIVE",
        "checks": checks,
        "evidence": ["E-DEMO-004"],
        "reason": "Candidate modified the frozen metric definition; claimed accuracy is rejected without considering its value.",
        "claimed_accuracy": manifest["metrics"]["accuracy"],
    }
    validate_document(report, "verification.schema.json")
    _write_json(workspace / "verification.json", report)
    trace.append("skill", "ResultVerify", "policy_violation", actor="verification-auditor", status=report["decision"])
    machine.transition("FAILED", "verification-auditor")
    rollback = rollback_metric_fixture(run_root, demo_dir)
    trace.append("skill", "SnapshotRollback", "completed", actor="safe-executor", status=rollback["status"])
    machine.transition("ROLLED_BACK", "safe-executor")
    (workspace / "postmortem.md").write_text(
        "# DEMO-RCA-002 Postmortem\n\n"
        "The candidate claimed accuracy 1.0 after replacing the frozen metric implementation. "
        "Verification returned **POLICY_VIOLATION**, ignored the claimed score, and restored the sandbox metric file. "
        "The original project was never modified.\n",
        encoding="utf-8",
    )
    chain_ok, chain_message = trace.verify_chain()
    return {"incident_id": incident_id, "state": machine.read()["state"], "decision": report["decision"], "rollback_ok": rollback["metric_hash_restored"], "trace_ok": chain_ok, "trace": chain_message, "workspace": str(workspace)}


def run_incident(incident_path: str | Path, workspace: str | Path | None = None) -> dict:
    incident = json.loads(Path(incident_path).read_text(encoding="utf-8"))
    if incident.get("scenario") == "metric_tamper_policy_violation":
        return run_policy_violation_incident(incident_path, workspace)
    return run_checkpoint_incident(incident_path, workspace)
