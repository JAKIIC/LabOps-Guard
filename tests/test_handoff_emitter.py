"""Behavioral tests for the standalone AgentTeams Matrix handoff emitter."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from labops.handoff_emitter import (
    HandoffEmissionError,
    build_handoff_message,
    emit_handoff,
)


BINDING = {
    "schema_version": "1.0",
    "canonical_agent_id": "evidence-collector",
    "runtime_agent_id": "evidence-collector",
    "skill_id": "collect-lab-evidence",
    "emitter_sha256": "1" * 64,
    "events": {
        "collector_to_rca": {
            "room_id": "!collector:matrix.local",
            "recipient_matrix_id": "@manager:matrix.local",
        },
        "evidence_incomplete": {
            "room_id": "!collector:matrix.local",
            "recipient_matrix_id": "@manager:matrix.local",
        },
    },
}

ENVELOPE = {
    "session_id": "20260903-003",
    "task_instance_id": "LIVE-TASK-20260903-003",
    "incident_instance_id": "LIVE-INCIDENT-20260903-003",
    "attempt_id": "LIVE-ATTEMPT-20260903-003-01",
    "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-003",
    "event_kind": "collector_to_rca",
    "input_artifact": "incident_packet.json",
    "output_artifact": "collector-report.json",
}


def _write_binding(root: Path) -> Path:
    path = root / "LABOPS_HANDOFF_RUNTIME.json"
    path.write_text(json.dumps(BINDING), encoding="utf-8")
    return path


class HandoffMessageTests(unittest.TestCase):
    def test_message_has_one_kind_five_bindings_and_two_artifacts_in_fixed_order(self) -> None:
        body = build_handoff_message(BINDING, ENVELOPE)

        self.assertEqual(
            body,
            "\n".join(
                [
                    "@manager:matrix.local",
                    "session_id: 20260903-003",
                    "task_instance_id: LIVE-TASK-20260903-003",
                    "incident_instance_id: LIVE-INCIDENT-20260903-003",
                    "attempt_id: LIVE-ATTEMPT-20260903-003-01",
                    "run_id: RUN-LABOPS-AT-004-AGENTTEAMS-003",
                    "LABOPS_EVENT_KIND: collector_to_rca",
                    "LABOPS_INPUT_ARTIFACT: incident_packet.json",
                    "LABOPS_OUTPUT_ARTIFACT: collector-report.json",
                ]
            ),
        )
        self.assertEqual(body.count("LABOPS_EVENT_KIND:"), 1)

    def test_rejects_event_not_allowed_for_runtime_role(self) -> None:
        with self.assertRaisesRegex(HandoffEmissionError, "not allowed"):
            build_handoff_message(
                BINDING,
                {**ENVELOPE, "event_kind": "approval_pending"},
            )

    def test_rejects_binding_that_does_not_match_session(self) -> None:
        invalid_values = {
            "task_instance_id": "LIVE-TASK-20260903-004",
            "incident_instance_id": "LIVE-INCIDENT-20260903-004",
            "attempt_id": "LIVE-ATTEMPT-20260903-004-01",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                with self.assertRaisesRegex(HandoffEmissionError, "does not match session"):
                    build_handoff_message(BINDING, {**ENVELOPE, field: value})

    def test_rejects_absolute_traversal_and_empty_artifact_paths(self) -> None:
        invalid_paths = (
            "C:/private/file.json",
            "/root/private/file.json",
            "../private/file.json",
            "evidence/../../private/file.json",
            "",
        )
        for value in invalid_paths:
            with self.subTest(value=value):
                with self.assertRaisesRegex(HandoffEmissionError, "artifact path"):
                    build_handoff_message(
                        BINDING,
                        {**ENVELOPE, "output_artifact": value},
                    )


class HandoffEmissionTests(unittest.TestCase):
    def test_dry_run_validates_and_returns_body_without_sending_or_writing(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            raise AssertionError("dry-run must not execute OpenClaw")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binding_path = _write_binding(root)
            result = emit_handoff(
                binding_path,
                root / "missing-session-root",
                ENVELOPE,
                dry_run=True,
                command_runner=runner,
            )

            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(result["event_kind"], "collector_to_rca")
            self.assertNotIn("room_id", result)
            self.assertFalse((root / "missing-session-root").exists())
        self.assertEqual(calls, [])

    def test_success_uses_openclaw_once_and_persists_redacted_receipt(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"result": {"eventId": "$event-003"}}),
                stderr="configuration warning without secrets",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binding_path = _write_binding(root)
            (root / ENVELOPE["input_artifact"]).write_text("{}", encoding="utf-8")
            (root / ENVELOPE["output_artifact"]).write_text("{}", encoding="utf-8")

            first = emit_handoff(
                binding_path,
                root,
                ENVELOPE,
                command_runner=runner,
            )
            second = emit_handoff(
                binding_path,
                root,
                ENVELOPE,
                command_runner=runner,
            )

            receipts = list((root / ".labops-handoff-receipts").glob("*.json"))
            receipt_text = receipts[0].read_text(encoding="utf-8")

        self.assertEqual(first["status"], "EMITTED")
        self.assertEqual(first["event_id"], "$event-003")
        self.assertEqual(second["status"], "ALREADY_EMITTED")
        self.assertEqual(second["event_id"], "$event-003")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][:8],
            [
                "openclaw",
                "message",
                "send",
                "--account",
                "default",
                "--channel",
                "matrix",
                "--target",
            ],
        )
        self.assertEqual(calls[0][8], "room:!collector:matrix.local")
        self.assertEqual(calls[0][-1], "--json")
        self.assertEqual(len(receipts), 1)
        self.assertIn("$event-003", receipt_text)
        self.assertNotIn("token", receipt_text.lower())
        self.assertNotIn("!collector:matrix.local", receipt_text)

    def test_missing_artifact_blocks_before_openclaw(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout='{"event_id":"$bad"}', stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binding_path = _write_binding(root)
            (root / ENVELOPE["input_artifact"]).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(HandoffEmissionError, "output artifact does not exist"):
                emit_handoff(binding_path, root, ENVELOPE, command_runner=runner)

        self.assertEqual(calls, [])

    def test_definite_failure_removes_pending_marker_so_a_later_call_can_retry(self) -> None:
        outcomes = [
            subprocess.CompletedProcess(["openclaw"], 2, stdout="", stderr="send rejected"),
            subprocess.CompletedProcess(["openclaw"], 0, stdout='{"event_id":"$retry-ok"}', stderr=""),
        ]

        def runner(_command: list[str]) -> subprocess.CompletedProcess[str]:
            return outcomes.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binding_path = _write_binding(root)
            (root / ENVELOPE["input_artifact"]).write_text("{}", encoding="utf-8")
            (root / ENVELOPE["output_artifact"]).write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(HandoffEmissionError, "send failed"):
                emit_handoff(binding_path, root, ENVELOPE, command_runner=runner)
            result = emit_handoff(binding_path, root, ENVELOPE, command_runner=runner)

        self.assertEqual(result["status"], "EMITTED")
        self.assertEqual(result["event_id"], "$retry-ok")

    def test_timeout_keeps_pending_marker_and_blocks_blind_retry(self) -> None:
        calls = 0

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            raise subprocess.TimeoutExpired(command, 30)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binding_path = _write_binding(root)
            (root / ENVELOPE["input_artifact"]).write_text("{}", encoding="utf-8")
            (root / ENVELOPE["output_artifact"]).write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(HandoffEmissionError, "outcome is unknown"):
                emit_handoff(binding_path, root, ENVELOPE, command_runner=runner)
            with self.assertRaisesRegex(HandoffEmissionError, "previous emission outcome is unknown"):
                emit_handoff(binding_path, root, ENVELOPE, command_runner=runner)

            receipt = json.loads(
                next((root / ".labops-handoff-receipts").glob("*.json")).read_text(encoding="utf-8")
            )

        self.assertEqual(calls, 1)
        self.assertEqual(receipt["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
