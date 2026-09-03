"""Safe inspection and archival of stale non-formal live-demo Manager tasks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARCHIVE_CONFIRMATION = "ARCHIVE_LIVE_REHEARSALS"
MANAGER_CONTAINER = "hiclaw-manager"
MANAGER_STATE_PATH = "/root/manager-workspace/state.json"
LIVE_TASK_ID = re.compile(r"^LIVE-TASK-(?P<session>\d{8}-\d{3})$")


class LiveDemoStateError(ValueError):
    """Raised when recording state cannot be changed without ambiguity."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _task_id(key: Any, value: Any) -> str:
    candidate = key
    if key is None and isinstance(value, str):
        candidate = value
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
        raise LiveDemoStateError("Manager active task has no stable identifier")
    return candidate


def _partition_active_tasks(active_tasks: Any) -> tuple[Any, list[str], int]:
    if isinstance(active_tasks, dict):
        retained: Any = {}
        entries = active_tasks.items()
    elif isinstance(active_tasks, list):
        retained = []
        entries = ((None, value) for value in active_tasks)
    else:
        raise LiveDemoStateError("Manager active_tasks must be an object or array")

    live_ids: list[str] = []
    formal_count = 0
    for key, value in entries:
        identifier = _task_id(key, value)
        if LIVE_TASK_ID.fullmatch(identifier):
            live_ids.append(identifier)
            continue
        formal_count += 1
        if isinstance(retained, dict):
            retained[key] = value
        else:
            retained.append(value)
    return retained, sorted(live_ids), formal_count


def inspect_recording_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a payload-free summary of active formal and live tasks."""

    if not isinstance(state, dict) or "active_tasks" not in state:
        raise LiveDemoStateError("Manager state lacks active_tasks")
    retained, live_ids, formal_count = _partition_active_tasks(
        state["active_tasks"]
    )
    retained_count = len(retained)
    return {
        "status": "STALE_LIVE_TASKS" if live_ids else "CLEAN",
        "active_task_count": retained_count + len(live_ids),
        "formal_task_count": formal_count,
        "live_task_count": len(live_ids),
        "live_task_ids": live_ids,
    }


class DockerManagerStateRuntime:
    """Narrow Docker boundary for one fixed Manager state document."""

    _REPLACE_SCRIPT = """
import hashlib
import os
import sys
import tempfile

path = sys.argv[1]
expected = sys.argv[2]
replacement = sys.stdin.buffer.read()
with open(path, "rb") as handle:
    current = handle.read()
if hashlib.sha256(current).hexdigest() != expected:
    raise SystemExit(73)
directory = os.path.dirname(path)
fd, temporary = tempfile.mkstemp(prefix=".labops-state-", dir=directory)
try:
    with os.fdopen(fd, "wb") as handle:
        handle.write(replacement)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
""".strip()

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.docker = shutil.which("docker")
        if not self.docker:
            raise LiveDemoStateError("Docker is unavailable")

    def read_state(self) -> bytes:
        try:
            result = subprocess.run(
                [
                    self.docker,
                    "exec",
                    MANAGER_CONTAINER,
                    "cat",
                    MANAGER_STATE_PATH,
                ],
                cwd=self.project_root,
                check=False,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveDemoStateError("Cannot read Manager state") from exc
        if result.returncode != 0 or len(result.stdout) > 8 * 1024 * 1024:
            raise LiveDemoStateError("Cannot read a bounded Manager state document")
        return result.stdout

    def replace_state(self, expected_sha256: str, payload: bytes) -> None:
        try:
            result = subprocess.run(
                [
                    self.docker,
                    "exec",
                    "-i",
                    MANAGER_CONTAINER,
                    "python",
                    "-c",
                    self._REPLACE_SCRIPT,
                    MANAGER_STATE_PATH,
                    expected_sha256,
                ],
                cwd=self.project_root,
                input=payload,
                check=False,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveDemoStateError("Cannot replace Manager state") from exc
        if result.returncode == 73:
            raise LiveDemoStateError("Manager state changed concurrently")
        if result.returncode != 0:
            raise LiveDemoStateError("Manager state replacement failed")


def _write_backup(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != payload:
            raise LiveDemoStateError("Existing Manager state backup has wrong content")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
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
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _mark_aborted_sessions(
    sessions_root: Path,
    live_task_ids: list[str],
    state_sha256: str,
    archived_at: str,
) -> int:
    written = 0
    for task_id in live_task_ids:
        match = LIVE_TASK_ID.fullmatch(task_id)
        if match is None:
            continue
        session_id = match.group("session")
        session_root = sessions_root / session_id
        manifest_path = session_root / "session.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(manifest, dict)
            or manifest.get("task_instance_id") != task_id
        ):
            continue
        _write_json_atomic(
            session_root / "session_outcome.json",
            {
                "schema_version": "1.0",
                "status": "ABORTED_REHEARSAL",
                "session_id": session_id,
                "task_instance_id": task_id,
                "reason": "archived before a clean recording",
                "archived_at": archived_at,
                "manager_state_backup_sha256": state_sha256,
                "evidence_deleted": False,
            },
        )
        written += 1
    return written


def archive_live_rehearsals(
    project_root: str | Path,
    sessions_root: str | Path,
    *,
    confirm: str | None = None,
    runtime: Any | None = None,
) -> dict[str, Any]:
    """Preview or archive stale live tasks without deleting session evidence."""

    project = Path(project_root).resolve()
    sessions = Path(sessions_root).resolve()
    manager = runtime or DockerManagerStateRuntime(project)
    original = manager.read_state()
    original_sha256 = hashlib.sha256(original).hexdigest()
    try:
        state = json.loads(original.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LiveDemoStateError("Manager state is not valid UTF-8 JSON") from exc
    if not isinstance(state, dict) or "active_tasks" not in state:
        raise LiveDemoStateError("Manager state lacks active_tasks")
    retained, live_ids, formal_count = _partition_active_tasks(
        state["active_tasks"]
    )
    preview = {
        "status": "PREVIEW",
        "confirmation_required": ARCHIVE_CONFIRMATION,
        "active_task_count": formal_count + len(live_ids),
        "formal_task_count": formal_count,
        "live_task_count": len(live_ids),
        "live_task_ids": live_ids,
        "evidence_deleted": False,
    }
    if confirm is None:
        return preview
    if confirm != ARCHIVE_CONFIRMATION:
        raise LiveDemoStateError(
            f"explicit confirmation must equal {ARCHIVE_CONFIRMATION}"
        )
    if not live_ids:
        return {**preview, "status": "CLEAN", "confirmation_required": None}

    backup = (
        sessions
        / "_runtime-backups"
        / f"manager-state-{original_sha256}.json"
    )
    _write_backup(backup, original)
    updated = dict(state)
    updated["active_tasks"] = retained
    replacement = (
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manager.replace_state(original_sha256, replacement)
    archived_at = _utc_now()
    outcomes = _mark_aborted_sessions(
        sessions, live_ids, original_sha256, archived_at
    )
    return {
        "status": "ARCHIVED",
        "archived_live_tasks": len(live_ids),
        "formal_task_count": formal_count,
        "session_outcomes_written": outcomes,
        "backup": backup.name,
        "manager_state_before_sha256": original_sha256,
        "evidence_deleted": False,
    }
