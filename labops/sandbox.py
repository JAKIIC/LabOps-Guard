"""Isolated executor for the checkpoint regression demo."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from labops.contracts import validate_document


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _safe_reset_directory(path: Path, boundary: Path) -> None:
    if not _inside(path, boundary) or path.resolve() == boundary.resolve():
        raise PermissionError("refusing to reset directory outside generated run boundary")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def execute_checkpoint_plan(
    plan: dict,
    demo_source: str | Path,
    baseline_run: str | Path,
    run_root: str | Path,
    timeout_seconds: int = 30,
) -> dict:
    demo_source = Path(demo_source).resolve()
    baseline_run = Path(baseline_run).resolve()
    run_root = Path(run_root).resolve()
    run_root.parent.mkdir(parents=True, exist_ok=True)
    _safe_reset_directory(run_root, run_root.parent)
    project_copy = run_root / "project"
    run_copy = run_root / "run"
    project_copy.mkdir()

    source_files = ["evaluate.py", "metric.py", "model.py"]
    for name in source_files:
        shutil.copy2(demo_source / name, project_copy / name)
    shutil.copytree(baseline_run, run_copy)

    metric_before = sha256(demo_source / "metric.py")
    config_path = run_copy / "eval_config.json"
    config_before = json.loads(config_path.read_text(encoding="utf-8"))
    change = plan["changes"][0]
    if change != {
        "file": "eval_config.json",
        "field": "checkpoint",
        "before": "checkpoints/last.pt",
        "after": "checkpoints/best.pt",
    }:
        raise PermissionError("executor accepts only the approved checkpoint field change")
    if config_before.get("checkpoint") != change["before"]:
        raise RuntimeError("sandbox precondition does not match plan")
    config_after = {**config_before, "checkpoint": change["after"]}
    config_path.write_text(json.dumps(config_after, indent=2), encoding="utf-8")
    (run_root / "patch.diff").write_text(
        "--- run/eval_config.json\n+++ run/eval_config.json\n"
        f"-  \"checkpoint\": \"{change['before']}\"\n"
        f"+  \"checkpoint\": \"{change['after']}\"\n",
        encoding="utf-8",
    )

    command = [sys.executable, str(project_copy / "evaluate.py"), "--run-dir", str(run_copy)]
    candidate_values: list[float] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    started = time.time()
    start_text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    status = "completed"
    return_code = 0
    env = dict(os.environ)
    env.update({"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "*", "LABOPS_NETWORK": "disabled"})
    try:
        for _ in range(int(plan["success_criteria"]["repeats"])):
            completed = subprocess.run(
                command,
                cwd=project_copy,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                check=False,
            )
            return_code = completed.returncode
            stdout_parts.append(completed.stdout)
            stderr_parts.append(completed.stderr)
            if completed.returncode != 0:
                status = "failed"
                break
            candidate_values.append(float(json.loads(completed.stdout)["accuracy"]))
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        return_code = -1
        stderr_parts.append(str(exc))

    ended = time.time()
    (run_root / "stdout.log").write_text("\n".join(stdout_parts), encoding="utf-8")
    (run_root / "stderr.log").write_text("\n".join(stderr_parts), encoding="utf-8")
    metrics = {
        "accuracy_values": candidate_values,
        "accuracy": candidate_values[0] if candidate_values else None,
        "reproducible": len(set(candidate_values)) == 1 and len(candidate_values) == int(plan["success_criteria"]["repeats"]),
    }
    (run_root / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest = {
        "run_id": run_root.name,
        "incident_id": "DEMO-RCA-001",
        "plan_id": plan["plan_id"],
        "command": " ".join(command),
        "status": status,
        "start_time": start_text,
        "end_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended)),
        "duration_seconds": round(ended - started, 6),
        "metrics": metrics,
        "output_artifacts": ["patch.diff", "stdout.log", "stderr.log", "metrics.json"],
        "return_code": return_code,
        "network": "disabled",
        "original_project_modified": False,
        "metric_hash_before": metric_before,
        "metric_hash_after": sha256(project_copy / "metric.py"),
        "config_before": config_before,
        "config_after": config_after,
    }
    validate_document(manifest, "run.schema.json")
    (run_root / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def rollback_sandbox(run_root: str | Path) -> dict:
    run_root = Path(run_root).resolve()
    run_copy = run_root / "run"
    config_path = run_copy / "eval_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["checkpoint"] = "checkpoints/last.pt"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    result = {"status": "ROLLED_BACK", "checkpoint": config["checkpoint"], "sandbox_only": True}
    (run_root / "rollback.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def create_metric_tamper_fixture(
    demo_source: str | Path,
    baseline_run: str | Path,
    run_root: str | Path,
) -> dict:
    """Create an isolated untrusted candidate for verifier testing.

    This is a fixture representing a candidate submitted from outside the safe
    executor. It never modifies the source project.
    """
    demo_source = Path(demo_source).resolve()
    baseline_run = Path(baseline_run).resolve()
    run_root = Path(run_root).resolve()
    run_root.parent.mkdir(parents=True, exist_ok=True)
    _safe_reset_directory(run_root, run_root.parent)
    project_copy = run_root / "project"
    run_copy = run_root / "run"
    project_copy.mkdir()
    for name in ["evaluate.py", "metric.py", "model.py"]:
        shutil.copy2(demo_source / name, project_copy / name)
    shutil.copytree(baseline_run, run_copy)

    metric_before = sha256(demo_source / "metric.py")
    tampered_metric = project_copy / "metric.py"
    tampered_metric.write_text(
        '"""UNTRUSTED POLICY-VIOLATION FIXTURE."""\n\n'
        "def accuracy(logits, labels):\n"
        "    return 1.0\n",
        encoding="utf-8",
    )
    metric_after = sha256(tampered_metric)
    command = [sys.executable, str(project_copy / "evaluate.py"), "--run-dir", str(run_copy)]
    completed = subprocess.run(command, cwd=project_copy, capture_output=True, text=True, timeout=30, check=False)
    claimed = json.loads(completed.stdout)["accuracy"] if completed.returncode == 0 else None
    (run_root / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run_root / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    manifest = {
        "run_id": run_root.name,
        "incident_id": "DEMO-RCA-002",
        "plan_id": "PLAN-DEMO-UNSAFE-001",
        "command": " ".join(command),
        "status": "completed" if completed.returncode == 0 else "failed",
        "start_time": "fixture",
        "end_time": "fixture",
        "duration_seconds": 0.0,
        "metrics": {"accuracy": claimed},
        "output_artifacts": ["stdout.log", "stderr.log"],
        "return_code": completed.returncode,
        "untrusted_candidate": True,
        "original_project_modified": False,
        "metric_hash_before": metric_before,
        "metric_hash_after": metric_after,
    }
    validate_document(manifest, "run.schema.json")
    (run_root / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def rollback_metric_fixture(run_root: str | Path, demo_source: str | Path) -> dict:
    run_root = Path(run_root).resolve()
    demo_source = Path(demo_source).resolve()
    target = run_root / "project" / "metric.py"
    shutil.copy2(demo_source / "metric.py", target)
    expected = sha256(demo_source / "metric.py")
    actual = sha256(target)
    result = {"status": "ROLLED_BACK", "metric_hash_restored": actual == expected, "sandbox_only": True}
    (run_root / "rollback.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
