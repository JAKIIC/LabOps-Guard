"""Fail-closed, read-only synchronization for live AgentTeams Evidence.

The synchronizer mirrors an external session tree for inspection, but it never
publishes canonical Evidence until an independently constructed candidate has
passed the existing live-demo verifier.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol

from labops.live_demo import (
    CLASSIFICATION,
    EVIDENCE_FILES,
    HANDOFFS,
    ROLE_ORDER,
    SESSION_ID,
    verify_session,
)
from labops.matrix_observer import (
    PROJECTION_VALIDATION_VERSION,
    active_session_binding,
)


ERROR_CODES = {
    "EVIDENCE_SOURCE_UNAVAILABLE",
    "EVIDENCE_SNAPSHOT_TOO_LARGE",
    "EVIDENCE_PATH_REJECTED",
    "EVIDENCE_BINDING_MISMATCH",
    "EVIDENCE_SCHEMA_INVALID",
    "EVIDENCE_HASH_CONFLICT",
    "EVIDENCE_INCOMPLETE",
}
HANDOFF_KINDS = (
    "manager_to_collector",
    "collector_to_rca",
    "rca_to_planner",
    "approval_pending",
    "executor_to_auditor",
    "verification_completed",
)


@dataclass(frozen=True)
class SnapshotLimits:
    max_files: int = 256
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if min(self.max_files, self.max_file_bytes, self.max_total_bytes) <= 0:
            raise ValueError("snapshot limits must be positive")


@dataclass(frozen=True)
class SyncResult:
    status: str
    mirror_digest: str | None
    published: bool
    errors: tuple[str, ...]
    checked_at: str

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "mirror_digest": self.mirror_digest,
            "published": self.published,
            "errors": list(self.errors),
            "checked_at": self.checked_at,
        }


class EvidenceSyncError(RuntimeError):
    def __init__(self, code: str):
        if code not in ERROR_CODES:
            raise ValueError("unknown Evidence sync error code")
        super().__init__(code)
        self.code = code


class EvidenceSource(Protocol):
    limits: SnapshotLimits

    def snapshot(self, session_id: str, destination: Path) -> Path:
        """Copy one source session into ``destination`` without source writes."""


def _checked_at(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise EvidenceSyncError("EVIDENCE_PATH_REJECTED") from exc
    normalized = relative.as_posix()
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or ".." in pure.parts
        or re.match(r"^[A-Za-z]:/", normalized)
    ):
        raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
    return normalized


def _is_reparse(path: Path) -> bool:
    try:
        record = path.lstat()
    except OSError as exc:
        raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE") from exc
    attributes = getattr(record, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _scan_snapshot(root: Path, limits: SnapshotLimits) -> list[dict]:
    if not root.is_dir() or _is_reparse(root):
        raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
    entries: list[dict] = []
    total = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(directories):
            directory = current_path / name
            _safe_relative(directory, root)
            if _is_reparse(directory):
                raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
        for name in files:
            path = current_path / name
            relative = _safe_relative(path, root)
            if _is_reparse(path):
                raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
            try:
                record = path.stat()
            except OSError as exc:
                raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE") from exc
            if not stat.S_ISREG(record.st_mode):
                raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
            if len(entries) + 1 > limits.max_files:
                raise EvidenceSyncError("EVIDENCE_SNAPSHOT_TOO_LARGE")
            if record.st_size > limits.max_file_bytes:
                raise EvidenceSyncError("EVIDENCE_SNAPSHOT_TOO_LARGE")
            total += record.st_size
            if total > limits.max_total_bytes:
                raise EvidenceSyncError("EVIDENCE_SNAPSHOT_TOO_LARGE")
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
            except OSError as exc:
                raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE") from exc
            entries.append(
                {"path": relative, "size": record.st_size, "sha256": digest.hexdigest()}
            )
    entries.sort(key=lambda item: item["path"])
    return entries


class DirectoryEvidenceSource:
    """Read-only local-directory adapter used by tests and local rehearsals."""

    def __init__(
        self,
        root: str | Path,
        limits: SnapshotLimits | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.limits = limits or SnapshotLimits()

    def snapshot(self, session_id: str, destination: Path) -> Path:
        if SESSION_ID.fullmatch(session_id) is None:
            raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
        source = self.root / session_id
        if not source.is_dir() or _is_reparse(source):
            raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE")
        destination.mkdir(parents=True, exist_ok=False)
        entries = _scan_snapshot(source, self.limits)
        for item in entries:
            relative = PurePosixPath(item["path"])
            source_path = source.joinpath(*relative.parts)
            target_path = destination.joinpath(*relative.parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(source_path, target_path, follow_symlinks=False)
            except OSError as exc:
                raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE") from exc
        return destination


class DockerEvidenceSource:
    """Read-only Docker ``cp`` adapter for the Manager shared filesystem."""

    _CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def __init__(
        self,
        container: str,
        root: str,
        limits: SnapshotLimits | None = None,
    ) -> None:
        if self._CONTAINER.fullmatch(container) is None:
            raise ValueError("invalid Evidence source container")
        pure_root = PurePosixPath(root)
        if not pure_root.is_absolute() or ".." in pure_root.parts:
            raise ValueError("invalid Evidence source root")
        self.container = container
        self.root = str(pure_root)
        self.limits = limits or SnapshotLimits()

    def snapshot(self, session_id: str, destination: Path) -> Path:
        if SESSION_ID.fullmatch(session_id) is None:
            raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
        docker = shutil.which("docker")
        if docker is None:
            raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE")
        destination.mkdir(parents=True, exist_ok=False)
        source = f"{self.container}:{self.root.rstrip('/')}/{session_id}/."
        try:
            result = subprocess.run(
                [docker, "cp", source, str(destination)],
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE") from exc
        if result.returncode != 0:
            raise EvidenceSyncError("EVIDENCE_SOURCE_UNAVAILABLE")
        _scan_snapshot(destination, self.limits)
        return destination


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _atomic_replace_directory(source: Path, target: Path) -> None:
    backup = target.with_name(f".{target.name}.{os.getpid()}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    moved_previous = False
    try:
        if target.exists():
            target.replace(backup)
            moved_previous = True
        source.replace(target)
    except OSError:
        if moved_previous and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _mirror_digest(entries: list[dict]) -> str:
    material = "\n".join(
        f"{item['path']}:{item['size']}:{item['sha256']}" for item in entries
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _load_session(session_root: Path, session_id: str) -> dict:
    try:
        value = json.loads((session_root / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise EvidenceSyncError("EVIDENCE_BINDING_MISMATCH") from exc
    if (
        not isinstance(value, dict)
        or value.get("classification") != CLASSIFICATION
        or value.get("session_id") != session_id
    ):
        raise EvidenceSyncError("EVIDENCE_BINDING_MISMATCH")
    return value


def _read_mirror_json(mirror: Path, relative: str) -> dict:
    try:
        value = json.loads((mirror / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise EvidenceSyncError("EVIDENCE_SCHEMA_INVALID") from exc
    if not isinstance(value, dict):
        raise EvidenceSyncError("EVIDENCE_SCHEMA_INVALID")
    return value


def _raw_mapping(run_id: str) -> dict[str, str]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", run_id) is None:
        raise EvidenceSyncError("EVIDENCE_BINDING_MISMATCH")
    run_root = f"runs/{run_id}"
    return {
        "approval_grant.json": "artifacts/DEMO-EVAL-DRIFT-004/approval_grant.json",
        "gateway_request.json": f"{run_root}/gateway_request.json",
        "gateway_response.json": f"{run_root}/gateway_response.json",
        "runner/run_result.json": f"{run_root}/run_result.json",
        "runner/metrics.json": f"{run_root}/metrics.json",
        "runner/artifact_manifest.json": f"{run_root}/artifact_manifest.json",
        "runner/stdout.log": f"{run_root}/stdout.log",
        "runner/stderr.log": f"{run_root}/stderr.log",
        "verification.json": "verification/verification_report.json",
        "trace.jsonl": "trace.jsonl",
    }


def _optional_raw_mapping(run_id: str) -> dict[str, str]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", run_id) is None:
        raise EvidenceSyncError("EVIDENCE_BINDING_MISMATCH")
    return {"runner/status.json": f"runs/{run_id}/status.json"}


def _artifact_refs(event: dict) -> tuple[list[str], list[str]]:
    direct_input = event.get("input_artifact_refs")
    direct_output = event.get("output_artifact_refs")
    if isinstance(direct_input, list) and isinstance(direct_output, list):
        inputs = [item for item in direct_input if isinstance(item, str) and item]
        outputs = [item for item in direct_output if isinstance(item, str) and item]
        if inputs and outputs:
            return inputs, outputs
    refs = event.get("artifact_refs")
    refs = [item for item in refs if isinstance(item, str) and item] if isinstance(refs, list) else []
    if len(refs) < 2:
        raise EvidenceSyncError("EVIDENCE_INCOMPLETE")
    return [refs[0]], refs[1:]


def _matrix_documents(matrix_snapshot: dict, bindings: dict) -> tuple[dict, dict]:
    events = matrix_snapshot.get("events") if isinstance(matrix_snapshot, dict) else None
    if not isinstance(events, list):
        raise EvidenceSyncError("EVIDENCE_INCOMPLETE")
    selected: list[dict] = []
    handoffs: list[dict] = []
    seen_ids: set[str] = set()
    for index, ((source, target), kind) in enumerate(zip(HANDOFFS, HANDOFF_KINDS), 1):
        candidates = [
            event
            for event in events
            if isinstance(event, dict)
            and event.get("kind") == kind
            and event.get("actor") == source
            and event.get("validation_version") == PROJECTION_VALIDATION_VERSION
            and all(event.get(name) == value for name, value in bindings.items())
        ]
        if len(candidates) != 1:
            raise EvidenceSyncError("EVIDENCE_INCOMPLETE")
        event = candidates[0]
        event_id = event.get("event_id")
        room_id = event.get("room_id")
        timestamp = event.get("timestamp")
        if (
            not isinstance(event_id, str)
            or not event_id.startswith("$")
            or event_id in seen_ids
            or not isinstance(room_id, str)
            or not room_id.startswith("!")
            or not isinstance(timestamp, str)
            or not timestamp
        ):
            raise EvidenceSyncError("EVIDENCE_SCHEMA_INVALID")
        inputs, outputs = _artifact_refs(event)
        seen_ids.add(event_id)
        selected.append(
            {
                "event_id": event_id,
                "sender_agent": source,
                "room_id": room_id,
                "timestamp": timestamp,
                "kind": kind,
                **bindings,
            }
        )
        handoffs.append(
            {
                "handoff": index,
                "from_agent": source,
                "to_agent": target,
                "matrix_event_id": event_id,
                "status": "COMPLETED",
                "input_artifact_refs": inputs,
                "output_artifact_refs": outputs,
            }
        )
    return {"events": selected}, {"agent_order": ROLE_ORDER, "handoffs": handoffs}


def _validate_verification(mirror: Path, bindings: dict) -> None:
    verification = _read_mirror_json(
        mirror, "verification/verification_report.json"
    )
    required = ("decision", "verified_by", "resolution_status")
    if any(not isinstance(verification.get(name), str) or not verification.get(name) for name in required):
        raise EvidenceSyncError("EVIDENCE_SCHEMA_INVALID")
    if any(verification.get(name) != value for name, value in bindings.items()):
        raise EvidenceSyncError("EVIDENCE_BINDING_MISMATCH")
    checks = verification.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise EvidenceSyncError("EVIDENCE_SCHEMA_INVALID")


def _validate_optional_runner_status(mirror: Path, relative: str, run_id: str) -> None:
    status = _read_mirror_json(mirror, relative)
    if status.get("run_id") != run_id:
        raise EvidenceSyncError("EVIDENCE_BINDING_MISMATCH")
    if status.get("status") != "completed" or not isinstance(
        status.get("simulated"), bool
    ):
        raise EvidenceSyncError("EVIDENCE_SCHEMA_INVALID")


def _candidate_error_code(errors: object) -> str:
    text = " ".join(str(item).lower() for item in errors) if isinstance(errors, list) else ""
    if "hash" in text or "sha" in text:
        return "EVIDENCE_HASH_CONFLICT"
    if "bound" in text or "binding" in text or "belongs" in text:
        return "EVIDENCE_BINDING_MISMATCH"
    if "missing" in text or "incomplete" in text or "handoff" in text:
        return "EVIDENCE_INCOMPLETE"
    return "EVIDENCE_SCHEMA_INVALID"


def _build_and_verify_candidate(
    project_root: Path,
    session_root: Path,
    mirror: Path,
    session_id: str,
    matrix_snapshot: dict,
) -> Path:
    active_binding = active_session_binding(session_root)
    bindings = {
        name: active_binding[name]
        for name in (
            "session_id",
            "task_instance_id",
            "incident_instance_id",
            "attempt_id",
            "run_id",
        )
    }
    mapping = _raw_mapping(bindings["run_id"])
    optional_mapping = {
        target: source
        for target, source in _optional_raw_mapping(bindings["run_id"]).items()
        if (mirror / source).is_file()
    }
    missing = [source for source in mapping.values() if not (mirror / source).is_file()]
    if missing:
        raise EvidenceSyncError("EVIDENCE_INCOMPLETE")
    _validate_verification(mirror, bindings)
    for source in optional_mapping.values():
        _validate_optional_runner_status(mirror, source, bindings["run_id"])
    matrix_document, handoff_document = _matrix_documents(matrix_snapshot, bindings)

    candidate_parent = Path(
        tempfile.mkdtemp(prefix=".evidence-candidate-", dir=str(session_root / "observer"))
    )
    candidate_session = candidate_parent / session_id
    evidence = candidate_session / "evidence"
    evidence.mkdir(parents=True)
    try:
        shutil.copyfile(session_root / "session.json", candidate_session / "session.json")
        recovery = session_root / "recovery"
        if recovery.is_dir():
            shutil.copytree(recovery, candidate_session / "recovery", symlinks=False)
        for target, source in mapping.items():
            destination = evidence.joinpath(*PurePosixPath(target).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mirror / source, destination)
        for target, source in optional_mapping.items():
            destination = evidence.joinpath(*PurePosixPath(target).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mirror / source, destination)
        (evidence / "matrix_events.json").write_text(
            json.dumps(matrix_document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (evidence / "handoff_manifest.json").write_text(
            json.dumps(handoff_document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        expected_files = set(EVIDENCE_FILES) | set(optional_mapping)
        if {
            path.relative_to(evidence).as_posix()
            for path in evidence.rglob("*")
            if path.is_file()
        } != expected_files:
            raise EvidenceSyncError("EVIDENCE_INCOMPLETE")
        verification = verify_session(project_root, candidate_parent, session_id)
        if verification.get("status") != "VERIFIED" or verification.get("errors") != []:
            raise EvidenceSyncError(_candidate_error_code(verification.get("errors")))
        return candidate_parent
    except Exception:
        if candidate_parent.exists():
            shutil.rmtree(candidate_parent)
        raise


def sync_live_evidence(
    project_root: str | Path,
    sessions_root: str | Path,
    session_id: str,
    source: EvidenceSource,
    matrix_snapshot: dict,
    now: datetime,
) -> dict:
    """Mirror one live source snapshot and fail closed until it is complete."""

    if SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("session must use YYYYMMDD-NNN")
    project = Path(project_root).resolve()
    session_root = Path(sessions_root).resolve() / session_id
    _load_session(session_root, session_id)
    observer = session_root / "observer"
    observer.mkdir(parents=True, exist_ok=True)
    checked_at = _checked_at(now)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=".evidence-snapshot-", dir=str(observer))
    )
    staging = staging_parent / "snapshot"
    candidate_parent: Path | None = None
    try:
        snapshot = source.snapshot(session_id, staging)
        if snapshot.resolve() != staging.resolve():
            raise EvidenceSyncError("EVIDENCE_PATH_REJECTED")
        entries = _scan_snapshot(staging, source.limits)
        digest = _mirror_digest(entries)
        (staging / "manifest.json").write_text(
            json.dumps({"files": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _atomic_replace_directory(staging, observer / "evidence-mirror")
        try:
            candidate_parent = _build_and_verify_candidate(
                project,
                session_root,
                observer / "evidence-mirror",
                session_id,
                matrix_snapshot,
            )
        except EvidenceSyncError as exc:
            result = SyncResult(
                status="MIRRORED",
                mirror_digest=digest,
                published=False,
                errors=(exc.code,),
                checked_at=checked_at,
            )
        else:
            candidate_evidence = candidate_parent / session_id / "evidence"
            _atomic_replace_directory(candidate_evidence, session_root / "evidence")
            result = SyncResult(
                status="VERIFIED",
                mirror_digest=digest,
                published=True,
                errors=(),
                checked_at=checked_at,
            )
    except EvidenceSyncError as exc:
        result = SyncResult(
            status="BLOCKED",
            mirror_digest=None,
            published=False,
            errors=(exc.code,),
            checked_at=checked_at,
        )
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent)
        if candidate_parent is not None and candidate_parent.exists():
            shutil.rmtree(candidate_parent)
    payload = result.as_dict()
    _atomic_json(observer / "evidence_sync.json", payload)
    return payload
