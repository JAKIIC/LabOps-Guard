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

from labops.live_demo import CLASSIFICATION, FORMAL_ROOTS


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
                    "python3",
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


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_backup_root(
    project_root: Path,
    sessions_root: Path,
    *,
    create: bool,
) -> Path | None:
    candidate = sessions_root / "_runtime-backups"
    if candidate.exists():
        if _is_link_or_reparse(candidate) or not candidate.is_dir():
            raise LiveDemoStateError("Manager backup directory is unsafe")
    elif not create:
        return None
    else:
        candidate.mkdir()
    if _is_link_or_reparse(candidate):
        raise LiveDemoStateError("Manager backup directory is unsafe")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(sessions_root)
    except ValueError as exc:
        raise LiveDemoStateError("Manager backup directory escapes live sessions") from exc
    if any(_inside(resolved, project_root / relative) for relative in FORMAL_ROOTS):
        raise LiveDemoStateError("Manager backup directory overlaps formal Evidence")
    return resolved


def _validated_abort_outcomes(
    project_root: Path,
    sessions_root: Path,
    live_task_ids: list[str],
    state_sha256: str,
    archived_at: str,
    *,
    allow_matching_existing: bool = False,
) -> list[tuple[Path, dict[str, Any]]]:
    outcomes: list[tuple[Path, dict[str, Any]]] = []
    for task_id in live_task_ids:
        match = LIVE_TASK_ID.fullmatch(task_id)
        if match is None:
            raise LiveDemoStateError("live task identifier is invalid")
        session_id = match.group("session")
        candidate = sessions_root / session_id
        if candidate.is_symlink() or not candidate.is_dir():
            raise LiveDemoStateError(f"live session root is missing or unsafe: {session_id}")
        session_root = candidate.resolve()
        try:
            session_root.relative_to(sessions_root)
        except ValueError as exc:
            raise LiveDemoStateError(f"live session root escapes the sessions root: {session_id}") from exc
        if any(_inside(session_root, project_root / relative) for relative in FORMAL_ROOTS):
            raise LiveDemoStateError("live session root overlaps formal Evidence")
        manifest_path = session_root / "session.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise LiveDemoStateError(f"live session manifest is missing or unsafe: {session_id}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LiveDemoStateError(f"live session manifest is invalid: {session_id}") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != "1.0"
            or manifest.get("classification") != CLASSIFICATION
            or manifest.get("session_id") != session_id
            or manifest.get("task_instance_id") != task_id
        ):
            raise LiveDemoStateError(f"live session manifest binding is invalid: {session_id}")
        outcome_path = session_root / "session_outcome.json"
        payload = {
                "schema_version": "1.0",
                "status": "ABORTED_REHEARSAL",
                "session_id": session_id,
                "task_instance_id": task_id,
                "reason": "archived before a clean recording",
                "archived_at": archived_at,
                "manager_state_backup_sha256": state_sha256,
                "evidence_deleted": False,
        }
        if outcome_path.is_symlink():
            raise LiveDemoStateError(f"existing session outcome must not be overwritten: {session_id}")
        if outcome_path.exists():
            if not allow_matching_existing:
                raise LiveDemoStateError(f"existing session outcome must not be overwritten: {session_id}")
            try:
                existing = json.loads(outcome_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise LiveDemoStateError(f"existing session outcome is invalid: {session_id}") from exc
            if existing != payload:
                raise LiveDemoStateError(f"existing session outcome conflicts with archive: {session_id}")
        outcomes.append((outcome_path, payload))
    return outcomes


def _write_abort_outcomes(
    outcomes: list[tuple[Path, dict[str, Any]]],
) -> list[Path]:
    written: list[Path] = []
    try:
        for path, payload in outcomes:
            encoded = (
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            if path.exists():
                if path.read_bytes() != encoded:
                    raise LiveDemoStateError("existing session outcome conflicts with archive")
                written.append(path)
                continue
            with path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            written.append(path)
    except OSError as exc:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise LiveDemoStateError("session outcomes could not be written atomically") from exc
    return written


def _write_pending_transaction(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LiveDemoStateError("archive transaction journal is unreadable") from exc
        if existing != payload:
            raise LiveDemoStateError("archive transaction journal conflicts with current request")


def _pending_transaction(backup_root: Path | None) -> tuple[Path, dict[str, Any]] | None:
    if backup_root is None:
        return None
    paths = sorted(backup_root.glob("archive-*.pending.json"))
    if len(paths) > 1:
        raise LiveDemoStateError("multiple archive transactions require manual inspection")
    if not paths:
        return None
    path = paths[0]
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise LiveDemoStateError("archive transaction journal is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveDemoStateError("archive transaction journal is unreadable") from exc
    if not isinstance(value, dict):
        raise LiveDemoStateError("archive transaction journal is invalid")
    return path, value


def _finish_pending_transaction(
    project: Path,
    sessions: Path,
    manager: Any,
    current: bytes,
    journal_path: Path,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    required = (
        "original_sha256",
        "replacement_sha256",
        "archived_at",
        "live_task_ids",
        "formal_task_count",
        "backup_name",
    )
    if any(name not in transaction for name in required):
        raise LiveDemoStateError("archive transaction journal is incomplete")
    live_ids = transaction["live_task_ids"]
    if not isinstance(live_ids, list) or not live_ids or any(
        not isinstance(item, str) or LIVE_TASK_ID.fullmatch(item) is None
        for item in live_ids
    ):
        raise LiveDemoStateError("archive transaction task bindings are invalid")
    original_sha = transaction["original_sha256"]
    replacement_sha = transaction["replacement_sha256"]
    if not isinstance(original_sha, str) or not isinstance(replacement_sha, str):
        raise LiveDemoStateError("archive transaction hashes are invalid")
    backup = journal_path.parent / str(transaction["backup_name"])
    if backup.is_symlink() or not backup.is_file() or hashlib.sha256(backup.read_bytes()).hexdigest() != original_sha:
        raise LiveDemoStateError("archive transaction Manager backup is invalid")

    current_sha = hashlib.sha256(current).hexdigest()
    if current_sha == original_sha:
        try:
            state = json.loads(current.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LiveDemoStateError("Manager state is not valid UTF-8 JSON") from exc
        retained, observed_live_ids, formal_count = _partition_active_tasks(state.get("active_tasks"))
        if observed_live_ids != live_ids or formal_count != transaction["formal_task_count"]:
            raise LiveDemoStateError("archive transaction no longer matches Manager state")
        replacement_state = dict(state)
        replacement_state["active_tasks"] = retained
        replacement = (
            json.dumps(replacement_state, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        if hashlib.sha256(replacement).hexdigest() != replacement_sha:
            raise LiveDemoStateError("archive transaction replacement hash is invalid")
        manager.replace_state(original_sha, replacement)
    elif current_sha != replacement_sha:
        raise LiveDemoStateError("Manager state diverged from pending archive transaction")

    outcomes = _validated_abort_outcomes(
        project,
        sessions,
        live_ids,
        original_sha,
        str(transaction["archived_at"]),
        allow_matching_existing=True,
    )
    written = _write_abort_outcomes(outcomes)
    journal_path.unlink()
    return {
        "status": "ARCHIVED",
        "archived_live_tasks": len(live_ids),
        "formal_task_count": int(transaction["formal_task_count"]),
        "session_outcomes_written": len(written),
        "backup": backup.name,
        "manager_state_before_sha256": original_sha,
        "evidence_deleted": False,
    }


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
    if any(_inside(sessions, project / relative) for relative in FORMAL_ROOTS):
        raise LiveDemoStateError("live sessions root overlaps formal Evidence")
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
    existing_backup_root = _safe_backup_root(project, sessions, create=False)
    pending = _pending_transaction(existing_backup_root)
    if pending is not None:
        return _finish_pending_transaction(
            project,
            sessions,
            manager,
            original,
            pending[0],
            pending[1],
        )
    if not live_ids:
        return {**preview, "status": "CLEAN", "confirmation_required": None}

    archived_at = _utc_now()
    outcomes = _validated_abort_outcomes(
        project, sessions, live_ids, original_sha256, archived_at
    )
    updated = dict(state)
    updated["active_tasks"] = retained
    replacement = (
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    replacement_sha256 = hashlib.sha256(replacement).hexdigest()
    backup_root = _safe_backup_root(project, sessions, create=True)
    assert backup_root is not None
    backup = backup_root / f"manager-state-{original_sha256}.json"
    _write_backup(backup, original)
    journal = backup_root / f"archive-{original_sha256}.pending.json"
    transaction = {
        "schema_version": "1.0",
        "original_sha256": original_sha256,
        "replacement_sha256": replacement_sha256,
        "archived_at": archived_at,
        "live_task_ids": live_ids,
        "formal_task_count": formal_count,
        "backup_name": backup.name,
    }
    _write_pending_transaction(journal, transaction)
    return _finish_pending_transaction(
        project, sessions, manager, original, journal, transaction
    )
