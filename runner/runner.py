"""Restricted, offline PyTorch CPU experiment runner.

The container accepts one structured ExperimentPlan and exposes no arbitrary
command execution. Inputs are mounted read-only; only /output and /tmp are
writable at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import torch


RUNNER_IMAGE = "labops/pytorch-cpu-runner:0.1.0"
PYTHON_VERSION = "3.11.15"
TORCH_VERSION = "2.5.1+cpu"
COMMAND_ALLOWLIST = {"evaluate_checkpoint"}
OUTPUT_FILES = ["run_result.json", "metrics.json", "stdout.log", "stderr.log"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_secret_key(value) -> bool:
    forbidden = ("api_key", "apikey", "token", "password", "credential", "secret")
    if isinstance(value, dict):
        return any(any(marker in str(key).lower() for marker in forbidden) or _contains_secret_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


def _data_fingerprint(project: Path, seed: int) -> str:
    sys.path.insert(0, str(project))
    try:
        from model import make_dataset  # type: ignore

        _, _, val_x, val_y = make_dataset(seed)
        digest = hashlib.sha256()
        digest.update(bytes(val_x.detach().cpu().contiguous().view(torch.uint8).reshape(-1).tolist()))
        digest.update(bytes(val_y.detach().cpu().contiguous().view(torch.uint8).reshape(-1).tolist()))
        return digest.hexdigest()
    finally:
        sys.path.pop(0)


def capability_check(plan: dict, project: Path, run: Path, output: Path) -> dict:
    budget = plan.get("budget", {})
    changes = plan.get("changes", [])
    config_path = run / "eval_config.json"
    config = _json(config_path) if config_path.is_file() else {}
    change = changes[0] if len(changes) == 1 else {}
    expected_change = {
        "file": "eval_config.json",
        "field": "checkpoint",
        "before": "checkpoints/last.pt",
        "after": "checkpoints/best.pt",
    }
    paths = [project / name for name in ("evaluate.py", "metric.py", "model.py")]
    checkpoints = [run / "checkpoints" / name for name in ("last.pt", "best.pt")]
    checks = {
        "runner_image": os.environ.get("LABOPS_RUNNER_IMAGE") == RUNNER_IMAGE,
        "python": sys.version.startswith(PYTHON_VERSION),
        "torch": torch.__version__ == TORCH_VERSION and not torch.cuda.is_available(),
        "checkpoint": all(path.is_file() and _inside(path, run) for path in checkpoints),
        "config": config.get("checkpoint") == expected_change["before"] and config.get("metric") == "accuracy",
        "paths": all(path.is_file() and _inside(path, project) for path in paths) and _inside(output, output),
        "resource_budget": budget.get("device") == "cpu" and budget.get("network") is False and 0 < int(budget.get("max_runtime_seconds", 0)) <= 30 and int(plan.get("success_criteria", {}).get("repeats", 0)) == 3,
        "command_allowlist": plan.get("command") in COMMAND_ALLOWLIST,
        "single_approved_change": change == expected_change,
        "no_credentials": not _contains_secret_key(plan),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "runtime": {"image": RUNNER_IMAGE, "python": sys.version.split()[0], "torch": torch.__version__, "cuda": torch.cuda.is_available(), "network": "none"},
    }


def _evaluate(project: Path, run: Path, timeout: int) -> tuple[dict | None, str, str, int]:
    command = [sys.executable, str(project / "evaluate.py"), "--run-dir", str(run)]
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(project), "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "LABOPS_NETWORK": "disabled", "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": ""}
    completed = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    result = json.loads(completed.stdout) if completed.returncode == 0 else None
    return result, completed.stdout, completed.stderr, completed.returncode


def run(plan_path: Path, project: Path, input_run: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    plan = _json(plan_path)
    capability = capability_check(plan, project, input_run, output)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    started = time.time()
    start_text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    status = "completed"
    return_code = 0
    baseline_values: list[float] = []
    candidate_values: list[float] = []

    metric_before = _sha256(project / "metric.py")
    model_before = _sha256(project / "model.py")
    seed = int(_json(input_run / "eval_config.json").get("seed", 0)) if (input_run / "eval_config.json").is_file() else 0
    data_before = _data_fingerprint(project, seed) if seed else ""

    if capability["status"] != "PASS":
        status = "rejected"
        return_code = 2
        stderr_parts.append("RuntimeCapabilityCheck failed: " + json.dumps(capability["checks"], sort_keys=True))
    else:
        sandbox = Path("/tmp/labops-sandbox")
        if sandbox.exists():
            shutil.rmtree(sandbox)
        shutil.copytree(input_run, sandbox)
        timeout = int(plan["budget"]["max_runtime_seconds"])
        for _ in range(int(plan["success_criteria"]["repeats"])):
            try:
                baseline, out, err, code = _evaluate(project, input_run, timeout)
            except subprocess.TimeoutExpired as exc:
                status, return_code = "timeout", -1
                stderr_parts.append(str(exc))
                break
            stdout_parts.append(out)
            stderr_parts.append(err)
            if code != 0 or baseline is None:
                status, return_code = "failed", code
                break
            baseline_values.append(float(baseline["accuracy"]))

            config_path = sandbox / "eval_config.json"
            config = _json(config_path)
            config["checkpoint"] = plan["changes"][0]["after"]
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            try:
                candidate, out, err, code = _evaluate(project, sandbox, timeout)
            except subprocess.TimeoutExpired as exc:
                status, return_code = "timeout", -1
                stderr_parts.append(str(exc))
                break
            stdout_parts.append(out)
            stderr_parts.append(err)
            if code != 0 or candidate is None:
                status, return_code = "failed", code
                break
            candidate_values.append(float(candidate["accuracy"]))

    metric_after = _sha256(project / "metric.py")
    model_after = _sha256(project / "model.py")
    data_after = _data_fingerprint(project, seed) if seed else ""
    ended = time.time()
    repeats = int(plan.get("success_criteria", {}).get("repeats", 0))
    metrics = {
        "baseline_accuracy_values": baseline_values,
        "candidate_accuracy_values": candidate_values,
        "baseline_accuracy": baseline_values[0] if baseline_values else None,
        "candidate_accuracy": candidate_values[0] if candidate_values else None,
        "reproducible": len(baseline_values) == repeats and len(candidate_values) == repeats and len(set(baseline_values)) == 1 and len(set(candidate_values)) == 1,
    }
    result = {
        "schema_version": "1.0",
        "task_id": plan.get("task_id"),
        "run_id": plan.get("run_id"),
        "incident_id": plan.get("incident_id"),
        "plan_id": plan.get("plan_id"),
        "command": plan.get("command"),
        "status": status,
        "start_time": start_text,
        "end_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended)),
        "duration_seconds": round(ended - started, 6),
        "return_code": return_code,
        "network": "none",
        "sandbox_only": True,
        "original_project_modified": False,
        "changed_paths": ["sandbox/eval_config.json:checkpoint"] if status == "completed" else [],
        "capability_check": capability,
        "metrics": metrics,
        "protected_hashes": {
            "metric_before": metric_before,
            "metric_after": metric_after,
            "metric_unchanged": metric_before == metric_after,
            "model_before": model_before,
            "model_after": model_after,
            "model_unchanged": model_before == model_after,
            "validation_data_before": data_before,
            "validation_data_after": data_after,
            "validation_data_unchanged": bool(data_before) and data_before == data_after,
        },
        "output_artifacts": [*OUTPUT_FILES, "artifact_manifest.json"],
    }
    (output / "run_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "stdout.log").write_text("\n".join(stdout_parts), encoding="utf-8")
    (output / "stderr.log").write_text("\n".join(stderr_parts), encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "run_id": plan.get("run_id"),
        "created_at": result["end_time"],
        "artifacts": {name: {"sha256": _sha256(output / name), "size": (output / name).stat().st_size} for name in OUTPUT_FILES},
        "protected_hashes": result["protected_hashes"],
    }
    (output / "artifact_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="/input/experiment_plan.json")
    parser.add_argument("--project", default="/input/project")
    parser.add_argument("--run", default="/input/run")
    parser.add_argument("--output", default="/output")
    args = parser.parse_args()
    return run(Path(args.plan).resolve(), Path(args.project).resolve(), Path(args.run).resolve(), Path(args.output).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
