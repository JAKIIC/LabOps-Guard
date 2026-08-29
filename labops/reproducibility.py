"""Credential-safe verification for the Reviewer Reproducibility Pack."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from labops.contracts import ContractError, validate_document
from labops.live_demo import ROLE_ORDER
from labops.matrix_observer import load_room_map, probe_joined_rooms
from labops.reviewer import build_preflight


DEFAULT_LOCK = "config/reviewer-runtime-lock.json"
MAX_LOCK_BYTES = 64 * 1024


def load_runtime_lock(project_root: str | Path, runtime_lock: str | Path) -> dict[str, Any]:
    """Load and strictly validate the public, credential-free runtime lock."""

    root = Path(project_root).resolve()
    path = Path(runtime_lock)
    if not path.is_absolute():
        path = root / path
    if not path.is_file() or path.stat().st_size > MAX_LOCK_BYTES:
        raise ValueError("runtime lock is missing or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_document(payload, "reviewer_runtime_lock.schema.json", root)
    except (OSError, UnicodeError, json.JSONDecodeError, ContractError) as exc:
        raise ValueError(f"runtime lock is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("runtime lock must be an object")
    version = payload["agentteams"]["version"]
    if f"/{version}/" not in payload["agentteams"]["installer_url"]:
        raise ValueError("runtime lock version does not match installer URL")
    expected_bundled = {"Higress Gateway", "Tuwunel Matrix", "Element Web", "MinIO"}
    if set(payload["bundled_components"]) != expected_bundled:
        raise ValueError("runtime lock bundled components are incomplete")
    return payload


def _package_version(project_root: Path) -> str | None:
    try:
        text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _run(command: list[str], project_root: Path, timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _probe_docker(project_root: Path, runtime_lock: dict[str, Any]) -> dict[str, Any]:
    docker = shutil.which("docker")
    empty = {
        "docker": False,
        "runner_image": False,
        "runner_labels": {},
        "agentteams_controller": False,
        "agentteams_manager": False,
        "agentteams_workers": 0,
        "agentteams_version": None,
        "docker_server_version": None,
    }
    if not docker:
        return empty
    version = _run([docker, "version", "--format", "{{.Server.Version}}"], project_root)
    if version is None or version.returncode != 0:
        return empty
    image_name = runtime_lock["runner"]["image"]
    image = _run([docker, "image", "inspect", image_name, "--format", "{{json .Config.Labels}}"], project_root)
    labels: dict[str, str] = {}
    if image is not None and image.returncode == 0:
        try:
            parsed = json.loads(image.stdout.strip())
            if isinstance(parsed, dict):
                labels = {str(key): str(value) for key, value in parsed.items()}
        except (ValueError, json.JSONDecodeError):
            labels = {}
    containers = _run([docker, "ps", "--format", "{{.Names}}\t{{.Image}}"], project_root)
    observed: list[tuple[str, str]] = []
    if containers is not None and containers.returncode == 0:
        for line in containers.stdout.splitlines():
            name, separator, image_name = line.strip().partition("\t")
            if name and separator and image_name:
                observed.append((name, image_name))
    names = [name for name, _image in observed]
    controller = any(re.fullmatch(r"(?:hiclaw|agentteams)-controller", name) for name in names)
    manager = any(re.fullmatch(r"(?:hiclaw|agentteams)-manager", name) for name in names)
    workers = sum(
        1 for name in names if re.fullmatch(r"(?:hiclaw|agentteams)-worker(?:-.+)?", name)
    )
    control_images = [
        image_name
        for name, image_name in observed
        if re.fullmatch(r"(?:hiclaw|agentteams)-(?:controller|manager)", name)
    ]
    image_versions = {
        match.group(1)
        for image_name in control_images
        if (match := re.search(r":(v[0-9]+\.[0-9]+\.[0-9]+)(?:@sha256:[0-9a-f]+)?$", image_name))
    }
    agentteams_version = next(iter(image_versions)) if len(control_images) >= 2 and len(image_versions) == 1 else None
    return {
        "docker": True,
        "runner_image": bool(labels),
        "runner_labels": labels,
        "agentteams_controller": controller,
        "agentteams_manager": manager,
        "agentteams_workers": workers,
        "agentteams_version": agentteams_version,
        "docker_server_version": version.stdout.strip() or None,
    }


def _room_map_status(environment: dict[str, str]) -> tuple[bool, int]:
    room_map_value = environment.get("LABOPS_MATRIX_ROOM_MAP", "").strip()
    if not room_map_value:
        return False, 0
    try:
        roles = load_room_map(Path(room_map_value))
    except (OSError, ValueError, json.JSONDecodeError):
        return False, 0
    valid = len(roles) == 6 and set(roles.values()) == set(ROLE_ORDER)
    return valid, len(roles) if valid else 0


def build_pack_report(
    project_root: str | Path,
    mode: str,
    runtime_lock: str | Path = DEFAULT_LOCK,
    *,
    environment: dict[str, str] | None = None,
    docker_probe: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    matrix_probe: Callable[[str, str, dict[str, str]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic reproduction report without returning private values."""

    root = Path(project_root).resolve()
    normalized = str(mode).lower()
    if normalized not in {"quick", "live"}:
        raise ValueError("Reviewer mode must be quick or live")
    lock = load_runtime_lock(root, runtime_lock)
    expected_package = lock["labops"]["package_version"]
    observed_package = _package_version(root)
    package_ready = observed_package == expected_package
    quick = build_preflight(root, "quick", environment={})
    repository_ready = quick.get("status") == "READY" and package_ready
    checks: dict[str, Any] = {
        "runtime_lock": {"status": "PASS"},
        "repository": {"status": "PASS" if repository_ready else "FAIL"},
        "package_version": {
            "status": "PASS" if package_ready else "FAIL",
            "expected": expected_package,
            "observed": observed_package,
        },
    }
    missing: list[str] = []
    if not repository_ready:
        missing.append("REPOSITORY_NOT_READY")

    if normalized == "live":
        env = dict(os.environ if environment is None else environment)
        probe = (docker_probe or _probe_docker)(root, lock)
        docker_ready = probe.get("docker") is True
        image_ready = probe.get("runner_image") is True
        labels = probe.get("runner_labels") if isinstance(probe.get("runner_labels"), dict) else {}
        label_ready = image_ready and all(
            labels.get(name) == value for name, value in lock["runner"]["labels"].items()
        )
        controller_ready = probe.get("agentteams_controller") is True
        manager_ready = probe.get("agentteams_manager") is True
        worker_count = probe.get("agentteams_workers")
        workers_ready = isinstance(worker_count, int) and not isinstance(worker_count, bool) and worker_count >= 5
        observed_agentteams_version = probe.get("agentteams_version")
        version_ready = observed_agentteams_version == lock["agentteams"]["version"]
        checks["docker"] = {
            "status": "PASS" if docker_ready else "FAIL",
            "server_version": probe.get("docker_server_version") if docker_ready else None,
        }
        checks["runner_contract"] = {
            "status": "PASS" if label_ready else "FAIL",
            "image": lock["runner"]["image"],
        }
        checks["agentteams_runtime"] = {
            "status": "PASS" if controller_ready and manager_ready and workers_ready and version_ready else "FAIL",
            "controller": "RUNNING" if controller_ready else "MISSING",
            "manager": "RUNNING" if manager_ready else "MISSING",
            "workers_running": worker_count if isinstance(worker_count, int) else 0,
            "workers_required": 5,
            "expected_version": lock["agentteams"]["version"],
            "observed_version": observed_agentteams_version,
        }
        if not docker_ready:
            missing.append("DOCKER_UNAVAILABLE")
        if not image_ready:
            missing.append("RUNNER_IMAGE_MISSING")
        elif not label_ready:
            missing.append("RUNNER_CONTRACT_MISMATCH")
        if not controller_ready:
            missing.append("AGENTTEAMS_CONTROLLER_MISSING")
        if not manager_ready:
            missing.append("AGENTTEAMS_MANAGER_MISSING")
        if not workers_ready:
            missing.append("AGENTTEAMS_WORKERS_INSUFFICIENT")
        if controller_ready and manager_ready and not version_ready:
            missing.append("AGENTTEAMS_VERSION_MISMATCH")

        homeserver = env.get("LABOPS_MATRIX_HOMESERVER", "").strip()
        token = env.get("LABOPS_MATRIX_ACCESS_TOKEN", "").strip()
        room_map_value = env.get("LABOPS_MATRIX_ROOM_MAP", "").strip()
        homeserver_ready = homeserver.startswith(("http://", "https://"))
        room_map_ready, room_count = _room_map_status(env)
        room_roles: dict[str, str] = {}
        if room_map_ready:
            room_roles = load_room_map(Path(room_map_value))
        membership = {
            "connected": False,
            "all_joined": False,
            "rooms_expected": room_count,
            "error": None,
        }
        if homeserver_ready and token and room_map_ready:
            membership = (matrix_probe or probe_joined_rooms)(homeserver, token, room_roles)
        membership_ready = membership.get("all_joined") is True
        checks["matrix_homeserver"] = {"status": "PASS" if homeserver_ready else "FAIL"}
        checks["matrix_access"] = {"status": "PASS" if token else "FAIL", "redacted": True}
        checks["matrix_room_map"] = {
            "status": "PASS" if room_map_ready else "FAIL",
            "rooms": room_count,
        }
        checks["matrix_room_membership"] = {
            "status": "PASS" if membership_ready else "NOT_CHECKED" if not (
                homeserver_ready and bool(token) and room_map_ready
            ) else "FAIL",
            "rooms": membership.get("rooms_expected") if membership_ready else 0,
        }
        if not homeserver:
            missing.append("MATRIX_HOMESERVER_MISSING")
        elif not homeserver_ready:
            missing.append("MATRIX_HOMESERVER_INVALID")
        if not token:
            missing.append("MATRIX_ACCESS_TOKEN_MISSING")
        if not room_map_value:
            missing.append("MATRIX_ROOM_MAP_MISSING")
        elif not room_map_ready:
            missing.append("MATRIX_ROOM_MAP_INVALID")
        elif homeserver_ready and token and not membership_ready:
            error = membership.get("error")
            missing.append(
                "MATRIX_ROOM_MAP_UNJOINED"
                if error == "MATRIX_ROOM_MAP_UNJOINED"
                else "MATRIX_ROOM_MEMBERSHIP_UNVERIFIED"
            )

    status = "READY" if not missing else "BLOCKED"
    fallback_mode = "QUICK" if normalized == "live" and repository_ready else "PUBLIC_EVIDENCE_REPLAY"
    return {
        "schema_version": "1.0",
        "requested_mode": normalized.upper(),
        "status": status,
        "versions": {
            "agentteams": lock["agentteams"]["version"],
            "labops": expected_package,
            "runner": lock["runner"]["image"],
        },
        "checks": checks,
        "missing_requirements": missing,
        "fallback": {
            "mode": fallback_mode,
            "description": "Use verified archived Evidence when Live prerequisites are unavailable.",
        },
        "safety": [
            "No credential value, private room ID or host path is returned.",
            "Quick Mode is archived verified replay, not live AgentTeams execution.",
            "Live readiness requires real AgentTeams services and five Workers.",
            "Formal AT-002/003/004 Evidence is read-only.",
        ],
    }
