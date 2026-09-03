"""Foreground lifecycle for the read-only LabOps Guard Reviewer Edition.

The launcher verifies prerequisites, owns local observation services and keeps
the browser surface read-only.  It never sends Matrix messages, approves a
plan, invokes the Runner as an Agent, or writes formal Evidence Bundles.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from labops.agentteams_skill_deployment import verify_skill_packages
from labops.demo_readiness import RUNNER_IMAGE, build_readiness
from labops.live_demo import (
    CLASSIFICATION,
    FORMAL_ROOTS,
    ROLE_ORDER,
    SESSION_ID,
    _session_manifest,
    prepare_session,
)
from labops.live_evidence_sync import DockerEvidenceSource, sync_live_evidence
from labops.matrix_observer import (
    active_session_binding,
    load_room_map,
    probe_joined_rooms,
    sync_once,
    write_observer_projection,
)


LIFECYCLE_CLASSIFICATION = "LOCAL_REVIEWER_LIFECYCLE"
LIFECYCLE_MAX_AGE_SECONDS = 15
AGENTTEAMS_STATUS_TIMEOUT_SECONDS = 30
AGENTTEAMS_CONTAINERS = {
    "labops-manager": "hiclaw-manager",
    "evidence-collector": "hiclaw-worker-evidence-collector",
    "rca-analyst": "hiclaw-worker-rca-analyst",
    "experiment-planner": "hiclaw-worker-researcher",
    "safe-executor": "hiclaw-worker-controlled-executor",
    "verification-auditor": "hiclaw-worker-verification-auditor",
}
MANAGER_STATE_PATH = "/root/manager-workspace/state.json"
LIVE_TASK_ID = re.compile(r"^LIVE-TASK-\d{8}-\d{3}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _read_object(path: Path, maximum_bytes: int = 64 * 1024) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _probe_docker(project_root: Path) -> dict[str, bool]:
    docker = shutil.which("docker")
    if not docker:
        return {"docker": False, "runner_image": False}
    try:
        daemon = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if daemon.returncode != 0:
            return {"docker": False, "runner_image": False}
        image = subprocess.run(
            [docker, "image", "inspect", RUNNER_IMAGE, "--format", "{{.Id}}"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"docker": False, "runner_image": False}
    return {"docker": True, "runner_image": image.returncode == 0}


def _probe_agentteams_business_readiness(project_root: Path) -> dict[str, Any]:
    """Check that every AgentTeams Matrix consumer is actually running.

    Container liveness and Matrix membership are insufficient: OpenClaw can
    remain healthy while one channel has stopped consuming messages.
    """

    docker = shutil.which("docker")
    if not docker:
        return {
            "ready": False,
            "ready_count": 0,
            "required": len(AGENTTEAMS_CONTAINERS),
            "components": {role: "DOCKER_UNAVAILABLE" for role in AGENTTEAMS_CONTAINERS},
        }

    def probe(item: tuple[str, str]) -> tuple[str, str]:
        role, container = item
        try:
            result = subprocess.run(
                [docker, "exec", container, "openclaw", "channels", "status", "--json"],
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=AGENTTEAMS_STATUS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return role, "UNREACHABLE"
        if result.returncode != 0:
            return role, "UNREACHABLE"
        try:
            channel_status = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return role, "INVALID_HEALTH"
        matrix = (
            channel_status.get("channels", {}).get("matrix", {})
            if isinstance(channel_status, dict)
            else {}
        )
        accounts = (
            channel_status.get("channelAccounts", {}).get("matrix", [])
            if isinstance(channel_status, dict)
            else []
        )
        if matrix.get("configured") is not True:
            return role, "MATRIX_UNCONFIGURED"
        if matrix.get("running") is not True:
            return role, "MATRIX_STOPPED"
        account = next(
            (item for item in accounts if isinstance(item, dict) and item.get("accountId") == "default"),
            accounts[0] if accounts and isinstance(accounts[0], dict) else {},
        )
        if not account:
            return role, "MATRIX_ACCOUNT_MISSING"
        if account.get("running") is not True or account.get("connected") is not True:
            return role, "MATRIX_DISCONNECTED"
        if account.get("healthState") != "healthy":
            return role, "MATRIX_UNHEALTHY"
        return role, "READY"

    with ThreadPoolExecutor(max_workers=len(AGENTTEAMS_CONTAINERS)) as executor:
        components = dict(executor.map(probe, AGENTTEAMS_CONTAINERS.items()))
    ready_count = sum(status == "READY" for status in components.values())
    return {
        "ready": ready_count == len(AGENTTEAMS_CONTAINERS),
        "ready_count": ready_count,
        "required": len(AGENTTEAMS_CONTAINERS),
        "components": components,
    }


def _probe_agentteams_skill_runtime(
    project_root: Path, room_map_path: Path
) -> dict[str, Any]:
    """Verify deployed atomic emitters without returning private routing data."""

    try:
        report = verify_skill_packages(
            project_root,
            room_map_path=room_map_path,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            "status": "UNVERIFIED",
            "runtime_event_emission": "UNVERIFIED",
            "skill_count": 0,
            "emitters_verified": 0,
        }
    skills = report.get("skills") if isinstance(report.get("skills"), list) else []
    skill_count = report.get("skill_count")
    expected = skill_count if isinstance(skill_count, int) else len(skills)
    emitters_verified = sum(
        isinstance(item, dict) and item.get("event_emitter") == "VERIFIED"
        for item in skills
    )
    return {
        "status": report.get("status", "UNVERIFIED"),
        "runtime_event_emission": report.get(
            "runtime_event_emission", "UNVERIFIED"
        ),
        "skill_count": expected,
        "emitters_verified": emitters_verified,
    }


def _active_task_ids(active_tasks: Any) -> list[str]:
    """Extract only task identifiers from the Manager's active task registry."""

    if isinstance(active_tasks, dict):
        entries = list(active_tasks.items())
    elif isinstance(active_tasks, list):
        entries = [(None, item) for item in active_tasks]
    else:
        raise ValueError("Manager active_tasks must be an object or array")

    identifiers: list[str] = []
    for key, value in entries:
        candidate: Any = key
        if isinstance(value, str):
            candidate = value if key is None else key
        elif isinstance(value, dict):
            candidate = next(
                (
                    value.get(field)
                    for field in ("task_instance_id", "task_id", "id")
                    if isinstance(value.get(field), str)
                ),
                key,
            )
        if not isinstance(candidate, str) or not candidate:
            raise ValueError("Manager active task has no identifier")
        identifiers.append(candidate)
    return identifiers


def _probe_manager_recording_state(project_root: Path) -> dict[str, Any]:
    """Read only Manager active-task counts, never task contents or state paths."""

    docker = shutil.which("docker")
    if not docker:
        return {
            "status": "UNVERIFIED",
            "active_task_count": 0,
            "formal_task_count": 0,
            "live_task_count": 0,
        }
    try:
        result = subprocess.run(
            [docker, "exec", "hiclaw-manager", "cat", MANAGER_STATE_PATH],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=15,
        )
        if result.returncode != 0:
            raise ValueError("Manager state is unavailable")
        state = json.loads(result.stdout)
        if not isinstance(state, dict) or "active_tasks" not in state:
            raise ValueError("Manager state lacks active_tasks")
        identifiers = _active_task_ids(state["active_tasks"])
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ):
        return {
            "status": "UNVERIFIED",
            "active_task_count": 0,
            "formal_task_count": 0,
            "live_task_count": 0,
        }

    live_count = sum(bool(LIVE_TASK_ID.fullmatch(item)) for item in identifiers)
    return {
        "status": "VERIFIED",
        "active_task_count": len(identifiers),
        "formal_task_count": len(identifiers) - live_count,
        "live_task_count": live_count,
    }


def _repository_projection(project_root: Path) -> tuple[dict[str, Any], bool]:
    try:
        readiness = build_readiness(project_root)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        readiness = {"status": "BLOCKED", "trust_contract": {}, "evidence": [], "task": {}, "skills": {}}
    trust = readiness.get("trust_contract", {})
    evidence = readiness.get("evidence", [])
    bundles = [
        {
            "task_id": item.get("task_id"),
            "status": item.get("status"),
            "sha256": item.get("sha256"),
        }
        for item in evidence
        if isinstance(item, dict)
    ] if isinstance(evidence, list) else []
    evidence_ready = len(bundles) == 3 and all(item.get("status") == "PASS" for item in bundles)
    contract_ready = isinstance(trust, dict) and trust.get("status") == "PASS"
    task_ready = isinstance(readiness.get("task"), dict) and readiness["task"].get("status") == "PASS"
    skills_ready = isinstance(readiness.get("skills"), dict) and readiness["skills"].get("status") == "CONFIGURED"
    ready = readiness.get("status") == "LOCAL_READY" and all(
        (evidence_ready, contract_ready, task_ready, skills_ready)
    )
    return {
        "trust_contract": {"status": "PASS" if contract_ready else "FAIL"},
        "formal_evidence": {
            "status": "PASS" if evidence_ready else "FAIL",
            "bundles": bundles,
        },
        "agentteams_task": {"status": "PASS" if task_ready else "FAIL"},
        "skill_registry": {"status": "PASS" if skills_ready else "FAIL"},
    }, ready


def build_preflight(
    project_root: str | Path,
    mode: str,
    *,
    environment: dict[str, str] | None = None,
    docker_probe: Callable[[Path], dict[str, bool]] | None = None,
    agentteams_probe: Callable[[Path], dict[str, Any]] | None = None,
    matrix_probe: Callable[[str, str, dict[str, str]], dict[str, Any]] | None = None,
    skill_runtime_probe: Callable[[Path, Path], dict[str, Any]] | None = None,
    manager_state_probe: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return deterministic, credential-free Reviewer readiness JSON."""

    root = Path(project_root).resolve()
    normalized = str(mode).lower()
    if normalized not in {"quick", "live"}:
        raise ValueError("Reviewer mode must be quick or live")
    checks, repository_ready = _repository_projection(root)
    missing: list[str] = []
    available_modes: list[str] = []
    if repository_ready:
        available_modes.append("QUICK")
    else:
        missing.append("REPOSITORY_NOT_READY")

    if normalized == "live":
        env = dict(os.environ if environment is None else environment)
        probe = (docker_probe or _probe_docker)(root)
        docker_ready = probe.get("docker") is True
        image_ready = probe.get("runner_image") is True
        checks["docker"] = {"status": "PASS" if docker_ready else "FAIL"}
        checks["runner_image"] = {
            "status": "PASS" if image_ready else "FAIL",
            "image": RUNNER_IMAGE,
        }
        if not docker_ready:
            missing.append("DOCKER_UNAVAILABLE")
        if not image_ready:
            missing.append("RUNNER_IMAGE_MISSING")

        business = {
            "ready": False,
            "ready_count": 0,
            "required": len(AGENTTEAMS_CONTAINERS),
            "components": {},
        }
        if docker_ready:
            business = (agentteams_probe or _probe_agentteams_business_readiness)(root)
        business_ready = business.get("ready") is True
        ready_count = business.get("ready_count")
        required_count = business.get("required")
        components = business.get("components") if isinstance(business.get("components"), dict) else {}
        checks["agentteams_business_readiness"] = {
            "status": "PASS" if business_ready else "NOT_CHECKED" if not docker_ready else "FAIL",
            "ready": ready_count if isinstance(ready_count, int) else 0,
            "required": required_count if isinstance(required_count, int) else len(AGENTTEAMS_CONTAINERS),
            "components": components,
        }
        if docker_ready and not business_ready:
            missing.append("AGENTTEAMS_BUSINESS_NOT_READY")

        homeserver = env.get("LABOPS_MATRIX_HOMESERVER", "").strip()
        token = env.get("LABOPS_MATRIX_ACCESS_TOKEN", "").strip()
        room_map_value = env.get("LABOPS_MATRIX_ROOM_MAP", "").strip()
        homeserver_ready = homeserver.startswith(("http://", "https://"))
        token_ready = bool(token)
        room_map_ready = False
        room_roles: dict[str, str] = {}
        if room_map_value:
            try:
                room_roles = load_room_map(Path(room_map_value))
                room_map_ready = len(room_roles) == 6 and set(room_roles.values()) == set(ROLE_ORDER)
            except (OSError, ValueError, json.JSONDecodeError):
                room_map_ready = False
        checks["matrix_homeserver"] = {"status": "PASS" if homeserver_ready else "FAIL"}
        checks["matrix_access_token"] = {"status": "PASS" if token_ready else "FAIL", "redacted": True}
        checks["matrix_room_map"] = {"status": "PASS" if room_map_ready else "FAIL", "rooms": 6 if room_map_ready else 0}
        membership = {
            "connected": False,
            "all_joined": False,
            "rooms_expected": len(room_roles),
            "error": None,
        }
        if homeserver_ready and token_ready and room_map_ready:
            membership = (matrix_probe or probe_joined_rooms)(homeserver, token, room_roles)
        membership_ready = membership.get("all_joined") is True
        checks["matrix_room_membership"] = {
            "status": "PASS" if membership_ready else "NOT_CHECKED" if not (
                homeserver_ready and token_ready and room_map_ready
            ) else "FAIL",
            "rooms": membership.get("rooms_expected") if membership_ready else 0,
        }
        if not homeserver:
            missing.append("MATRIX_HOMESERVER_MISSING")
        elif not homeserver_ready:
            missing.append("MATRIX_HOMESERVER_INVALID")
        if not token_ready:
            missing.append("MATRIX_ACCESS_TOKEN_MISSING")
        if not room_map_value:
            missing.append("MATRIX_ROOM_MAP_MISSING")
        elif not room_map_ready:
            missing.append("MATRIX_ROOM_MAP_INVALID")
        elif homeserver_ready and token_ready and not membership_ready:
            error = membership.get("error")
            missing.append(
                "MATRIX_ROOM_MAP_UNJOINED"
                if error == "MATRIX_ROOM_MAP_UNJOINED"
                else "MATRIX_ROOM_MEMBERSHIP_UNVERIFIED"
            )

        skill_runtime_ready = False
        skill_runtime_eligible = docker_ready and business_ready and room_map_ready
        skill_runtime: dict[str, Any] = {
            "status": "NOT_CHECKED",
            "runtime_event_emission": "NOT_CHECKED",
            "skill_count": 0,
            "emitters_verified": 0,
        }
        if skill_runtime_eligible:
            skill_runtime = (skill_runtime_probe or _probe_agentteams_skill_runtime)(
                root, Path(room_map_value)
            )
            skill_count = skill_runtime.get("skill_count")
            emitters_verified = skill_runtime.get("emitters_verified")
            skill_runtime_ready = (
                skill_runtime.get("status") == "VERIFIED"
                and skill_runtime.get("runtime_event_emission") == "VERIFIED"
                and isinstance(skill_count, int)
                and skill_count > 0
                and emitters_verified == skill_count
            )
        checks["agentteams_event_emission"] = {
            "status": (
                "PASS"
                if skill_runtime_ready
                else "FAIL"
                if skill_runtime_eligible
                else "NOT_CHECKED"
            ),
            "runtime_event_emission": skill_runtime.get(
                "runtime_event_emission", "UNVERIFIED"
            ),
            "skills": (
                skill_runtime.get("skill_count")
                if isinstance(skill_runtime.get("skill_count"), int)
                else 0
            ),
            "emitters_verified": (
                skill_runtime.get("emitters_verified")
                if isinstance(skill_runtime.get("emitters_verified"), int)
                else 0
            ),
        }
        if skill_runtime_eligible and not skill_runtime_ready:
            missing.append("AGENTTEAMS_EVENT_EMISSION_UNVERIFIED")

        manager_state_ready = False
        manager_state_clean = False
        manager_state_eligible = docker_ready and business_ready
        manager_state: dict[str, Any] = {
            "status": "NOT_CHECKED",
            "active_task_count": 0,
            "formal_task_count": 0,
            "live_task_count": 0,
        }
        if manager_state_eligible:
            manager_state = (manager_state_probe or _probe_manager_recording_state)(
                root
            )
            manager_state_ready = manager_state.get("status") == "VERIFIED"
            manager_state_clean = (
                manager_state_ready and manager_state.get("live_task_count") == 0
            )
        checks["manager_recording_state"] = {
            "status": (
                "PASS"
                if manager_state_clean
                else "FAIL"
                if manager_state_eligible
                else "NOT_CHECKED"
            ),
            "active_task_count": (
                manager_state.get("active_task_count")
                if isinstance(manager_state.get("active_task_count"), int)
                else 0
            ),
            "formal_task_count": (
                manager_state.get("formal_task_count")
                if isinstance(manager_state.get("formal_task_count"), int)
                else 0
            ),
            "live_task_count": (
                manager_state.get("live_task_count")
                if isinstance(manager_state.get("live_task_count"), int)
                else 0
            ),
        }
        if manager_state_eligible and not manager_state_ready:
            missing.append("MANAGER_RECORDING_STATE_UNVERIFIED")
        elif manager_state_eligible and not manager_state_clean:
            missing.append("STALE_LIVE_TASKS")

        if (
            repository_ready
            and docker_ready
            and image_ready
            and business_ready
            and homeserver_ready
            and token_ready
            and room_map_ready
            and membership_ready
            and skill_runtime_ready
            and manager_state_clean
        ):
            available_modes.append("LIVE")

    requested = normalized.upper()
    status = "READY" if requested in available_modes else "BLOCKED"
    fallback = {
        "mode": "QUICK" if "QUICK" in available_modes else "PUBLIC_EVIDENCE_REPLAY",
        "description": "Use verified archived Evidence when Live prerequisites are unavailable.",
    }
    return {
        "schema_version": "1.0",
        "requested_mode": requested,
        "status": status,
        "available_modes": available_modes,
        "checks": checks,
        "missing_requirements": missing,
        "fallback": fallback,
        "safety": [
            "The Workbench is read-only.",
            "Quick Mode is archived verified replay, not live AgentTeams execution.",
            "Live Mode observes external AgentTeams and never sends Matrix messages or approves plans.",
            "Formal AT-002/003/004 Evidence is never modified.",
        ],
    }


class _ManagedServer:
    def __init__(self, name: str, server: ThreadingHTTPServer) -> None:
        self.name = name
        self.server = server
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=server.serve_forever, name=f"reviewer-{name}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def is_alive(self) -> bool:
        return self.thread.is_alive()


class _MatrixObserver:
    def __init__(
        self,
        session_root: Path,
        homeserver: str,
        token: str,
        room_map: Path,
        interval_seconds: float = 1.0,
    ) -> None:
        self.name = "observer"
        self.session_root = session_root
        self.homeserver = homeserver
        self.token = token
        self.room_roles = load_room_map(room_map)
        manifest = _read_object(session_root / "session.json")
        if not manifest or manifest.get("classification") != CLASSIFICATION:
            raise ValueError("Live observer requires a valid non-formal session")
        self.session = manifest
        self.interval_seconds = interval_seconds
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name="reviewer-matrix-observer", daemon=True)

    def _run(self) -> None:
        since: str | None = None
        last_success: str | None = None
        while not self.stopping.is_set():
            try:
                snapshot = sync_once(
                    self.homeserver,
                    self.token,
                    self.room_roles,
                    since,
                    session=active_session_binding(self.session_root),
                )
                if snapshot.get("connected") is True:
                    if isinstance(snapshot.get("next_batch"), str):
                        since = snapshot["next_batch"]
                    if isinstance(snapshot.get("last_success_at"), str):
                        last_success = snapshot["last_success_at"]
                elif last_success:
                    snapshot["last_success_at"] = last_success
            except Exception:  # observer degradation must never stop the web surface
                snapshot = {
                    "connected": False,
                    "source_status": "DISCONNECTED",
                    "checked_at": _utc_now(),
                    "last_success_at": last_success,
                    "next_batch": since,
                    "events": [],
                    "errors": [{"code": "MATRIX_UNAVAILABLE"}],
                }
            try:
                write_observer_projection(self.session_root, snapshot)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            self.stopping.wait(self.interval_seconds)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=5)

    def is_alive(self) -> bool:
        return self.thread.is_alive()


class _EvidenceSynchronizer:
    """Continuously mirror and verify live Evidence without source mutations."""

    def __init__(
        self,
        project_root: Path,
        sessions_root: Path,
        session_root: Path,
        source: object,
        interval_seconds: float = 3.0,
    ) -> None:
        self.name = "evidence"
        self.project_root = project_root.resolve()
        self.sessions_root = sessions_root.resolve()
        self.session_root = session_root.resolve()
        manifest = _read_object(self.session_root / "session.json")
        if not manifest or manifest.get("classification") != CLASSIFICATION:
            raise ValueError("Live Evidence sync requires a valid non-formal session")
        self.session_id = manifest.get("session_id")
        if not isinstance(self.session_id, str) or SESSION_ID.fullmatch(self.session_id) is None:
            raise ValueError("Live Evidence sync requires a valid session ID")
        self.source = source
        self.interval_seconds = interval_seconds
        self.stopping = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="reviewer-evidence-synchronizer",
            daemon=True,
        )

    def _matrix_snapshot(self) -> dict[str, Any]:
        observer = self.session_root / "observer"
        status = _read_object(observer / "source_status.json") or {}
        events: list[dict[str, Any]] = []
        event_path = observer / "normalized_events.jsonl"
        try:
            if event_path.is_file() and event_path.stat().st_size <= 2 * 1024 * 1024:
                for line in event_path.read_text(encoding="utf-8").splitlines()[:256]:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        events.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            events = []
        return {**status, "events": events}

    def _record_failure(self) -> None:
        _atomic_json(
            self.session_root / "observer" / "evidence_sync.json",
            {
                "status": "BLOCKED",
                "mirror_digest": None,
                "published": False,
                "errors": ["EVIDENCE_SOURCE_UNAVAILABLE"],
                "checked_at": _utc_now(),
            },
        )

    def _run(self) -> None:
        while not self.stopping.is_set():
            try:
                sync_live_evidence(
                    self.project_root,
                    self.sessions_root,
                    self.session_id,
                    self.source,
                    self._matrix_snapshot(),
                    datetime.now(timezone.utc),
                )
            except Exception:  # sync degradation must never stop the web surface
                try:
                    self._record_failure()
                except OSError:
                    pass
            self.stopping.wait(self.interval_seconds)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=5)

    def is_alive(self) -> bool:
        return self.thread.is_alive()


def _default_component_factory(kind: str, **options):
    project_root = Path(options["project_root"])
    if kind == "web":
        from labops.web import make_handler

        handler = make_handler(
            project_root / "demo" / "output",
            reviewer_context=options["reviewer_context"],
        )
        return _ManagedServer(
            "web",
            ThreadingHTTPServer((options["host"], options["port"]), handler),
        )
    if kind == "gateway":
        from labops.runner_gateway import make_handler

        output_root = Path(options["session_root"]) / "gateway-runs"
        output_root.mkdir(parents=True, exist_ok=True)
        handler = make_handler(project_root, output_root)
        return _ManagedServer(
            "gateway",
            ThreadingHTTPServer((options["gateway_host"], options["gateway_port"]), handler),
        )
    if kind == "observer":
        environment = options["environment"]
        return _MatrixObserver(
            Path(options["session_root"]),
            environment["LABOPS_MATRIX_HOMESERVER"],
            environment["LABOPS_MATRIX_ACCESS_TOKEN"],
            Path(environment["LABOPS_MATRIX_ROOM_MAP"]),
        )
    if kind == "evidence":
        environment = options["environment"]
        configured_source = _read_object(
            project_root / "config" / "reviewer-evidence-source.json"
        )
        container = environment.get("LABOPS_LIVE_EVIDENCE_CONTAINER") or configured_source.get("container")
        source_root = environment.get("LABOPS_LIVE_EVIDENCE_ROOT") or configured_source.get("root")
        if not isinstance(container, str) or not container or not isinstance(source_root, str) or not source_root:
            raise ValueError("live Evidence source is not configured")
        source = DockerEvidenceSource(
            container,
            source_root,
        )
        return _EvidenceSynchronizer(
            project_root,
            Path(options["sessions_root"]),
            Path(options["session_root"]),
            source,
        )
    raise ValueError(f"unknown Reviewer component: {kind}")


def _lifecycle_root(sessions_root: Path) -> Path:
    return sessions_root.resolve() / ".reviewer"


def _inside_formal_evidence(project_root: Path, candidate: Path) -> bool:
    for relative in FORMAL_ROOTS:
        try:
            candidate.resolve().relative_to((project_root / relative).resolve())
            return True
        except ValueError:
            continue
    return False


def _valid_lifecycle(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("schema_version") == "1.0"
        and record.get("classification") == LIFECYCLE_CLASSIFICATION
        and isinstance(record.get("instance_id"), str)
        and 4 <= len(record["instance_id"]) <= 80
        and isinstance(record.get("pid"), int)
        and not isinstance(record.get("pid"), bool)
        and record["pid"] > 1
        and record.get("mode") in {"QUICK", "LIVE"}
        and (record.get("session_id") is None or isinstance(record.get("session_id"), str))
        and record.get("host") in {"127.0.0.1", "localhost", "::1"}
        and isinstance(record.get("port"), int)
        and 0 <= record["port"] <= 65535
        and (record.get("gateway_port") is None or isinstance(record.get("gateway_port"), int))
        and isinstance(record.get("started_at"), str)
        and isinstance(record.get("heartbeat_at"), str)
        and record.get("status") in {"RUNNING", "STOPPED", "BLOCKED"}
        and isinstance(record.get("url"), str)
        and record.get("read_only") is True
    )


def _heartbeat_fresh(record: dict[str, Any], maximum_age: int = LIFECYCLE_MAX_AGE_SECONDS) -> bool:
    try:
        heartbeat = datetime.fromisoformat(record["heartbeat_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return False
    if heartbeat.tzinfo is None:
        return False
    age = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
    return -2 <= age <= maximum_age


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return False
    if os.name == "nt":
        try:
            listed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return listed.returncode == 0 and f'"{pid}"' in listed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - fixed local endpoint
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return response.status == 200 and payload.get("read_only") is True


def _ensure_live_session(project_root: Path, sessions_root: Path, session_id: str) -> Path:
    if SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("session must use YYYYMMDD-NNN")
    session_root = sessions_root / session_id
    if not session_root.exists():
        prepare_session(project_root, sessions_root, session_id)
        return session_root
    manifest = _read_object(session_root / "session.json")
    if manifest != _session_manifest(session_id):
        raise ValueError("existing session is not the deterministic non-formal envelope")
    return session_root


def _stop_request(record: dict[str, Any], runtime_root: Path) -> bool:
    request = _read_object(runtime_root / f"stop-{record['instance_id']}.json")
    return bool(
        request
        and request.get("classification") == LIFECYCLE_CLASSIFICATION
        and request.get("instance_id") == record["instance_id"]
        and request.get("pid") == record["pid"]
    )


def start_reviewer(
    project_root: str | Path,
    sessions_root: str | Path,
    mode: str,
    *,
    session_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 18787,
    container_bind: bool = False,
    gateway_host: str = "0.0.0.0",
    gateway_port: int = 18103,
    environment: dict[str, str] | None = None,
    component_factory: Callable[..., Any] | None = None,
    preflight_builder: Callable[..., dict[str, Any]] | None = None,
    wait_fn: Callable[[float], None] = time.sleep,
    open_browser: bool = True,
    on_started: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Start Reviewer components once and keep their owner in the foreground."""

    root = Path(project_root).resolve()
    sessions = Path(sessions_root).resolve()
    if _inside_formal_evidence(root, sessions):
        return {"status": "BLOCKED", "error": "FORMAL_EVIDENCE_ROOT_FORBIDDEN"}
    sessions.mkdir(parents=True, exist_ok=True)
    normalized = str(mode).lower()
    env = dict(os.environ if environment is None else environment)
    builder = preflight_builder or build_preflight
    report = builder(root, normalized, environment=env)
    if report.get("status") != "READY":
        return {
            "status": "BLOCKED",
            "mode": normalized.upper(),
            "missing_requirements": list(report.get("missing_requirements", [])),
            "fallback": report.get("fallback", {}),
        }
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return {"status": "BLOCKED", "error": "REVIEWER_HOST_MUST_BE_LOCAL"}
    bind_host = "0.0.0.0" if container_bind else host
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return {"status": "BLOCKED", "error": "INVALID_REVIEWER_PORT"}
    if normalized == "live" and gateway_host not in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}:
        return {"status": "BLOCKED", "error": "GATEWAY_HOST_OUTSIDE_LOCAL_BOUNDARY"}
    if normalized == "live" and (
        not isinstance(gateway_port, int)
        or isinstance(gateway_port, bool)
        or not 1 <= gateway_port <= 65535
    ):
        return {"status": "BLOCKED", "error": "INVALID_GATEWAY_PORT"}

    session_root: Path | None = None
    if normalized == "live":
        if not session_id:
            return {"status": "BLOCKED", "error": "SESSION_REQUIRED"}
        try:
            session_root = _ensure_live_session(root, sessions, session_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"status": "BLOCKED", "error": type(exc).__name__}
    elif normalized != "quick":
        return {"status": "BLOCKED", "error": "INVALID_MODE"}

    runtime_root = _lifecycle_root(sessions)
    lifecycle_path = runtime_root / "lifecycle.json"
    previous = _read_object(lifecycle_path)
    if previous and _valid_lifecycle(previous) and previous.get("status") == "RUNNING":
        if _heartbeat_fresh(previous) and _pid_alive(previous["pid"]):
            return {"status": "BLOCKED", "error": "REVIEWER_ALREADY_RUNNING"}

    mode_name = normalized.upper()
    query = f"?session={session_id}" if normalized == "live" else ""
    url = f"http://{host}:{port}/reviewer{query}"
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "classification": LIFECYCLE_CLASSIFICATION,
        "instance_id": f"reviewer-{uuid.uuid4().hex}",
        "pid": os.getpid(),
        "mode": mode_name,
        "session_id": session_id if normalized == "live" else None,
        "host": host,
        "port": port,
        "gateway_port": gateway_port if normalized == "live" else None,
        "started_at": _utc_now(),
        "heartbeat_at": _utc_now(),
        "status": "RUNNING",
        "url": url,
        "read_only": True,
        "bind_scope": "CONTAINER_BRIDGE" if container_bind else "LOCAL_LOOPBACK",
    }
    preflight_context = {
        "status": "READY",
        "requirements": {
            name: item.get("status") == "PASS"
            for name, item in report.get("checks", {}).items()
            if isinstance(name, str) and isinstance(item, dict)
        },
    }
    reviewer_context = {
        "project_root": root,
        "sessions_root": sessions,
        "mode": normalized,
        "preflight": preflight_context,
    }
    options = {
        "project_root": root,
        "sessions_root": sessions,
        "session_root": session_root,
        "host": bind_host,
        "port": port,
        "gateway_host": gateway_host,
        "gateway_port": gateway_port,
        "environment": env,
        "reviewer_context": reviewer_context,
    }
    factory = component_factory or _default_component_factory
    components: list[Any] = []
    final_status = "STOPPED"
    reason = "STOPPED"
    error: str | None = None
    try:
        def create_and_start(kind: str) -> None:
            component = factory(kind, **options)
            component.start()
            components.append(component)

        if normalized == "live":
            create_and_start("gateway")
            create_and_start("observer")
            create_and_start("evidence")
        create_and_start("web")
        _atomic_json(lifecycle_path, record)
        started = {
            "status": "RUNNING",
            "mode": mode_name,
            "session_id": record["session_id"],
            "url": url,
            "pid": record["pid"],
            "read_only": True,
        }
        if on_started:
            on_started(started)
        if open_browser:
            try:
                webbrowser.open(url)
            except (OSError, webbrowser.Error):
                pass
        while True:
            if _stop_request(record, runtime_root):
                reason = "STOP_REQUESTED"
                break
            stopped_components = [component.name for component in components if not component.is_alive()]
            if stopped_components:
                final_status = "BLOCKED"
                reason = "COMPONENT_EXITED"
                error = ",".join(stopped_components)
                break
            record["heartbeat_at"] = _utc_now()
            _atomic_json(lifecycle_path, record)
            wait_fn(0.5)
    except KeyboardInterrupt:
        reason = "KEYBOARD_INTERRUPT"
    except Exception as exc:
        final_status = "BLOCKED"
        reason = "STARTUP_OR_RUNTIME_ERROR"
        error = type(exc).__name__
    finally:
        for component in reversed(components):
            try:
                component.stop()
            except Exception:
                final_status = "BLOCKED"
                error = error or "COMPONENT_STOP_FAILED"
        record["status"] = final_status
        record["heartbeat_at"] = _utc_now()
        _atomic_json(lifecycle_path, record)

    result = {
        "status": final_status,
        "mode": mode_name,
        "session_id": record["session_id"],
        "reason": reason,
        "read_only": True,
    }
    if error:
        result["error"] = error
    return result


def reviewer_status(
    sessions_root: str | Path,
    *,
    session_id: str | None = None,
    process_probe: Callable[[int], bool] = _pid_alive,
    health_probe: Callable[[str], bool] = _health,
) -> dict[str, Any]:
    """Read the exact local lifecycle owner and Reviewer health endpoint."""

    record = _read_object(_lifecycle_root(Path(sessions_root)) / "lifecycle.json")
    if record is None:
        return {"status": "NOT_RUNNING", "read_only": True}
    if not _valid_lifecycle(record):
        return {"status": "BLOCKED", "error": "INVALID_LIFECYCLE_RECORD", "read_only": True}
    if session_id and record.get("session_id") != session_id:
        return {"status": "BLOCKED", "error": "SESSION_MISMATCH", "read_only": True}
    if record["status"] != "RUNNING":
        return {"status": "NOT_RUNNING", "last_status": record["status"], "read_only": True}
    if not _heartbeat_fresh(record):
        return {"status": "NOT_RUNNING", "reason": "STALE_LIFECYCLE_RECORD", "read_only": True}
    if not process_probe(record["pid"]):
        return {"status": "NOT_RUNNING", "reason": "OWNER_PROCESS_ABSENT", "read_only": True}
    health_url = f"http://{record['host']}:{record['port']}/api/reviewer/preflight"
    healthy = health_probe(health_url)
    return {
        "status": "RUNNING" if healthy else "DEGRADED",
        "mode": record["mode"],
        "session_id": record["session_id"],
        "url": record["url"],
        "owner_pid": record["pid"],
        "instance_id": record["instance_id"],
        "read_only": True,
    }


def stop_reviewer(
    sessions_root: str | Path,
    *,
    process_probe: Callable[[int], bool] = _pid_alive,
) -> dict[str, Any]:
    """Request graceful stop only for a fresh, exact Reviewer lifecycle owner."""

    runtime_root = _lifecycle_root(Path(sessions_root))
    record = _read_object(runtime_root / "lifecycle.json")
    if record is None:
        return {"status": "NOT_RUNNING", "read_only": True}
    if not _valid_lifecycle(record):
        return {"status": "BLOCKED", "error": "INVALID_LIFECYCLE_RECORD", "read_only": True}
    if record["status"] != "RUNNING":
        return {"status": "NOT_RUNNING", "last_status": record["status"], "read_only": True}
    if not _heartbeat_fresh(record):
        return {"status": "BLOCKED", "error": "STALE_LIFECYCLE_RECORD", "read_only": True}
    if not process_probe(record["pid"]):
        return {"status": "NOT_RUNNING", "reason": "OWNER_PROCESS_ABSENT", "read_only": True}
    request = {
        "schema_version": "1.0",
        "classification": LIFECYCLE_CLASSIFICATION,
        "instance_id": record["instance_id"],
        "pid": record["pid"],
        "requested_at": _utc_now(),
    }
    _atomic_json(runtime_root / f"stop-{record['instance_id']}.json", request)
    return {
        "status": "STOP_REQUESTED",
        "instance_id": record["instance_id"],
        "owner_pid": record["pid"],
        "read_only": True,
    }
