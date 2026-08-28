"""Foreground lifecycle for the read-only LabOps Guard Reviewer Edition.

The launcher verifies prerequisites, owns local observation services and keeps
the browser surface read-only.  It never sends Matrix messages, approves a
plan, invokes the Runner as an Agent, or writes formal Evidence Bundles.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from labops.demo_readiness import RUNNER_IMAGE, build_readiness
from labops.live_demo import (
    CLASSIFICATION,
    FORMAL_ROOTS,
    ROLE_ORDER,
    SESSION_ID,
    _session_manifest,
    prepare_session,
)
from labops.matrix_observer import load_room_map, sync_once, write_observer_projection


LIFECYCLE_CLASSIFICATION = "LOCAL_REVIEWER_LIFECYCLE"
LIFECYCLE_MAX_AGE_SECONDS = 15


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

        homeserver = env.get("LABOPS_MATRIX_HOMESERVER", "").strip()
        token = env.get("LABOPS_MATRIX_ACCESS_TOKEN", "").strip()
        room_map_value = env.get("LABOPS_MATRIX_ROOM_MAP", "").strip()
        homeserver_ready = homeserver.startswith(("http://", "https://"))
        token_ready = bool(token)
        room_map_ready = False
        if room_map_value:
            try:
                room_roles = load_room_map(Path(room_map_value))
                room_map_ready = len(room_roles) == 6 and set(room_roles.values()) == set(ROLE_ORDER)
            except (OSError, ValueError, json.JSONDecodeError):
                room_map_ready = False
        checks["matrix_homeserver"] = {"status": "PASS" if homeserver_ready else "FAIL"}
        checks["matrix_access_token"] = {"status": "PASS" if token_ready else "FAIL", "redacted": True}
        checks["matrix_room_map"] = {"status": "PASS" if room_map_ready else "FAIL", "rooms": 6 if room_map_ready else 0}
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
        if repository_ready and docker_ready and image_ready and homeserver_ready and token_ready and room_map_ready:
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
                    session=self.session,
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
