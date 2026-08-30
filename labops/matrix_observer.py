"""Read-only, allowlisted Matrix observer for Reviewer Edition.

The observer performs bounded `/sync` reads and writes only a non-authoritative
UI projection beneath an isolated live-demo session.  It never sends Matrix
messages or treats room text as terminal evidence.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from labops.contracts import ContractError, validate_document
from labops.live_demo import CLASSIFICATION, ROLE_ORDER
from labops.recovery import load_recovery_overlay
from labops.reviewer_state import AGENT_PROGRESS, EXPECTED_TIMELINE


PROJECTION_CLASSIFICATION = "NON_AUTHORITATIVE_UI_PROJECTION"
PROJECTION_VALIDATION_VERSION = "matrix-sender-bound-v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EVENTS_PER_SYNC = 256
ROOM_ID = re.compile(r"^![^:\s]+:\S+$")
EVENT_ID = re.compile(r"^\$\S+$")
MATRIX_USER_ID = re.compile(r"^@([^:\s]+):(\S+)$")
EVENT_KIND = re.compile(r"LABOPS_EVENT_KIND\s*[:=]\s*([a-z_]+)", re.IGNORECASE)
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
TRANSITIONS = {kind: (source, target) for kind, source, target in EXPECTED_TIMELINE}
TRANSITIONS.update({
    "evidence_incomplete": ("EVIDENCE_COLLECTING", "BLOCKED"),
})
EVENT_ACTORS = {kind: actor for kind, (actor, _state) in AGENT_PROGRESS.items()}
EVENT_ACTORS["evidence_incomplete"] = "evidence-collector"
RUNTIME_SENDER_ALIASES = {
    "manager": "labops-manager",
    "labops-manager": "labops-manager",
    "hiclaw-manager": "labops-manager",
    "evidence-collector": "evidence-collector",
    "rca-analyst": "rca-analyst",
    "researcher": "experiment-planner",
    "experiment-planner": "experiment-planner",
    "controlled-executor": "safe-executor",
    "safe-executor": "safe-executor",
    "verification-auditor": "verification-auditor",
}
SOURCE_STATUSES = {"LIVE", "STALE", "DISCONNECTED", "UNSUPPORTED_ENCRYPTED_ROOM"}
ERROR_CODES = {
    "MATRIX_AUTH_FAILED",
    "MATRIX_UNAVAILABLE",
    "MATRIX_CONFIG_INVALID",
    "MATRIX_RESPONSE_TOO_LARGE",
    "MATRIX_RESPONSE_INVALID",
    "MATRIX_ROOM_MAP_UNJOINED",
    "RECOVERY_BINDING_INVALID",
    "UNSUPPORTED_ENCRYPTED_ROOM",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def load_room_map(path: str | Path) -> dict[str, str]:
    """Load a room allowlist and reject ambiguous or unknown identities."""

    document = _read_object(Path(path))
    try:
        validate_document(document, "reviewer_config.schema.json")
    except (ContractError, OSError, ValueError) as exc:
        raise ValueError(f"invalid Reviewer room map: {exc}") from exc
    rooms = document.get("rooms")
    if not isinstance(rooms, dict) or not rooms:
        raise ValueError("Reviewer room map must contain at least one room")
    normalized: dict[str, str] = {}
    seen_roles: set[str] = set()
    for room_id, agent_id in rooms.items():
        if not isinstance(room_id, str) or ROOM_ID.fullmatch(room_id) is None:
            raise ValueError("Reviewer room map contains an invalid Matrix room ID")
        domain = room_id.split(":", 1)[1].lower()
        if domain == "example.invalid" or domain.endswith(".invalid"):
            raise ValueError("Reviewer room map contains a placeholder Matrix room ID")
        if agent_id not in ROLE_ORDER:
            raise ValueError("Reviewer room map contains an unknown Agent ID")
        if agent_id in seen_roles:
            raise ValueError("Reviewer room map contains a duplicate Agent role")
        seen_roles.add(agent_id)
        normalized[room_id] = agent_id
    return normalized


def _event_time(milliseconds: object) -> str | None:
    if not isinstance(milliseconds, int) or isinstance(milliseconds, bool) or milliseconds < 0:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None


def _safe_refs(value: object, *, hashes: bool = False, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 512:
            continue
        if hashes:
            if SHA256.fullmatch(item):
                result.append(item.lower())
        else:
            normalized = item.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:/", normalized):
                continue
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _session_bindings(session: dict[str, Any]) -> dict[str, str]:
    names = (
        "session_id",
        "task_instance_id",
        "incident_instance_id",
        "attempt_id",
        "run_id",
    )
    values = {name: session.get(name) for name in names}
    if any(not isinstance(value, str) or not value for value in values.values()):
        return {}
    return {name: str(value) for name, value in values.items()}


def _known_session_bindings(session_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Return every attempt/run binding verified by the recovery hash chain."""

    common_names = ("session_id", "task_instance_id", "incident_instance_id")
    common = {name: manifest.get(name) for name in common_names}
    if any(not isinstance(value, str) or not value for value in common.values()):
        raise ValueError("live session manifest lacks observer bindings")
    overlay = load_recovery_overlay(session_root)
    attempts = overlay.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("recovery overlay has no attempts")
    bindings: list[dict[str, str]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("recovery overlay contains an invalid attempt")
        attempt_id = attempt.get("attempt_id")
        run_id = attempt.get("run_id")
        if not isinstance(attempt_id, str) or not attempt_id or not isinstance(run_id, str) or not run_id:
            raise ValueError("recovery attempt lacks observer bindings")
        bindings.append({
            **{name: str(value) for name, value in common.items()},
            "attempt_id": attempt_id,
            "run_id": run_id,
        })
    return bindings


def active_session_binding(session_root: str | Path) -> dict[str, Any]:
    """Return a transient session manifest bound to the latest verified attempt.

    The immutable ``session.json`` remains the original attempt manifest.  This
    helper overlays only the latest attempt/run pair reconstructed from the
    append-only Recovery Trace so a live Observer cannot accept stale runs.
    """

    root = Path(session_root).resolve()
    manifest = _read_object(root / "session.json")
    if manifest.get("classification") != CLASSIFICATION:
        raise ValueError("active observer binding requires a NON_FORMAL_LIVE_DEMO session")
    active = _known_session_bindings(root, manifest)[-1]
    return {**manifest, "attempt_id": active["attempt_id"], "run_id": active["run_id"]}


def _sender_localpart(sender: object, room_id: str) -> str | None:
    if not isinstance(sender, str) or not isinstance(room_id, str) or ":" not in room_id:
        return None
    match = MATRIX_USER_ID.fullmatch(sender)
    if match is None or match.group(2).lower() != room_id.split(":", 1)[1].lower():
        return None
    return match.group(1).lower()


def _sender_role(sender: object, room_id: str) -> str | None:
    localpart = _sender_localpart(sender, room_id)
    return RUNTIME_SENDER_ALIASES.get(localpart) if localpart is not None else None


def projection_actor_valid(actor: object, kind: object) -> bool:
    """Return whether a projected kind is bound to its authorized actor."""

    if not isinstance(kind, str):
        return False
    if kind == "approval_granted":
        return actor == "human-approver"
    return EVENT_ACTORS.get(kind) == actor


def _normalized_event(
    event: dict[str, Any],
    room_id: str,
    agent_id: str,
    bindings: dict[str, str],
) -> dict[str, Any] | None:
    if event.get("type") != "m.room.message":
        return None
    event_id = event.get("event_id")
    content = event.get("content")
    if not isinstance(event_id, str) or EVENT_ID.fullmatch(event_id) is None or not isinstance(content, dict):
        return None
    searchable = json.dumps(content, ensure_ascii=False, sort_keys=True)
    if not bindings or any(binding not in searchable for binding in bindings.values()):
        return None
    structured = content.get("labops_event")
    structured = structured if isinstance(structured, dict) else {}
    kind = structured.get("kind")
    if not isinstance(kind, str):
        body = content.get("body")
        match = EVENT_KIND.search(body) if isinstance(body, str) else None
        kind = match.group(1).lower() if match else None
    if kind not in TRANSITIONS:
        return None
    sender = event.get("sender")
    sender_role = _sender_role(sender, room_id)
    if kind == "approval_granted":
        if structured.get("actor") != "human-approver" or sender_role is not None:
            return None
        if _sender_localpart(sender, room_id) is None:
            return None
        actor = "human-approver"
    else:
        expected_actor = EVENT_ACTORS.get(kind)
        if expected_actor is None or sender_role != expected_actor:
            return None
        if expected_actor != agent_id and expected_actor != "labops-manager":
            return None
        actor = expected_actor
    expected_from, expected_to = TRANSITIONS[kind]
    workflow_from = structured.get("workflow_from")
    workflow_to = structured.get("workflow_to")
    if not isinstance(workflow_from, str) or not workflow_from:
        workflow_from = expected_from
    if not isinstance(workflow_to, str) or not workflow_to:
        workflow_to = expected_to
    return {
        "classification": PROJECTION_CLASSIFICATION,
        "validation_version": PROJECTION_VALIDATION_VERSION,
        "event_id": event_id,
        "room_id": room_id,
        **bindings,
        "actor": actor,
        "kind": kind,
        "timestamp": _event_time(event.get("origin_server_ts")),
        "workflow_from": workflow_from,
        "workflow_to": workflow_to,
        "evidence_state": "OBSERVED",
        "artifact_refs": _safe_refs(structured.get("artifact_refs")),
        "hash_refs": _safe_refs(structured.get("hash_refs"), hashes=True),
    }


def normalize_sync_response(
    payload: dict,
    room_roles: dict[str, str],
    session: dict,
) -> list[dict]:
    """Normalize only session-bound events from allowlisted rooms."""

    if not isinstance(payload, dict) or not isinstance(room_roles, dict) or not isinstance(session, dict):
        return []
    bindings = _session_bindings(session)
    joined = payload.get("rooms", {}).get("join", {}) if isinstance(payload.get("rooms"), dict) else {}
    if not isinstance(joined, dict):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for room_id, agent_id in room_roles.items():
        if agent_id not in ROLE_ORDER:
            continue
        room = joined.get(room_id)
        timeline = room.get("timeline", {}) if isinstance(room, dict) else {}
        events = timeline.get("events", []) if isinstance(timeline, dict) else []
        if not isinstance(events, list):
            continue
        for event in events[:MAX_EVENTS_PER_SYNC]:
            if not isinstance(event, dict):
                continue
            item = _normalized_event(event, room_id, agent_id, bindings)
            if item is None or item["event_id"] in seen:
                continue
            seen.add(item["event_id"])
            normalized.append(item)
    normalized.sort(key=lambda item: (item.get("timestamp") or "", item["event_id"]))
    return normalized


def _encrypted_rooms(payload: dict[str, Any], room_roles: dict[str, str]) -> list[str]:
    joined = payload.get("rooms", {}).get("join", {}) if isinstance(payload.get("rooms"), dict) else {}
    if not isinstance(joined, dict):
        return []
    encrypted: list[str] = []
    for room_id in room_roles:
        room = joined.get(room_id)
        timeline = room.get("timeline", {}) if isinstance(room, dict) else {}
        events = timeline.get("events", []) if isinstance(timeline, dict) else []
        if isinstance(events, list) and any(
            isinstance(event, dict) and event.get("type") == "m.room.encrypted" for event in events
        ):
            encrypted.append(room_id)
    return encrypted


def _failure(checked_at: str, code: str) -> dict[str, Any]:
    return {
        "connected": False,
        "source_status": "DISCONNECTED",
        "checked_at": checked_at,
        "last_success_at": None,
        "next_batch": None,
        "events": [],
        "errors": [{"code": code}],
    }


def probe_joined_rooms(
    homeserver: str,
    token: str,
    room_roles: dict[str, str],
    opener: Callable[..., Any] = urlopen,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Verify configured rooms are joined without returning private identifiers."""

    base = {
        "connected": False,
        "all_joined": False,
        "rooms_expected": len(room_roles) if isinstance(room_roles, dict) else 0,
        "error": "MATRIX_CONFIG_INVALID",
    }
    if (
        not isinstance(homeserver, str)
        or not homeserver.startswith(("http://", "https://"))
        or not isinstance(token, str)
        or not token
        or not isinstance(room_roles, dict)
        or not room_roles
    ):
        return base
    endpoint = homeserver.rstrip("/") + "/_matrix/client/v3/joined_rooms"
    request = Request(endpoint, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return dict(base, error="MATRIX_RESPONSE_TOO_LARGE")
            payload = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        code = "MATRIX_AUTH_FAILED" if exc.code in {401, 403} else "MATRIX_UNAVAILABLE"
        return dict(base, error=code)
    except (URLError, OSError, TimeoutError):
        return dict(base, error="MATRIX_UNAVAILABLE")
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return dict(base, error="MATRIX_RESPONSE_INVALID")
    joined = payload.get("joined_rooms") if isinstance(payload, dict) else None
    if not isinstance(joined, list) or any(not isinstance(item, str) for item in joined):
        return dict(base, connected=True, error="MATRIX_RESPONSE_INVALID")
    all_joined = set(room_roles).issubset(set(joined))
    return {
        "connected": True,
        "all_joined": all_joined,
        "rooms_expected": len(room_roles),
        "error": None if all_joined else "MATRIX_ROOM_MAP_UNJOINED",
    }


def sync_once(
    homeserver: str,
    token: str,
    room_roles: dict[str, str],
    since: str | None = None,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 5.0,
    *,
    session: dict | None = None,
) -> dict:
    """Perform one bounded Matrix `/sync` without exposing credentials."""

    checked_at = _now()
    if not isinstance(homeserver, str) or not homeserver.startswith(("http://", "https://")):
        return _failure(checked_at, "MATRIX_CONFIG_INVALID")
    if not isinstance(token, str) or not token or not isinstance(room_roles, dict):
        return _failure(checked_at, "MATRIX_CONFIG_INVALID")
    query = {"timeout": "0"}
    if since:
        query["since"] = since
    endpoint = homeserver.rstrip("/") + "/_matrix/client/v3/sync?" + urlencode(query)
    request = Request(endpoint, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return _failure(checked_at, "MATRIX_RESPONSE_TOO_LARGE")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return _failure(checked_at, "MATRIX_RESPONSE_INVALID")
    except HTTPError as exc:
        code = "MATRIX_AUTH_FAILED" if exc.code in {401, 403} else "MATRIX_UNAVAILABLE"
        return _failure(checked_at, code)
    except (URLError, OSError, TimeoutError):
        return _failure(checked_at, "MATRIX_UNAVAILABLE")
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return _failure(checked_at, "MATRIX_RESPONSE_INVALID")

    joined = payload.get("rooms", {}).get("join", {}) if isinstance(payload.get("rooms"), dict) else {}
    if since is None and (
        not isinstance(joined, dict) or not set(room_roles).issubset(set(joined))
    ):
        return _failure(checked_at, "MATRIX_ROOM_MAP_UNJOINED")
    left = payload.get("rooms", {}).get("leave", {}) if isinstance(payload.get("rooms"), dict) else {}
    if isinstance(left, dict) and set(room_roles).intersection(set(left)):
        return _failure(checked_at, "MATRIX_ROOM_MAP_UNJOINED")

    encrypted = _encrypted_rooms(payload, room_roles)
    if encrypted:
        return {
            "connected": True,
            "source_status": "UNSUPPORTED_ENCRYPTED_ROOM",
            "checked_at": checked_at,
            "last_success_at": checked_at,
            "next_batch": payload.get("next_batch") if isinstance(payload.get("next_batch"), str) else None,
            "events": [],
            "errors": [
                {"code": "UNSUPPORTED_ENCRYPTED_ROOM", "room_id": room_id}
                for room_id in encrypted
            ],
        }
    events = normalize_sync_response(payload, room_roles, session or {})
    return {
        "connected": True,
        "source_status": "LIVE",
        "checked_at": checked_at,
        "last_success_at": checked_at,
        "next_batch": payload.get("next_batch") if isinstance(payload.get("next_batch"), str) else None,
        "events": events,
        "errors": [],
    }


def _atomic_text(path: Path, content: str) -> None:
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
            handle.write(content)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _safe_errors(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    errors: list[dict[str, str]] = []
    for item in value[:16]:
        if not isinstance(item, dict) or item.get("code") not in ERROR_CODES:
            continue
        sanitized = {"code": str(item["code"])}
        room_id = item.get("room_id")
        if sanitized["code"] == "UNSUPPORTED_ENCRYPTED_ROOM" and isinstance(room_id, str) and ROOM_ID.fullmatch(room_id):
            sanitized["room_id"] = room_id
        errors.append(sanitized)
    return errors


def _cache_event(
    value: object,
    allowed_bindings: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    event_id = value.get("event_id")
    room_id = value.get("room_id")
    actor = value.get("actor")
    kind = value.get("kind")
    bindings = next((
        candidate
        for candidate in allowed_bindings
        if all(value.get(name) == expected for name, expected in candidate.items())
    ), None)
    if (
        not isinstance(event_id, str)
        or EVENT_ID.fullmatch(event_id) is None
        or value.get("validation_version") != PROJECTION_VALIDATION_VERSION
        or not isinstance(room_id, str)
        or ROOM_ID.fullmatch(room_id) is None
        or actor not in set(ROLE_ORDER) | {"human-approver"}
        or kind not in TRANSITIONS
        or not projection_actor_valid(actor, kind)
        or bindings is None
    ):
        return None
    expected_from, expected_to = TRANSITIONS[str(kind)]
    workflow_from = value.get("workflow_from")
    workflow_to = value.get("workflow_to")
    return {
        "classification": PROJECTION_CLASSIFICATION,
        "validation_version": PROJECTION_VALIDATION_VERSION,
        "event_id": event_id,
        "room_id": room_id,
        **bindings,
        "actor": actor,
        "kind": kind,
        "timestamp": value.get("timestamp") if isinstance(value.get("timestamp"), str) else None,
        "workflow_from": workflow_from if isinstance(workflow_from, str) and workflow_from else expected_from,
        "workflow_to": workflow_to if isinstance(workflow_to, str) and workflow_to else expected_to,
        "evidence_state": "OBSERVED",
        "artifact_refs": _safe_refs(value.get("artifact_refs")),
        "hash_refs": _safe_refs(value.get("hash_refs"), hashes=True),
    }


def write_observer_projection(session_root: str | Path, snapshot: dict) -> None:
    """Atomically persist a non-authoritative UI cache for one live session."""

    root = Path(session_root).resolve()
    if any(re.fullmatch(r"output-agentteams-at00[234]", part) for part in root.parts):
        raise ValueError("observer projection cannot be written beneath formal Evidence roots")
    manifest = _read_object(root / "session.json")
    if manifest.get("classification") != CLASSIFICATION:
        raise ValueError("observer projection requires a NON_FORMAL_LIVE_DEMO session")
    if not isinstance(snapshot, dict):
        raise ValueError("observer snapshot must be an object")
    source_status = snapshot.get("source_status", "DISCONNECTED")
    if source_status not in SOURCE_STATUSES:
        raise ValueError("observer snapshot has an invalid source status")
    observer = root / "observer"
    try:
        allowed_bindings = _known_session_bindings(root, manifest)
    except ValueError as exc:
        failed_status = {
            "classification": PROJECTION_CLASSIFICATION,
            "connected": False,
            "source_status": "DISCONNECTED",
            "checked_at": snapshot.get("checked_at"),
            "last_success_at": snapshot.get("last_success_at"),
            "next_batch": snapshot.get("next_batch"),
            "errors": [{"code": "RECOVERY_BINDING_INVALID"}],
        }
        _atomic_text(
            observer / "source_status.json",
            json.dumps(failed_status, ensure_ascii=False, indent=2) + "\n",
        )
        raise ValueError("recovery binding validation failed") from exc
    status = {
        "classification": PROJECTION_CLASSIFICATION,
        "connected": snapshot.get("connected") is True,
        "source_status": source_status,
        "checked_at": snapshot.get("checked_at"),
        "last_success_at": snapshot.get("last_success_at"),
        "next_batch": snapshot.get("next_batch"),
        "errors": _safe_errors(snapshot.get("errors")),
    }
    _atomic_text(
        observer / "source_status.json",
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
    )

    event_path = observer / "normalized_events.jsonl"
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    if event_path.is_file():
        for line in event_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("observer event cache is malformed") from exc
            sanitized = _cache_event(record, allowed_bindings)
            if sanitized is None:
                continue
            if sanitized["event_id"] in seen:
                continue
            seen.add(sanitized["event_id"])
            records.append(sanitized)
    incoming = snapshot.get("events", [])
    if isinstance(incoming, list):
        for item in incoming:
            record = _cache_event(item, [allowed_bindings[-1]])
            if record is None:
                continue
            if record["event_id"] in seen:
                continue
            seen.add(record["event_id"])
            records.append(record)
    content = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    _atomic_text(event_path, content)
