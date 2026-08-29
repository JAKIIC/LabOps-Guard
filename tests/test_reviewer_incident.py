"""Behavioral gates for the answer-blind dynamic Reviewer incident."""

from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from labops import cli
from labops.matrix_observer import write_observer_projection
from labops.recovery import (
    accept_human_takeover,
    request_recovery,
    resume_human_takeover,
)
from labops.reviewer_incident import (
    ReviewerIncidentError,
    prepare_reviewer_incident,
    release_reviewer_evidence,
    review_reviewer_incident,
)


ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "20260831-091"


def _event(event_id: str, kind: str, actor: str, timestamp: str) -> dict:
    return {
        "classification": "NON_AUTHORITATIVE_UI_PROJECTION",
        "validation_version": "matrix-sender-bound-v1",
        "event_id": event_id,
        "room_id": f"!{actor}:example.invalid",
        "actor": actor,
        "kind": kind,
        "timestamp": timestamp,
        "workflow_from": "EVIDENCE_COLLECTING" if kind == "evidence_incomplete" else "RECEIVED",
        "workflow_to": "BLOCKED" if kind == "evidence_incomplete" else "EVIDENCE_COLLECTING",
        "evidence_state": "OBSERVED",
        "artifact_refs": ["shared/reviewer/evidence-gap.json"],
        "hash_refs": ["a" * 64],
    }


class ReviewerIncidentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.sessions = Path(self.temporary.name)
        self.prepared = prepare_reviewer_incident(ROOT, self.sessions, SESSION_ID)
        self.session_root = Path(self.prepared["session_root"])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_status_rejects_a_projection_without_sender_bound_validation(self) -> None:
        observer = self.session_root / "observer"
        observer.mkdir(exist_ok=True)
        legacy = _event("$legacy", "evidence_incomplete", "evidence-collector", "2026-08-31T10:00:00Z")
        legacy.pop("validation_version")
        (observer / "normalized_events.jsonl").write_text(
            json.dumps(legacy) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ReviewerIncidentError, "invalid"):
            review_reviewer_incident(self.session_root)

    def test_prepare_is_non_overwritable_and_does_not_leak_the_answer(self) -> None:
        self.assertEqual(self.prepared["status"], "PREPARED")
        self.assertEqual(self.prepared["profile"], "REVIEWER_EVIDENCE_GAP_V1")
        manager_task = (self.session_root / "manager_task.md").read_text(encoding="utf-8")
        for leaked_answer in (
            "train_augmented",
            "eval_standard",
            "preprocessing_profile",
            "0.978125",
        ):
            self.assertNotIn(leaked_answer, manager_task)

        initial = json.loads(
            (self.session_root / "operator" / "initial_incident_packet.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(initial["observed_accuracy"], [0.71875, 0.71875, 0.71875])
        self.assertEqual(
            initial["missing_required_evidence"],
            ["evaluation-config-snapshot-current"],
        )
        self.assertNotIn("train_augmented", json.dumps(initial))
        self.assertTrue(
            (self.session_root / "operator" / "withheld" / "evaluation-config-snapshot-current.json").is_file()
        )
        self.assertFalse((self.session_root / "operator" / "released").exists())

        with self.assertRaises(FileExistsError):
            prepare_reviewer_incident(ROOT, self.sessions, SESSION_ID)

    def test_release_requires_a_matching_accepted_human_takeover(self) -> None:
        with self.assertRaises(ReviewerIncidentError):
            release_reviewer_evidence(
                self.session_root,
                takeover_id=f"TAKEOVER-{SESSION_ID}-01",
                released_by="human-operator",
            )

        write_observer_projection(
            self.session_root,
            {
                "connected": True,
                "source_status": "LIVE",
                "checked_at": "2026-08-31T10:00:00Z",
                "last_success_at": "2026-08-31T10:00:00Z",
                "next_batch": "s1",
                "events": [
                    _event(
                        "$evidence-gap",
                        "evidence_incomplete",
                        "evidence-collector",
                        "2026-08-31T10:00:00Z",
                    )
                ],
                "errors": [],
            },
        )
        requested = request_recovery(
            self.session_root,
            failure_type="CAPABILITY_MISSING",
            failed_role="evidence-collector",
            failed_worker_id="evidence-collector-primary",
            requested_by="labops-manager",
            source_refs=["observer/normalized_events.jsonl"],
        )
        self.assertEqual(requested["decision"], "HUMAN_TAKEOVER")
        accept_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            accepted_by="human-operator",
        )

        with self.assertRaises(ReviewerIncidentError):
            release_reviewer_evidence(
                self.session_root,
                takeover_id=requested["takeover_id"],
                released_by="different-human",
            )

        released = release_reviewer_evidence(
            self.session_root,
            takeover_id=requested["takeover_id"],
            released_by="human-operator",
        )
        self.assertEqual(released["status"], "EVIDENCE_RELEASED")
        released_path = self.session_root / released["release_ref"]
        self.assertTrue(released_path.is_file())
        self.assertEqual(len(released["sha256"]), 64)
        with self.assertRaises(ReviewerIncidentError):
            release_reviewer_evidence(
                self.session_root,
                takeover_id=requested["takeover_id"],
                released_by="human-operator",
            )

    def test_status_requires_real_gap_takeover_release_resume_and_redispatch(self) -> None:
        initial = review_reviewer_incident(self.session_root)
        self.assertEqual(initial["status"], "WAITING_FOR_AGENTTEAMS_GAP")
        self.assertEqual(initial["skill_runtime_invocation"], "UNVERIFIED")

        first = _event(
            "$evidence-gap",
            "evidence_incomplete",
            "evidence-collector",
            "2026-08-31T10:00:00Z",
        )
        write_observer_projection(
            self.session_root,
            {
                "connected": True,
                "source_status": "LIVE",
                "checked_at": "2026-08-31T10:00:01Z",
                "last_success_at": "2026-08-31T10:00:01Z",
                "next_batch": "s1",
                "events": [first],
                "errors": [],
            },
        )
        self.assertEqual(
            review_reviewer_incident(self.session_root)["status"],
            "WAITING_FOR_RECOVERY_REQUEST",
        )

        requested = request_recovery(
            self.session_root,
            failure_type="CAPABILITY_MISSING",
            failed_role="evidence-collector",
            failed_worker_id="evidence-collector-primary",
            requested_by="labops-manager",
            source_refs=["observer/normalized_events.jsonl"],
        )
        pending = review_reviewer_incident(self.session_root)
        self.assertEqual(pending["status"], "WAITING_FOR_HUMAN_TAKEOVER")
        self.assertEqual(pending["recovery"]["reassign"], "UNAVAILABLE")

        accept_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            accepted_by="human-operator",
        )
        self.assertEqual(
            review_reviewer_incident(self.session_root)["status"],
            "WAITING_FOR_EVIDENCE_RELEASE",
        )
        release_reviewer_evidence(
            self.session_root,
            takeover_id=requested["takeover_id"],
            released_by="human-operator",
        )
        self.assertEqual(
            review_reviewer_incident(self.session_root)["status"],
            "WAITING_FOR_HUMAN_RESUME",
        )
        resume_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            resumed_by="human-operator",
            resume_point="EVIDENCE_COLLECTING",
        )
        waiting = review_reviewer_incident(self.session_root)
        self.assertEqual(waiting["status"], "WAITING_FOR_AGENTTEAMS_RESUME")
        self.assertEqual(waiting["recovery"]["human_takeover"], "VERIFIED")

        second = _event(
            "$manager-redispatch",
            "manager_to_collector",
            "labops-manager",
            "2026-08-31T10:05:00Z",
        )
        write_observer_projection(
            self.session_root,
            {
                "connected": True,
                "source_status": "LIVE",
                "checked_at": "2026-08-31T10:05:01Z",
                "last_success_at": "2026-08-31T10:05:01Z",
                "next_batch": "s2",
                "events": [second],
                "errors": [],
            },
        )
        ready = review_reviewer_incident(self.session_root)
        self.assertEqual(ready["status"], "READY_FOR_AGENTTEAMS_CONTINUATION")
        self.assertEqual(ready["matrix_dynamic_branch"], "OBSERVED")
        self.assertEqual(ready["skill_runtime_invocation"], "UNVERIFIED")
        self.assertFalse(ready["helper_boundaries"]["sends_matrix_messages"])

    def test_cli_prepare_and_status_are_truthful_and_read_only(self) -> None:
        other_session = "20260831-092"
        output = io.StringIO()
        with redirect_stdout(output):
            rc = cli.main(
                [
                    "reviewer-incident",
                    "prepare",
                    "--session",
                    other_session,
                    "--sessions-root",
                    str(self.sessions),
                ]
            )
        self.assertEqual(rc, 0)
        prepared = json.loads(output.getvalue())
        self.assertEqual(prepared["status"], "PREPARED")
        self.assertFalse(prepared["helper_boundaries"]["sends_matrix_messages"])

        output = io.StringIO()
        with redirect_stdout(output):
            rc = cli.main(
                [
                    "reviewer-incident",
                    "status",
                    "--session",
                    other_session,
                    "--sessions-root",
                    str(self.sessions),
                ]
            )
        self.assertEqual(rc, 2)
        status = json.loads(output.getvalue())
        self.assertEqual(status["status"], "WAITING_FOR_AGENTTEAMS_GAP")
        self.assertEqual(status["skill_runtime_invocation"], "UNVERIFIED")

    def test_cli_release_fails_closed_without_matching_takeover(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            rc = cli.main(
                [
                    "reviewer-incident",
                    "release",
                    "--session",
                    SESSION_ID,
                    "--sessions-root",
                    str(self.sessions),
                    "--takeover-id",
                    f"TAKEOVER-{SESSION_ID}-01",
                    "--released-by",
                    "human-operator",
                    "--confirm",
                    f"TAKEOVER-{SESSION_ID}-01",
                ]
            )
        self.assertEqual(rc, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse((self.session_root / "operator" / "released").exists())

    def test_contract_tampering_cannot_expand_helper_authority(self) -> None:
        contract_path = self.session_root / "reviewer_incident.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["helper_boundaries"]["sends_matrix_messages"] = True
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        with self.assertRaisesRegex(ReviewerIncidentError, "helper boundaries"):
            review_reviewer_incident(self.session_root)

    def test_contract_session_binding_cannot_be_repointed(self) -> None:
        contract_path = self.session_root / "reviewer_incident.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["session_id"] = "20260831-999"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        with self.assertRaisesRegex(ReviewerIncidentError, "session binding"):
            review_reviewer_incident(self.session_root)

    def test_profile_rejects_a_recovery_decision_unrelated_to_the_evidence_gap(self) -> None:
        write_observer_projection(
            self.session_root,
            {
                "connected": True,
                "source_status": "LIVE",
                "checked_at": "2026-08-31T10:00:00Z",
                "last_success_at": "2026-08-31T10:00:00Z",
                "next_batch": "s1",
                "events": [
                    _event(
                        "$evidence-gap",
                        "evidence_incomplete",
                        "evidence-collector",
                        "2026-08-31T10:00:00Z",
                    )
                ],
                "errors": [],
            },
        )
        request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["observer/normalized_events.jsonl"],
        )

        result = review_reviewer_incident(self.session_root)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["recovery"]["profile_binding"], "INVALID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
