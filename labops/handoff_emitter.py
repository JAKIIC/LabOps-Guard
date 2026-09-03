"""Standalone, fail-closed Matrix handoff emission for AgentTeams Skills.

This module intentionally uses only the Python standard library so the same
file can be copied into an OpenClaw Skill package and executed in a Worker
container without installing the LabOps package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


SESSION_ID = re.compile(r"^[0-9]{8}-[0-9]{3}$")
ROOM_ID = re.compile(r"^![^:\s]+:\S+$")
MATRIX_USER_ID = re.compile(r"^@[^:\s]+:\S+$")
EVENT_KIND = re.compile(r"^[a-z][a-z_]*$")
RUN_ID = re.compile(r"^RUN-LABOPS-AT-004-AGENTTEAMS-[0-9]{3}$")
MATRIX_EVENT_ID = re.compile(r"^\$\S+$")
RECEIPT_DIRECTORY = ".labops-handoff-receipts"


class HandoffEmissionError(ValueError):
    """Raised before or during an untrusted handoff emission."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffEmissionError("runtime binding is unreadable") from exc
    if not isinstance(value, dict):
        raise HandoffEmissionError("runtime binding must contain an object")
    return value


def _artifact_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HandoffEmissionError("artifact path must be a non-empty POSIX-relative path")
    if re.match(r"^[A-Za-z]:", value):
        raise HandoffEmissionError("artifact path must not use a drive or absolute path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HandoffEmissionError("artifact path must stay inside the session namespace")
    return path.as_posix()


def _validated_route(binding: dict[str, Any], event_kind: object) -> dict[str, str]:
    if not isinstance(event_kind, str) or EVENT_KIND.fullmatch(event_kind) is None:
        raise HandoffEmissionError("event kind is invalid")
    events = binding.get("events")
    route = events.get(event_kind) if isinstance(events, dict) else None
    if not isinstance(route, dict):
        raise HandoffEmissionError("event kind is not allowed for this runtime")
    room_id = route.get("room_id")
    recipient = route.get("recipient_matrix_id")
    if not isinstance(room_id, str) or ROOM_ID.fullmatch(room_id) is None:
        raise HandoffEmissionError("runtime event room binding is invalid")
    if not isinstance(recipient, str) or MATRIX_USER_ID.fullmatch(recipient) is None:
        raise HandoffEmissionError("runtime event recipient binding is invalid")
    if room_id.split(":", 1)[1].lower() != recipient.split(":", 1)[1].lower():
        raise HandoffEmissionError("runtime event room and recipient domains differ")
    return {"room_id": room_id, "recipient_matrix_id": recipient}


def _validated_envelope(binding: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    if not isinstance(binding, dict) or binding.get("schema_version") != "1.0":
        raise HandoffEmissionError("runtime binding schema is invalid")
    for name in ("canonical_agent_id", "runtime_agent_id", "skill_id"):
        if not isinstance(binding.get(name), str) or not binding[name]:
            raise HandoffEmissionError(f"runtime binding lacks {name}")
    if not isinstance(envelope, dict):
        raise HandoffEmissionError("handoff envelope must contain an object")

    required = (
        "session_id",
        "task_instance_id",
        "incident_instance_id",
        "attempt_id",
        "run_id",
        "event_kind",
    )
    if any(not isinstance(envelope.get(name), str) or not envelope[name] for name in required):
        raise HandoffEmissionError("handoff envelope lacks required string fields")
    for name in ("input_artifact", "output_artifact"):
        if not isinstance(envelope.get(name), str):
            raise HandoffEmissionError("artifact path must be a string")

    session_id = envelope["session_id"]
    if SESSION_ID.fullmatch(session_id) is None:
        raise HandoffEmissionError("session binding is invalid")
    relationships = {
        "task_instance_id": f"LIVE-TASK-{session_id}",
        "incident_instance_id": f"LIVE-INCIDENT-{session_id}",
    }
    for name, expected in relationships.items():
        if envelope[name] != expected:
            raise HandoffEmissionError(f"{name} does not match session")
    if re.fullmatch(rf"LIVE-ATTEMPT-{re.escape(session_id)}-[0-9]{{2}}", envelope["attempt_id"]) is None:
        raise HandoffEmissionError("attempt_id does not match session")
    if RUN_ID.fullmatch(envelope["run_id"]) is None:
        raise HandoffEmissionError("run_id is invalid")

    route = _validated_route(binding, envelope["event_kind"])
    return {
        "session_id": session_id,
        "task_instance_id": envelope["task_instance_id"],
        "incident_instance_id": envelope["incident_instance_id"],
        "attempt_id": envelope["attempt_id"],
        "run_id": envelope["run_id"],
        "event_kind": envelope["event_kind"],
        "input_artifact": _artifact_path(envelope["input_artifact"]),
        "output_artifact": _artifact_path(envelope["output_artifact"]),
        **route,
    }


def build_handoff_message(binding: dict[str, Any], envelope: dict[str, Any]) -> str:
    """Build the one canonical plain-text event body accepted by Reviewer."""

    value = _validated_envelope(binding, envelope)
    return "\n".join(
        [
            value["recipient_matrix_id"],
            f"session_id: {value['session_id']}",
            f"task_instance_id: {value['task_instance_id']}",
            f"incident_instance_id: {value['incident_instance_id']}",
            f"attempt_id: {value['attempt_id']}",
            f"run_id: {value['run_id']}",
            f"LABOPS_EVENT_KIND: {value['event_kind']}",
            f"LABOPS_INPUT_ARTIFACT: {value['input_artifact']}",
            f"LABOPS_OUTPUT_ARTIFACT: {value['output_artifact']}",
        ]
    )


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
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _event_id(value: object) -> str | None:
    if isinstance(value, str) and MATRIX_EVENT_ID.fullmatch(value):
        return value
    if isinstance(value, dict):
        for child in value.values():
            found = _event_id(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _event_id(child)
            if found is not None:
                return found
    return None


def _run_openclaw(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=30,
    )


def _receipt_key(value: dict[str, str]) -> str:
    identity = {
        name: value[name]
        for name in ("session_id", "attempt_id", "event_kind", "output_artifact")
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _existing_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffEmissionError("handoff receipt is unreadable") from exc
    if not isinstance(value, dict):
        raise HandoffEmissionError("handoff receipt is invalid")
    return value


def emit_handoff(
    binding_path: str | Path,
    session_root: str | Path,
    envelope: dict[str, Any],
    *,
    dry_run: bool = False,
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Validate and send one idempotent Matrix event through OpenClaw."""

    binding = _read_object(Path(binding_path))
    value = _validated_envelope(binding, envelope)
    body = build_handoff_message(binding, envelope)
    message_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    base_result = {
        "event_kind": value["event_kind"],
        "session_id": value["session_id"],
        "attempt_id": value["attempt_id"],
        "output_artifact": value["output_artifact"],
        "message_sha256": message_sha256,
    }
    if dry_run:
        return {"status": "DRY_RUN", **base_result, "message": body}

    root = Path(session_root).resolve()
    if not root.is_dir():
        raise HandoffEmissionError("session root does not exist")
    for direction in ("input", "output"):
        relative = value[f"{direction}_artifact"]
        artifact = (root / Path(*PurePosixPath(relative).parts)).resolve()
        try:
            artifact.relative_to(root)
        except ValueError as exc:
            raise HandoffEmissionError(f"{direction} artifact escapes session root") from exc
        if not artifact.is_file():
            raise HandoffEmissionError(f"{direction} artifact does not exist")

    receipt_path = root / RECEIPT_DIRECTORY / f"{_receipt_key(value)}.json"
    existing = _existing_receipt(receipt_path)
    if existing is not None:
        if existing.get("message_sha256") != message_sha256:
            raise HandoffEmissionError("handoff receipt conflicts with current message")
        if existing.get("status") == "EMITTED" and isinstance(existing.get("event_id"), str):
            return {"status": "ALREADY_EMITTED", **base_result, "event_id": existing["event_id"]}
        if existing.get("status") == "PENDING":
            raise HandoffEmissionError("previous emission outcome is unknown; refusing blind retry")
        raise HandoffEmissionError("handoff receipt has an unsupported status")

    pending = {
        "schema_version": "1.0",
        "status": "PENDING",
        **base_result,
        "created_at": _utc_now(),
    }
    _atomic_json(receipt_path, pending)
    command = [
        "openclaw",
        "message",
        "send",
        "--account",
        "default",
        "--channel",
        "matrix",
        "--target",
        f"room:{value['room_id']}",
        "--message",
        body,
        "--json",
    ]
    runner = command_runner or _run_openclaw
    try:
        completed = runner(command)
    except subprocess.TimeoutExpired as exc:
        raise HandoffEmissionError("Matrix send outcome is unknown after timeout") from exc
    except OSError as exc:
        receipt_path.unlink(missing_ok=True)
        raise HandoffEmissionError("OpenClaw could not be started") from exc

    if completed.returncode != 0:
        receipt_path.unlink(missing_ok=True)
        raise HandoffEmissionError(
            f"OpenClaw Matrix send failed with exit code {completed.returncode}"
        )
    try:
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, UnicodeError) as exc:
        raise HandoffEmissionError("Matrix send outcome is unknown because JSON was invalid") from exc
    event_id = _event_id(response)
    if event_id is None:
        raise HandoffEmissionError("Matrix send outcome is unknown because event ID was absent")

    emitted = {
        **pending,
        "status": "EMITTED",
        "event_id": event_id,
        "emitted_at": _utc_now(),
    }
    _atomic_json(receipt_path, emitted)
    return {"status": "EMITTED", **base_result, "event_id": event_id}


def _default_binding_path() -> Path:
    return Path(__file__).resolve().parent.parent / "LABOPS_HANDOFF_RUNTIME.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emit_handoff.py")
    parser.add_argument("--binding", default=str(_default_binding_path()))
    parser.add_argument("--session-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-instance-id", required=True)
    parser.add_argument("--incident-instance-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--event-kind", required=True)
    parser.add_argument("--input-artifact", required=True)
    parser.add_argument("--output-artifact", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    envelope = {
        "session_id": args.session_id,
        "task_instance_id": args.task_instance_id,
        "incident_instance_id": args.incident_instance_id,
        "attempt_id": args.attempt_id,
        "run_id": args.run_id,
        "event_kind": args.event_kind,
        "input_artifact": args.input_artifact,
        "output_artifact": args.output_artifact,
    }
    try:
        result = emit_handoff(
            args.binding,
            args.session_root,
            envelope,
            dry_run=args.dry_run,
        )
    except HandoffEmissionError as exc:
        print(
            json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
