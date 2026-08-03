"""Host-side adapter for the restricted PyTorch CPU Runner container."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from labops.contracts import validate_document
from labops.planner import check_plan_policy


RUNNER_IMAGE = "labops/pytorch-cpu-runner:0.1.0"
RUNNER_LABELS = {
    "io.labops.runner.image": RUNNER_IMAGE,
    "io.labops.runner.python": "3.11.15",
    "io.labops.runner.torch": "2.5.1+cpu",
    "io.labops.runner.network-runtime": "none",
}


def docker_binary() -> str:
    configured = os.environ.get("LABOPS_DOCKER_BIN")
    if configured:
        return configured
    found = shutil.which("docker")
    if found:
        return found
    windows_default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
    if windows_default.is_file():
        return str(windows_default)
    raise FileNotFoundError("Docker CLI not found; set LABOPS_DOCKER_BIN")


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def runtime_capability_check(plan: dict, demo_source: str | Path, baseline_run: str | Path, image: str = RUNNER_IMAGE) -> dict:
    validate_document(plan, "plan.schema.json")
    demo_source = Path(demo_source).resolve()
    baseline_run = Path(baseline_run).resolve()
    config_path = baseline_run / "eval_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    policy = check_plan_policy(plan)
    docker = docker_binary()
    inspect = _run([docker, "image", "inspect", image, "--format", "{{json .Config.Labels}}"])
    labels = json.loads(inspect.stdout) if inspect.returncode == 0 and inspect.stdout.strip() else {}
    probe = _run([
        docker, "run", "--rm", "--network", "none", "--entrypoint", "python", image, "-B", "-c",
        "import json,sys,torch;print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__,'cuda':torch.cuda.is_available()}))",
    ]) if inspect.returncode == 0 else None
    runtime = json.loads(probe.stdout) if probe and probe.returncode == 0 and probe.stdout.strip() else {}
    budget = plan.get("budget", {})
    change = plan.get("changes", [{}])[0]
    checks = {
        "runner_image": inspect.returncode == 0 and all(labels.get(key) == value for key, value in RUNNER_LABELS.items()),
        "torch": runtime.get("torch") == RUNNER_LABELS["io.labops.runner.torch"] and runtime.get("cuda") is False,
        "checkpoint": all((baseline_run / "checkpoints" / name).is_file() and _inside(baseline_run / "checkpoints" / name, baseline_run) for name in ("last.pt", "best.pt")),
        "config": config.get("checkpoint") == "checkpoints/last.pt" and config.get("metric") == "accuracy",
        "paths": all((demo_source / name).is_file() and _inside(demo_source / name, demo_source) for name in ("evaluate.py", "metric.py", "model.py")),
        "resource_budget": budget.get("device") == "cpu" and budget.get("network") is False and 0 < int(budget.get("max_runtime_seconds", 0)) <= 30 and int(plan.get("success_criteria", {}).get("repeats", 0)) == 3,
        "command_allowlist": plan.get("command") == "evaluate_checkpoint",
        "plan_policy": policy.get("decision") == "AUTO_APPROVED" and change.get("file") == "eval_config.json" and change.get("field") == "checkpoint",
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "runtime": runtime, "image": image, "image_labels": {key: labels.get(key) for key in RUNNER_LABELS}}


def execute_runner_plan(plan: dict, demo_source: str | Path, baseline_run: str | Path, output_dir: str | Path, image: str = RUNNER_IMAGE) -> dict:
    demo_source = Path(demo_source).resolve()
    baseline_run = Path(baseline_run).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    capability = runtime_capability_check(plan, demo_source, baseline_run, image)
    (output_dir / "host_capability_check.json").write_text(json.dumps(capability, ensure_ascii=False, indent=2), encoding="utf-8")
    if capability["status"] != "PASS":
        raise RuntimeError("RuntimeCapabilityCheck failed")

    inputs = output_dir / "_input"
    if inputs.exists():
        shutil.rmtree(inputs)
    project_copy = inputs / "project"
    run_copy = inputs / "run"
    project_copy.mkdir(parents=True)
    for name in ("evaluate.py", "metric.py", "model.py"):
        shutil.copy2(demo_source / name, project_copy / name)
    shutil.copytree(baseline_run, run_copy)
    plan_path = inputs / "experiment_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    docker = docker_binary()
    command = [
        docker, "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--pids-limit", "64", "--memory", "768m", "--cpus", "1",
        "--tmpfs", "/tmp:size=128m,mode=1777", "--user", "10001:10001",
        "-e", f"LABOPS_RUNNER_IMAGE={image}", "-e", "OMP_NUM_THREADS=1", "-e", "MKL_NUM_THREADS=1",
        "-v", f"{plan_path}:/input/experiment_plan.json:ro",
        "-v", f"{project_copy}:/input/project:ro",
        "-v", f"{run_copy}:/input/run:ro",
        "-v", f"{output_dir}:/output:rw",
        image,
    ]
    timeout = int(plan["budget"]["max_runtime_seconds"]) * int(plan["success_criteria"]["repeats"]) * 2 + 30
    completed = _run(command, timeout=timeout)
    if completed.returncode != 0 and not (output_dir / "run_result.json").is_file():
        raise RuntimeError(f"Runner failed before producing evidence: {completed.stderr[-1000:]}")
    result = json.loads((output_dir / "run_result.json").read_text(encoding="utf-8"))
    result["host_capability_check"] = capability
    result["container_return_code"] = completed.returncode
    return result
