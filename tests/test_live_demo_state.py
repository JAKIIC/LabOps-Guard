from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from labops.cli import main as cli_main
from labops.live_demo_state import (
    ARCHIVE_CONFIRMATION,
    LiveDemoStateError,
    archive_live_rehearsals,
    inspect_recording_state,
)


class MemoryManagerRuntime:
    def __init__(self, state: dict, *, change_before_replace: bool = False) -> None:
        self.payload = (json.dumps(state, sort_keys=True) + "\n").encode("utf-8")
        self.change_before_replace = change_before_replace
        self.replacements: list[tuple[str, bytes]] = []

    def read_state(self) -> bytes:
        return self.payload

    def replace_state(self, expected_sha256: str, payload: bytes) -> None:
        if self.change_before_replace:
            self.payload += b" "
        current = hashlib.sha256(self.payload).hexdigest()
        if current != expected_sha256:
            raise LiveDemoStateError("Manager state changed concurrently")
        self.replacements.append((expected_sha256, payload))
        self.payload = payload


def manager_state() -> dict:
    return {
        "schema_version": "1.0",
        "active_tasks": {
            "LABOPS-AT-004-EVAL-DRIFT": {"status": "ACTIVE", "formal": True},
            "LIVE-TASK-20260902-001": {"status": "WAITING"},
            "LIVE-TASK-20260902-002": {"status": "WAITING"},
        },
        "history": {"must_remain": True},
    }


def create_session(sessions_root: Path, session_id: str) -> Path:
    session = sessions_root / session_id
    session.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "task_instance_id": f"LIVE-TASK-{session_id}",
            }
        ),
        encoding="utf-8",
    )
    (session / "keep-me.txt").write_text("evidence remains", encoding="utf-8")
    return session


class LiveDemoStateTests(unittest.TestCase):
    def test_inspection_reports_only_live_task_ids_and_counts(self) -> None:
        report = inspect_recording_state(manager_state())

        self.assertEqual(report["status"], "STALE_LIVE_TASKS")
        self.assertEqual(report["active_task_count"], 3)
        self.assertEqual(report["formal_task_count"], 1)
        self.assertEqual(report["live_task_count"], 2)
        self.assertEqual(
            report["live_task_ids"],
            ["LIVE-TASK-20260902-001", "LIVE-TASK-20260902-002"],
        )
        self.assertNotIn("WAITING", json.dumps(report))

    def test_preview_makes_no_runtime_or_filesystem_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            create_session(sessions, "20260902-001")
            runtime = MemoryManagerRuntime(manager_state())

            report = archive_live_rehearsals(root, sessions, runtime=runtime)

            self.assertEqual(report["status"], "PREVIEW")
            self.assertEqual(report["live_task_count"], 2)
            self.assertEqual(runtime.replacements, [])
            self.assertFalse((sessions / "_runtime-backups").exists())
            self.assertFalse(
                (sessions / "20260902-001" / "session_outcome.json").exists()
            )

    def test_confirmed_archive_preserves_formal_state_and_session_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            first = create_session(sessions, "20260902-001")
            second = create_session(sessions, "20260902-002")
            runtime = MemoryManagerRuntime(manager_state())
            original = runtime.payload
            original_sha = hashlib.sha256(original).hexdigest()

            report = archive_live_rehearsals(
                root,
                sessions,
                confirm=ARCHIVE_CONFIRMATION,
                runtime=runtime,
            )

            self.assertEqual(report["status"], "ARCHIVED")
            self.assertEqual(report["archived_live_tasks"], 2)
            self.assertEqual(report["formal_task_count"], 1)
            self.assertEqual(report["session_outcomes_written"], 2)
            updated = json.loads(runtime.payload.decode("utf-8"))
            self.assertEqual(
                list(updated["active_tasks"]), ["LABOPS-AT-004-EVAL-DRIFT"]
            )
            self.assertEqual(updated["history"], {"must_remain": True})
            backup = (
                sessions
                / "_runtime-backups"
                / f"manager-state-{original_sha}.json"
            )
            self.assertEqual(backup.read_bytes(), original)
            for session in (first, second):
                self.assertEqual(
                    json.loads(
                        (session / "session_outcome.json").read_text(
                            encoding="utf-8"
                        )
                    )["status"],
                    "ABORTED_REHEARSAL",
                )
                self.assertEqual(
                    (session / "keep-me.txt").read_text(encoding="utf-8"),
                    "evidence remains",
                )

    def test_wrong_confirmation_and_concurrent_change_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            create_session(sessions, "20260902-001")
            runtime = MemoryManagerRuntime(manager_state())
            with self.assertRaises(LiveDemoStateError):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm="yes",
                    runtime=runtime,
                )
            self.assertEqual(runtime.replacements, [])

            concurrent = MemoryManagerRuntime(
                manager_state(), change_before_replace=True
            )
            with self.assertRaisesRegex(LiveDemoStateError, "concurrently"):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=concurrent,
                )
            self.assertEqual(concurrent.replacements, [])
            self.assertFalse(
                (sessions / "20260902-001" / "session_outcome.json").exists()
            )

    def test_cli_archive_defaults_to_a_read_only_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with (
                patch(
                    "labops.live_demo_state.archive_live_rehearsals",
                    return_value={"status": "PREVIEW", "live_task_count": 2},
                ) as archive,
                redirect_stdout(output),
            ):
                result = cli_main(
                    ["live-demo", "archive-rehearsals", "--sessions-root", tmp]
                )

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "PREVIEW")
        self.assertIsNone(archive.call_args.kwargs["confirm"])


if __name__ == "__main__":
    unittest.main()
