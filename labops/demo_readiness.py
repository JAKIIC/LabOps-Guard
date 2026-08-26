"""Read-only preflight for recording the real AgentTeams demonstration.

This module never starts services, executes an Agent, posts a Matrix event or
writes evidence.  It verifies the repository inputs and archived proof, and can
optionally check whether the local recording services are reachable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

from labops.trust import validate_trust_contract
from labops.skill_registry import SkillRegistryError, list_skills


ROLE_ORDER = [
    "labops-manager",
    "evidence-collector",
    "rca-analyst",
    "experiment-planner",
    "safe-executor",
    "verification-auditor",
]

TASK_PATH = Path("agentteams/tasks/LABOPS-AT-004-EVAL-DRIFT.json")
PROMPT_PATH = Path("agentteams/prompts/eval_drift_task.md")
RUNNER_IMAGE = "labops/pytorch-cpu-runner:0.2.0"
SKILL_PIPELINE = [
    ("Evidence Collection", "collect-lab-evidence", "evidence-collector"),
    ("RCA", "diagnose-lab-incident", "rca-analyst"),
    ("Safe Planning", "plan-lab-experiment", "experiment-planner"),
    ("Controlled Execution", "control-lab-action", "safe-executor"),
    ("Independent Verification", "verify-lab-result", "verification-auditor"),
    ("Evidence Packaging", "pack-lab-evidence", "labops-manager"),
    ("Case Memory", "publish-case-memory", "labops-manager"),
]


def _run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _check_task(root: Path, show_prompt: bool) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    task_file = root / TASK_PATH
    prompt_file = root / PROMPT_PATH
    try:
        task = json.loads(task_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "error": type(exc).__name__}, ["AT-004 task is unreadable"]

    if task.get("assigned_agents") != ROLE_ORDER:
        errors.append("AT-004 assigned Agent order differs from the six-role contract")
    if task.get("prompt_file") != PROMPT_PATH.as_posix():
        errors.append("AT-004 prompt reference differs from the recording prompt")
    runner = task.get("runner_contract", {})
    if runner.get("image") != RUNNER_IMAGE or runner.get("network") != "none":
        errors.append("AT-004 Runner image or network boundary differs from the fixed contract")
    expected_handoffs = [
        f"{source} -> {target}" for source, target in zip(ROLE_ORDER, ROLE_ORDER[1:])
    ] + ["verification-auditor -> labops-manager"]
    if task.get("required_handoffs") != expected_handoffs:
        errors.append("AT-004 required handoffs differ from the six-role order")

    prompt = ""
    try:
        prompt = prompt_file.read_text(encoding="utf-8")
    except OSError:
        errors.append("AT-004 Manager Prompt is unreadable")

    result: dict[str, Any] = {
        "status": "PASS" if not errors else "FAIL",
        "task_id": task.get("task_id"),
        "task_contract": TASK_PATH.as_posix(),
        "manager_prompt_path": PROMPT_PATH.as_posix(),
        "agent_order": ROLE_ORDER,
        "required_handoffs": task.get("required_handoffs", []),
        "runner_gateway": runner.get("endpoint"),
        "runner_image": runner.get("image"),
        "run_id": runner.get("run_id"),
    }
    if show_prompt:
        result["manager_prompt"] = prompt
    return result, errors


def _verify_evidence(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    verifier = root / "scripts" / "verify_evidence.py"
    try:
        completed = _run([sys.executable, "-B", str(verifier)], root)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"evidence verifier failed to start: {type(exc).__name__}"]
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return [], ["evidence verifier did not return JSON"]

    results = []
    for item in payload.get("results", []):
        results.append(
            {
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "sha256": item.get("sha256"),
                "artifact_count": item.get("artifact_count"),
                "trace": item.get("trace", {}),
                "errors": item.get("errors", []),
            }
        )
    errors = []
    if completed.returncode != 0 or payload.get("status") != "PASS":
        errors.append("one or more formal Evidence Bundles failed verification")
    return results, errors


def _check_skills(root: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        registry = {item["skill_id"]: item for item in list_skills(root)}
    except SkillRegistryError as exc:
        return {"status": "BLOCKED", "error": str(exc)}, ["Skill Registry failed closed"]
    expected_pipeline = []
    for stage, skill_id, owner_agent in SKILL_PIPELINE:
        skill = registry.get(skill_id)
        if skill is None:
            errors.append(f"expected Skill is not active: {skill_id}")
            continue
        if skill["owner_agents"] != [owner_agent]:
            errors.append(f"Skill owner differs from the recording pipeline: {skill_id}")
        io_contract = json.loads((root / skill["io_schema"]).read_text(encoding="utf-8"))
        expected_pipeline.append(
            {
                "stage": stage,
                "skill_id": skill_id,
                "skill_version": skill["version"],
                "owner_agent": owner_agent,
                "io_schema_version": io_contract.get("schema_version"),
                "runtime_visibility": "AGENTTEAMS_HOOK_REQUIRED",
            }
        )
    if len(registry) != 7:
        errors.append("active Skill count is not seven")
    event_contract = root / "schemas" / "skill_usage_event.schema.json"
    if not event_contract.is_file():
        errors.append("Skill usage event validation contract is missing")
    return {
        "status": "CONFIGURED" if not errors else "BLOCKED",
        "registry_valid": not errors,
        "registered_count": len(registry),
        "expected_pipeline": expected_pipeline,
        "usage_event_contract": "schemas/skill_usage_event.schema.json",
        "event_validation_command": "python -B -m labops skills validate-event <event.json>",
        "runtime_event_emission": "NOT_IMPLEMENTED",
        "historical_at004_has_skill_usage_events": False,
        "live_visibility": "AGENTTEAMS_HOOK_REQUIRED",
    }, errors


def _check_docker(root: Path) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {"status": "FAIL", "detail": "docker executable not found"}
    try:
        daemon = _run([docker, "version", "--format", "{{.Server.Version}}"], root)
        if daemon.returncode != 0:
            return {"status": "FAIL", "detail": "Docker daemon is not reachable"}
        image = _run([docker, "image", "inspect", RUNNER_IMAGE, "--format", "{{.Id}}"], root)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "FAIL", "detail": type(exc).__name__}
    return {
        "status": "PASS" if image.returncode == 0 else "FAIL",
        "daemon": "READY",
        "runner_image": RUNNER_IMAGE,
        "image_present": image.returncode == 0,
    }


def _check_health(url: str, expected_service: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return {"status": "FAIL", "url": url, "detail": "only local HTTP health endpoints are allowed"}
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - local URL is operator supplied
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"status": "FAIL", "url": url, "detail": type(exc).__name__}
    service = payload.get("service")
    healthy = response.status == 200 and payload.get("ok") is True
    if expected_service and service != expected_service:
        healthy = False
    return {"status": "PASS" if healthy else "FAIL", "url": url, "service": service}


def build_readiness(
    project_root: str | Path,
    *,
    service_checks: bool = False,
    show_prompt: bool = False,
    gateway_url: str = "http://127.0.0.1:18103/healthz",
    dashboard_url: str = "http://127.0.0.1:8787/healthz",
) -> dict[str, Any]:
    """Build a deterministic, read-only readiness report."""

    root = Path(project_root).resolve()
    task, task_errors = _check_task(root, show_prompt)
    evidence, evidence_errors = _verify_evidence(root)
    skills, skill_errors = _check_skills(root)
    contract_errors = validate_trust_contract(root)
    errors = task_errors + evidence_errors + skill_errors + [f"trust contract: {item}" for item in contract_errors]

    services: dict[str, Any]
    if service_checks:
        services = {
            "docker": _check_docker(root),
            "runner_gateway": _check_health(gateway_url, "labops-runner-gateway"),
            "dashboard": _check_health(dashboard_url, "labops-guard"),
        }
        if any(item.get("status") != "PASS" for item in services.values()):
            errors.append("one or more local recording services are not ready")
    else:
        services = {
            "status": "NOT_CHECKED",
            "instruction": "rerun with --service-checks after starting Docker, Gateway and Dashboard",
        }

    return {
        "schema_version": "1.0",
        "status": "LOCAL_READY" if not errors else "BLOCKED",
        "mode": "READINESS_CHECK_ONLY",
        "executes_agentteams": False,
        "archived_replay_is_live": False,
        "live_agentteams": "MANUAL_CHECK_REQUIRED",
        "task": task,
        "trust_contract": {"status": "PASS" if not contract_errors else "FAIL", "errors": contract_errors},
        "evidence": evidence,
        "skills": skills,
        "services": services,
        "manual_live_checks": [
            {"component": "HiClaw / AgentTeams Manager", "status": "MANUAL_CHECK_REQUIRED"},
            {"component": "six configured Agent identities", "status": "MANUAL_CHECK_REQUIRED"},
            {"component": "Matrix Manager and Worker rooms", "status": "MANUAL_CHECK_REQUIRED"},
            {"component": "MinIO shared task path", "status": "MANUAL_CHECK_REQUIRED"},
        ],
        "errors": errors,
        "operator_guide": "docs/final-demo-guide.md",
    }
