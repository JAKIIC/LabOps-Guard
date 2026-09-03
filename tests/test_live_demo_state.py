from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from labops.cli import main as cli_main
from labops.live_demo_state import (
    ARCHIVE_CONFIRMATION,
    DockerManagerStateRuntime,
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


class InterruptAfterReplaceRuntime(MemoryManagerRuntime):
    def __init__(self, state: dict) -> None:
        super().__init__(state)
        self.interrupted = False

    def replace_state(self, expected_sha256: str, payload: bytes) -> None:
        super().replace_state(expected_sha256, payload)
        if not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt("simulated process termination after Manager CAS")


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
                "schema_version": "1.0",
                "classification": "NON_FORMAL_LIVE_DEMO",
                "session_id": session_id,
                "task_instance_id": f"LIVE-TASK-{session_id}",
            }
        ),
        encoding="utf-8",
    )
    (session / "keep-me.txt").write_text("evidence remains", encoding="utf-8")
    return session


class LiveDemoStateTests(unittest.TestCase):
    def test_docker_runtime_uses_the_python3_available_in_agentteams(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with (
            patch("labops.live_demo_state.shutil.which", return_value="docker"),
            patch("labops.live_demo_state.subprocess.run", side_effect=fake_run),
        ):
            runtime = DockerManagerStateRuntime(Path.cwd())
            runtime.replace_state("a" * 64, b"{}\n")

        self.assertIn("python3", commands[0])
        self.assertNotIn("python", commands[0])

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
            create_session(sessions, "20260902-002")
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
            create_session(sessions, "20260902-002")
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

    def test_archive_rejects_formal_or_symlinked_session_roots_before_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            formal = root / "demo" / "output-agentteams-at004"
            formal.mkdir(parents=True)
            runtime = MemoryManagerRuntime(manager_state())
            with self.assertRaisesRegex(LiveDemoStateError, "formal Evidence"):
                archive_live_rehearsals(
                    root,
                    formal,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=runtime,
                )
            self.assertEqual(runtime.replacements, [])

            sessions = root / "sessions"
            sessions.mkdir()
            linked = sessions / "20260902-001"
            try:
                linked.symlink_to(formal, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(LiveDemoStateError, "session root"):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=runtime,
                )
            self.assertEqual(runtime.replacements, [])

    def test_archive_rejects_symlinked_runtime_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            create_session(sessions, "20260902-001")
            create_session(sessions, "20260902-002")
            formal = root / "demo" / "output-agentteams-at004"
            formal.mkdir(parents=True)
            backup = sessions / "_runtime-backups"
            try:
                backup.symlink_to(formal, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            runtime = MemoryManagerRuntime(manager_state())

            with self.assertRaisesRegex(LiveDemoStateError, "backup"):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=runtime,
                )

            self.assertEqual(runtime.replacements, [])
            self.assertEqual(list(formal.iterdir()), [])

    def test_archive_recovers_after_process_dies_following_manager_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            first = create_session(sessions, "20260902-001")
            second = create_session(sessions, "20260902-002")
            runtime = InterruptAfterReplaceRuntime(manager_state())

            with self.assertRaises(KeyboardInterrupt):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=runtime,
                )
            self.assertFalse((first / "session_outcome.json").exists())
            self.assertFalse((second / "session_outcome.json").exists())

            result = archive_live_rehearsals(
                root,
                sessions,
                confirm=ARCHIVE_CONFIRMATION,
                runtime=runtime,
            )

            self.assertEqual(result["status"], "ARCHIVED")
            self.assertEqual(result["session_outcomes_written"], 2)
            self.assertTrue((first / "session_outcome.json").is_file())
            self.assertTrue((second / "session_outcome.json").is_file())

    def test_archive_refuses_to_overwrite_a_truthful_terminal_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            session = create_session(sessions, "20260902-001")
            (session / "session_outcome.json").write_text(
                json.dumps(
                    {
                        "status": "DEMO_PASSED_NOT_RESOLVED",
                        "session_id": "20260902-001",
                    }
                ),
                encoding="utf-8",
            )
            runtime = MemoryManagerRuntime(manager_state())

            with self.assertRaisesRegex(LiveDemoStateError, "existing session outcome"):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=runtime,
                )

            self.assertEqual(runtime.replacements, [])
            self.assertEqual(
                json.loads((session / "session_outcome.json").read_text(encoding="utf-8"))["status"],
                "DEMO_PASSED_NOT_RESOLVED",
            )

    def test_all_session_targets_are_validated_before_any_state_or_outcome_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            first = create_session(sessions, "20260902-001")
            (sessions / "20260902-002").mkdir()
            runtime = MemoryManagerRuntime(manager_state())

            with self.assertRaisesRegex(LiveDemoStateError, "session manifest"):
                archive_live_rehearsals(
                    root,
                    sessions,
                    confirm=ARCHIVE_CONFIRMATION,
                    runtime=runtime,
                )

            self.assertEqual(runtime.replacements, [])
            self.assertFalse((first / "session_outcome.json").exists())

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
