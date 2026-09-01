from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from labops.contracts import ContractError, validate_document
from labops.live_demo import prepare_session
from labops.recovery import request_recovery
from labops.reviewer_state import (
    build_reviewer_state,
    classify_source_status,
    configured_recovery_policy,
)


ROOT = Path(__file__).resolve().parent.parent


class ReviewerStateTests(unittest.TestCase):
    NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    def _session(self, root: Path, session_id: str = "20260831-071") -> Path:
        prepare_session(ROOT, root, session_id)
        return root / session_id

    def _matrix_snapshot(self, *, include_rca_to_planner: bool = True) -> dict:
        events = [
            self._event(
                "task_dispatched", "$event-task", "labops-manager",
                "RECEIVED", "EVIDENCE_COLLECTING", "2026-08-28T11:59:01Z",
            ),
            self._event(
                "manager_to_collector", "$event-mgr-collector", "labops-manager",
                "RECEIVED", "EVIDENCE_COLLECTING", "2026-08-28T11:59:02Z",
            ),
            self._event(
                "evidence_collected", "$event-evidence", "evidence-collector",
                "EVIDENCE_COLLECTING", "EVIDENCE_READY", "2026-08-28T11:59:03Z",
            ),
            self._event(
                "collector_to_rca", "$event-collector-rca", "evidence-collector",
                "EVIDENCE_READY", "RCA_ANALYZING", "2026-08-28T11:59:04Z",
            ),
            self._event(
                "hypotheses_ranked", "$event-hypotheses", "rca-analyst",
                "RCA_ANALYZING", "RCA_READY", "2026-08-28T11:59:05Z",
            ),
        ]
        if include_rca_to_planner:
            events.append(self._event(
                "rca_to_planner", "$event-rca-planner", "rca-analyst",
                "RCA_READY", "PLAN_DRAFTING", "2026-08-28T11:59:06Z",
            ))
        events.extend([
            self._event(
                "policy_passed", "$event-policy", "experiment-planner",
                "PLAN_READY", "POLICY_CHECKING", "2026-08-28T11:59:07Z",
            ),
            self._event(
                "approval_pending", "$event-approval", "experiment-planner",
                "POLICY_CHECKING", "APPROVAL_PENDING", "2026-08-28T11:59:08Z",
            ),
        ])
        return {
            "connected": True,
            "last_success_at": "2026-08-28T11:59:55Z",
            "events": events,
        }

    @staticmethod
    def _event(
        kind: str,
        event_id: str,
        actor: str,
        workflow_from: str,
        workflow_to: str,
        timestamp: str,
    ) -> dict:
        return {
            "kind": kind,
            "event_id": event_id,
            "actor": actor,
            "timestamp": timestamp,
            "workflow_from": workflow_from,
            "workflow_to": workflow_to,
            "evidence_state": "OBSERVED",
            "artifact_refs": [f"shared/{kind}.json"],
            "hash_refs": ["a" * 64],
        }

    def test_source_status_is_data_driven(self) -> None:
        self.assertEqual(classify_source_status("quick", False, None, self.NOW), "REPLAY")
        self.assertEqual(
            classify_source_status("live", True, "2026-08-28T11:59:55Z", self.NOW),
            "LIVE",
        )
        self.assertEqual(
            classify_source_status("live", True, "2026-08-28T11:59:30Z", self.NOW),
            "STALE",
        )
        self.assertEqual(classify_source_status("live", False, None, self.NOW), "DISCONNECTED")
        self.assertEqual(
            classify_source_status("live", True, "2026-08-28T11:58:30Z", self.NOW),
            "DISCONNECTED",
        )
        with self.assertRaises(ValueError):
            classify_source_status("archive-but-live", True, None, self.NOW)

    def test_recent_success_stays_live_during_one_failed_poll(self) -> None:
        self.assertEqual(
            classify_source_status(
                "live",
                False,
                "2026-09-02T00:00:00Z",
                datetime(2026, 9, 2, 0, 0, 10, tzinfo=timezone.utc),
            ),
            "LIVE",
        )

    def test_failed_poll_becomes_stale_then_disconnected_by_age(self) -> None:
        cases = ((16, "STALE"), (60, "STALE"), (61, "DISCONNECTED"))
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(
                    classify_source_status(
                        "live",
                        False,
                        "2026-09-02T00:00:00Z",
                        datetime(2026, 9, 2, tzinfo=timezone.utc)
                        + timedelta(seconds=seconds),
                    ),
                    expected,
                )

    def test_agent_nodes_separate_workflow_and_evidence_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
            )
        planner = next(item for item in state["agents"] if item["agent_id"] == "experiment-planner")
        self.assertEqual(planner["workflow_state"], "PLAN_READY")
        self.assertEqual(planner["evidence_state"], "OBSERVED")
        executor = next(item for item in state["agents"] if item["agent_id"] == "safe-executor")
        self.assertEqual(executor["workflow_state"], "NOT_STARTED")
        self.assertEqual(executor["evidence_state"], "CONFIGURED")

    def test_quick_mode_is_replay_with_verified_archived_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = build_reviewer_state(ROOT, Path(tmp), None, "quick", now=self.NOW)
        self.assertEqual(state["source_summary"], "REPLAY")
        self.assertEqual(state["sources"]["archived_evidence"]["status"], "VERIFIED")
        self.assertEqual(state["audit"]["status"], "VERIFIED")
        self.assertEqual(state["incident"]["workflow_state"], "RESOLVED")
        self.assertTrue(all(item["evidence_state"] == "VERIFIED" for item in state["agents"]))
        by_kind = {event["kind"]: event for event in state["timeline"]}
        self.assertEqual(by_kind["task_dispatched"]["evidence_state"], "VERIFIED")
        self.assertEqual(by_kind["approval_pending"]["evidence_state"], "CONFIGURED")
        self.assertIsNone(by_kind["approval_pending"]["event_id"])

    def test_approval_pending_has_human_owner_and_complete_observed_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
            )
        self.assertEqual(state["incident"]["current_owner"], "Human Approver")
        self.assertEqual(state["incident"]["last_active_agent"], "Experiment Planner")
        self.assertEqual(state["incident"]["workflow_state"], "APPROVAL_PENDING")
        by_kind = {event["kind"]: event for event in state["timeline"]}
        self.assertEqual(by_kind["rca_to_planner"]["evidence_state"], "OBSERVED")
        self.assertEqual(by_kind["policy_passed"]["evidence_state"], "OBSERVED")
        self.assertEqual(by_kind["approval_pending"]["evidence_state"], "OBSERVED")

    def test_missing_timeline_event_remains_configured_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            snapshot = self._matrix_snapshot(include_rca_to_planner=False)
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", snapshot, self.NOW,
            )
        event = next(item for item in state["timeline"] if item["kind"] == "rca_to_planner")
        self.assertEqual(event["source"], "CONFIGURED")
        self.assertEqual(event["evidence_state"], "CONFIGURED")
        self.assertIsNone(event["event_id"])
        self.assertEqual(event["artifact_refs"], [])

    def test_timeline_details_are_bounded_and_have_transition_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            snapshot = self._matrix_snapshot()
            snapshot["events"][0]["artifact_refs"] = [f"artifact-{i}" for i in range(20)]
            snapshot["events"][0]["hash_refs"] = [str(i) * 64 for i in range(20)]
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", snapshot, self.NOW,
            )
        event = state["timeline"][0]
        for key in (
            "workflow_from", "workflow_to", "evidence_state", "source", "event_id",
            "artifact_refs", "hash_refs",
        ):
            self.assertIn(key, event)
        self.assertLessEqual(len(event["artifact_refs"]), 8)
        self.assertLessEqual(len(event["hash_refs"]), 8)

    def test_recovery_current_directive_is_separate_from_configured_policy(self) -> None:
        policy = configured_recovery_policy()
        self.assertEqual(policy["WORKER_TIMEOUT"]["first_failure"], "RETRY")
        self.assertEqual(policy["POLICY_VIOLATION"]["decision"], "ROLLBACK_REQUIRED")
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
            )
        self.assertEqual(state["recovery"]["current_directive"], "NONE")
        self.assertIn("WORKER_TIMEOUT", state["recovery"]["configured_policy"])
        self.assertNotEqual(state["recovery"]["current_directive"], "RETRY")

    def test_policy_violation_projects_real_rollback_without_new_stop_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            source = session_root / "evidence" / "policy_failure.json"
            source.write_text('{"decision":"POLICY_VIOLATION"}', encoding="utf-8")
            request_recovery(
                session_root,
                failure_type="POLICY_VIOLATION",
                requested_by="safe-executor",
                source_refs=["evidence/policy_failure.json"],
            )
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
            )
        self.assertEqual(state["recovery"]["current_directive"], "ROLLBACK_REQUIRED")
        self.assertEqual(state["recovery"]["display"], "STOP / NO RETRY")
        self.assertNotIn(state["recovery"]["current_directive"], {"STOP", "NO_RETRY"})
        self.assertEqual(state["recovery"]["trace_status"], "VERIFIED")

    def test_tool_contract_summary_and_full_details_require_live_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            evidence = session_root / "evidence"
            plan_hash = "b" * 64
            request = {
                "experiment_plan": {
                    "task_id": "LABOPS-AT-004-EVAL-DRIFT",
                    "incident_id": "DEMO-EVAL-DRIFT-004",
                    "plan_id": "PLAN-LIVE-071",
                    "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-071",
                },
                "approval": {
                    "approval_id": "APR-LIVE-071",
                    "canonical_plan_sha256": plan_hash,
                },
                "approval_binding": {"status": "VALID"},
                "tool_contract": {
                    "tool_id": "labops.runner.execute",
                    "caller_agent_id": "safe-executor",
                    "skill_id": "control-lab-action",
                    "task_id": "LABOPS-AT-004-EVAL-DRIFT",
                    "incident_id": "DEMO-EVAL-DRIFT-004",
                    "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-071",
                    "approval_reference": "APR-LIVE-071",
                    "input_schema_version": "1.0",
                    "allowed_side_effects": ["write sandbox output"],
                    "protected_resources": ["metric.py", "validation_data.pt", "checkpoint"],
                    "resource_budget": {"max_runtime_seconds": 30, "network": False},
                    "idempotency_key": "RUN-LABOPS-AT-004-AGENTTEAMS-071",
                    "success_postconditions": {},
                    "audit_context": {"decided_by": "human-operator"},
                },
            }
            (evidence / "gateway_request.json").write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8",
            )
            verified = {
                "status": "VERIFIED",
                "skill_runtime_evidence": {
                    "control-lab-action": {"status": "VERIFIED"},
                },
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )
            self.assertEqual(state["tool_contract"]["status"], "VERIFIED")
            self.assertEqual(state["tool_contract"]["skill"], "control-lab-action@0.2.0")
            self.assertEqual(state["tool_contract"]["caller"], "safe-executor")
            self.assertEqual(state["tool_contract"]["plan_hash"], "bbbbbbbbbbbb…")
            self.assertEqual(state["tool_contract"]["details"]["canonical_plan_sha256"], plan_hash)
            self.assertEqual(
                state["tool_contract"]["details"]["protected_resources"],
                ["metric.py", "validation_data.pt", "checkpoint"],
            )

            with patch(
                "labops.reviewer_state.verify_session",
                return_value={"status": "BLOCKED", "skill_runtime_evidence": {}},
            ):
                configured = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )
            self.assertEqual(configured["tool_contract"]["status"], "CONFIGURED")

            request["tool_contract"]["caller_agent_id"] = "rca-analyst"
            (evidence / "gateway_request.json").write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8",
            )
            with patch(
                "labops.reviewer_state.verify_session",
                return_value={"status": "BLOCKED", "skill_runtime_evidence": {}},
            ):
                mismatched = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )
            self.assertEqual(mismatched["tool_contract"]["status"], "BLOCKED")

    def test_quick_and_live_payloads_validate_against_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            quick = build_reviewer_state(ROOT, sessions, None, "quick", now=self.NOW)
            live = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
            )
            blocked = build_reviewer_state(ROOT, sessions, None, "live", now=self.NOW)
        validate_document(quick, "reviewer_status.schema.json", ROOT)
        validate_document(live, "reviewer_status.schema.json", ROOT)
        validate_document(blocked, "reviewer_status.schema.json", ROOT)
        invalid = deepcopy(live)
        invalid["sources"]["matrix"]["status"] = "PRETEND_LIVE"
        with self.assertRaises(ContractError):
            validate_document(invalid, "reviewer_status.schema.json", ROOT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
