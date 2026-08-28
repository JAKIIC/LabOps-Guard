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
from labops.reviewer_state import EXPECTED_TIMELINE


PROJECTION_CLASSIFICATION = "NON_AUTHORITATIVE_UI_PROJECTION"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EVENTS_PER_SYNC = 256
ROOM_ID = re.compile(r"^![^:\s]+:\S+$")
EVENT_ID = re.compile(r"^\$\S+$")
EVENT_KIND = re.compile(r"LABOPS_EVENT_KIND\s*[:=]\s*([a-z_]+)", re.IGNORECASE)
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
TRANSITIONS = {kind: (source, target) for kind, source, target in EXPECTED_TIMELINE}
SOURCE_STATUSES = {"LIVE", "STALE", "DISCONNECTED", "UNSUPPORTED_ENCRYPTED_ROOM"}
ERROR_CODES = {
    "MATRIX_AUTH_FAILED",
    "MATRIX_UNAVAILABLE",
    "MATRIX_CONFIG_INVALID",
    "MATRIX_RESPONSE_TOO_LARGE",
    "MATRIX_RESPONSE_INVALID",
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


def _session_bindings(session: dict[str, Any]) -> list[str]:
    names = ("session_id", "task_instance_id", "incident_instance_id", "run_id")
    values = [session.get(name) for name in names]
    if any(not isinstance(value, str) or not value for value in values):
        return []
    return [str(value) for value in values]


def _normalized_event(
    event: dict[str, Any],
    room_id: str,
    agent_id: str,
    bindings: list[str],
) -> dict[str, Any] | None:
    if event.get("type") != "m.room.message":
        return None
    event_id = event.get("event_id")
    content = event.get("content")
    if not isinstance(event_id, str) or EVENT_ID.fullmatch(event_id) is None or not isinstance(content, dict):
        return None
    searchable = json.dumps(content, ensure_ascii=False, sort_keys=True)
    if not bindings or any(binding not in searchable for binding in bindings):
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
    expected_from, expected_to = TRANSITIONS[kind]
    workflow_from = structured.get("workflow_from")
    workflow_to = structured.get("workflow_to")
    if not isinstance(workflow_from, str) or not workflow_from:
        workflow_from = expected_from
    if not isinstance(workflow_to, str) or not workflow_to:
        workflow_to = expected_to
    actor = agent_id
    if kind == "approval_granted" and structured.get("actor") == "human-approver":
        actor = "human-approver"
    return {
        "classification": PROJECTION_CLASSIFICATION,
        "event_id": event_id,
        "room_id": room_id,
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


def _cache_event(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    event_id = value.get("event_id")
    room_id = value.get("room_id")
    actor = value.get("actor")
    kind = value.get("kind")
    if (
        not isinstance(event_id, str)
        or EVENT_ID.fullmatch(event_id) is None
        or not isinstance(room_id, str)
        or ROOM_ID.fullmatch(room_id) is None
        or actor not in set(ROLE_ORDER) | {"human-approver"}
        or kind not in TRANSITIONS
    ):
        return None
    expected_from, expected_to = TRANSITIONS[str(kind)]
    workflow_from = value.get("workflow_from")
    workflow_to = value.get("workflow_to")
    return {
        "classification": PROJECTION_CLASSIFICATION,
        "event_id": event_id,
        "room_id": room_id,
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
            sanitized = _cache_event(record)
            if sanitized is None:
                raise ValueError("observer event cache contains an invalid record")
            if sanitized["event_id"] in seen:
                continue
            seen.add(sanitized["event_id"])
            records.append(sanitized)
    incoming = snapshot.get("events", [])
    if isinstance(incoming, list):
        for item in incoming:
            record = _cache_event(item)
            if record is None:
                continue
            if record["event_id"] in seen:
                continue
            seen.add(record["event_id"])
            records.append(record)
    content = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    _atomic_text(event_path, content)
