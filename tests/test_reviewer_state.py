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
from labops.skill_registry import list_skills


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

    def test_handoff_counts_separate_observed_from_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            empty = {
                "connected": True,
                "last_success_at": "2026-08-28T11:59:55Z",
                "events": [],
            }
            state_empty = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", empty, self.NOW,
            )
            kinds = (
                ("manager_to_collector", "labops-manager"),
                ("collector_to_rca", "evidence-collector"),
                ("rca_to_planner", "rca-analyst"),
            )
            partial = {
                **empty,
                "events": [
                    self._event(
                        kind,
                        f"$observed-{index}",
                        actor,
                        "FROM",
                        "TO",
                        f"2026-08-28T11:59:0{index}Z",
                    )
                    for index, (kind, actor) in enumerate(kinds, 1)
                ],
            }
            (session_root / "observer").mkdir(exist_ok=True)
            (session_root / "observer" / "evidence_sync.json").write_text(
                json.dumps(
                    {
                        "status": "MIRRORED",
                        "published": False,
                        "errors": ["EVIDENCE_INCOMPLETE"],
                        "checked_at": "2026-08-28T11:59:56Z",
                        "mirror_digest": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
            state_partial = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", partial, self.NOW,
            )

        self.assertEqual(state_empty["handoffs"], {"observed": 0, "verified": 0, "total": 6})
        self.assertEqual(state_empty["recovery"]["status"], "CONFIGURED")
        self.assertIsNone(state_empty["recovery"]["latest_attempt"])
        self.assertEqual(
            state_partial["handoffs"], {"observed": 3, "verified": 0, "total": 6}
        )
        self.assertEqual(state_partial["evidence_sync"]["status"], "MIRRORED")
        self.assertEqual(
            state_partial["evidence_sync"]["errors"], ["EVIDENCE_INCOMPLETE"]
        )
        confidence = {
            item["agent_id"]: item["confidence_state"]
            for item in state_partial["agents"]
        }
        self.assertEqual(confidence["labops-manager"], "OBSERVED")
        self.assertEqual(confidence["evidence-collector"], "OBSERVED")
        self.assertEqual(confidence["rca-analyst"], "OBSERVED")
        self.assertEqual(confidence["experiment-planner"], "CONFIGURED")

    def test_verified_handoff_manifest_upgrades_all_six_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            roles = [
                ("labops-manager", "evidence-collector", "manager_to_collector"),
                ("evidence-collector", "rca-analyst", "collector_to_rca"),
                ("rca-analyst", "experiment-planner", "rca_to_planner"),
                ("experiment-planner", "safe-executor", "approval_pending"),
                ("safe-executor", "verification-auditor", "executor_to_auditor"),
                ("verification-auditor", "labops-manager", "verification_completed"),
            ]
            events = []
            matrix_events = []
            handoffs = []
            for index, (source, target, kind) in enumerate(roles, 1):
                event_id = f"$verified-{index}"
                events.append(
                    self._event(
                        kind,
                        event_id,
                        source,
                        "FROM",
                        "TO",
                        f"2026-08-28T11:59:0{index}Z",
                    )
                )
                matrix_events.append(
                    {
                        "event_id": event_id,
                        "sender_agent": source,
                        "timestamp": f"2026-08-28T11:59:0{index}Z",
                    }
                )
                handoffs.append(
                    {
                        "handoff": index,
                        "from_agent": source,
                        "to_agent": target,
                        "matrix_event_id": event_id,
                        "status": "COMPLETED",
                        "input_artifact_refs": [f"input-{index}.json"],
                        "output_artifact_refs": [f"output-{index}.json"],
                    }
                )
            (session_root / "evidence" / "handoff_manifest.json").write_text(
                json.dumps({"handoffs": handoffs}), encoding="utf-8"
            )
            (session_root / "evidence" / "matrix_events.json").write_text(
                json.dumps({"events": matrix_events}), encoding="utf-8"
            )
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "b" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT,
                    sessions,
                    "20260831-071",
                    "live",
                    {
                        "connected": True,
                        "last_success_at": "2026-08-28T11:59:55Z",
                        "events": events,
                    },
                    self.NOW,
                )

        self.assertEqual(state["handoffs"], {"observed": 6, "verified": 6, "total": 6})
        self.assertTrue(
            all(item["confidence_state"] == "VERIFIED" for item in state["agents"])
        )

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
            current_version = next(
                item["version"]
                for item in list_skills(ROOT)
                if item["skill_id"] == "control-lab-action"
            )
            self.assertEqual(
                state["tool_contract"]["skill"],
                f"control-lab-action@{current_version}",
            )
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

    def test_verified_simulated_run_never_projects_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            verification = {
                "verified_by": "verification-auditor",
                "decision": "PASS",
                "incident_state": "DEMO_PASSED_NOT_RESOLVED",
                "underlying_issue_resolved": False,
                "verified_at": "2026-08-28T11:59:09Z",
            }
            (session_root / "evidence" / "verification.json").write_text(
                json.dumps(verification, ensure_ascii=False), encoding="utf-8",
            )
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )

        self.assertEqual(
            state["incident"]["workflow_state"], "DEMO_PASSED_NOT_RESOLVED",
        )
        auditor = next(
            item for item in state["agents"]
            if item["agent_id"] == "verification-auditor"
        )
        self.assertEqual(auditor["workflow_state"], "AUDIT_PASSED")
        terminal = next(
            item for item in state["timeline"] if item["kind"] == "terminal_decided"
        )
        self.assertEqual(terminal["workflow_to"], "DEMO_PASSED_NOT_RESOLVED")
        self.assertEqual(state["audit"]["resolution_status"], "DEMO_PASSED_NOT_RESOLVED")

    def test_unverified_terminal_and_publication_events_do_not_advance_incident(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            snapshot = self._matrix_snapshot()
            snapshot["events"].extend([
                self._event(
                    "terminal_decided",
                    "$unverified-terminal",
                    "verification-auditor",
                    "VERIFYING",
                    "DEMO_PASSED_NOT_RESOLVED",
                    "2026-08-28T11:59:09Z",
                ),
                self._event(
                    "commander_published",
                    "$unverified-publication",
                    "labops-manager",
                    "DEMO_PASSED_NOT_RESOLVED",
                    "DEMO_PASSED_NOT_RESOLVED",
                    "2026-08-28T11:59:10Z",
                ),
            ])
            with patch(
                "labops.reviewer_state.verify_session",
                return_value={"status": "BLOCKED", "skill_runtime_evidence": {}},
            ):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", snapshot, self.NOW,
                )

        by_kind = {item["kind"]: item for item in state["timeline"]}
        self.assertEqual(by_kind["terminal_decided"]["evidence_state"], "CONFIGURED")
        self.assertEqual(by_kind["commander_published"]["evidence_state"], "CONFIGURED")
        self.assertEqual(state["incident"]["workflow_state"], "APPROVAL_PENDING")
        self.assertEqual(state["incident"]["last_event"], "approval_pending")

    def test_verified_terminal_requires_later_independent_manager_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            verification = {
                "verified_by": "verification-auditor",
                "decision": "PASS",
                "incident_state": "DEMO_PASSED_NOT_RESOLVED",
                "underlying_issue_resolved": False,
                "verified_at": "2026-08-28T11:59:09Z",
            }
            (session_root / "evidence" / "verification.json").write_text(
                json.dumps(verification, ensure_ascii=False), encoding="utf-8",
            )
            snapshot = self._matrix_snapshot()
            snapshot["events"].append(self._event(
                "commander_published",
                "$manager-publication",
                "labops-manager",
                "DEMO_PASSED_NOT_RESOLVED",
                "DEMO_PASSED_NOT_RESOLVED",
                "2026-08-28T11:59:10Z",
            ))
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", snapshot, self.NOW,
                )

        by_kind = {item["kind"]: item for item in state["timeline"]}
        self.assertEqual(by_kind["terminal_decided"]["evidence_state"], "VERIFIED")
        self.assertEqual(by_kind["commander_published"]["evidence_state"], "VERIFIED")
        self.assertEqual(by_kind["commander_published"]["event_id"], "$manager-publication")
        self.assertEqual(state["incident"]["last_event"], "commander_published")

    def test_verified_recovery_projects_effective_attempt_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            verification = {
                "verified_by": "verification-auditor",
                "decision": "PASS",
                "attempt_id": "LIVE-ATTEMPT-20260831-071-02",
                "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-072",
                "incident_state": "DEMO_PASSED_NOT_RESOLVED",
                "underlying_issue_resolved": False,
                "verified_at": "2026-08-28T11:59:09Z",
            }
            (session_root / "evidence" / "verification.json").write_text(
                json.dumps(verification, ensure_ascii=False), encoding="utf-8",
            )
            verified = {
                "status": "VERIFIED",
                "effective_attempt_id": "LIVE-ATTEMPT-20260831-071-02",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )

        self.assertEqual(state["incident"]["attempt_id"], "LIVE-ATTEMPT-20260831-071-02")
        self.assertEqual(state["incident"]["run_id"], "RUN-LABOPS-AT-004-AGENTTEAMS-072")

    def _write_runner_outcome(
        self,
        session_root: Path,
        *,
        metrics_candidate: float = 0.9781249761581421,
        run_candidate: float = 0.9781249761581421,
        verification_candidate: float = 0.9781249761581421,
        run_changed_paths: list[str] | None = None,
        verification_changed_paths: list[str] | None = None,
    ) -> None:
        baseline = 0.71875
        runner_root = session_root / "evidence" / "runner"
        runner_root.mkdir(parents=True, exist_ok=True)
        metrics = {
            "baseline_accuracy_values": [baseline, baseline, baseline],
            "candidate_accuracy_values": [
                metrics_candidate,
                metrics_candidate,
                metrics_candidate,
            ],
            "baseline_accuracy": baseline,
            "candidate_accuracy": metrics_candidate,
        }
        changed = run_changed_paths or [
            "sandbox/eval_config.json:evaluation.preprocessing_profile",
        ]
        run_result = {
            "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-072",
            "status": "completed",
            "network": "none",
            "sandbox_only": True,
            "changed_paths": changed,
            "metrics": {
                **metrics,
                "candidate_accuracy": run_candidate,
            },
            "protected_hashes": {
                "checkpoint_unchanged": True,
                "evaluation_protocol_unchanged": True,
                "metric_unchanged": True,
                "model_unchanged": True,
                "preprocessing_unchanged": True,
                "validation_data_unchanged": True,
            },
        }
        verified_changed = verification_changed_paths or changed
        verification = {
            "verified_by": "verification-auditor",
            "decision": "PASS",
            "incident_state": "DEMO_PASSED_NOT_RESOLVED",
            "underlying_issue_resolved": False,
            "checks": {
                "metrics_recomputed_from_raw_stdout": {
                    "pass": True,
                    "baseline_accuracy": baseline,
                    "candidate_accuracy": verification_candidate,
                    "baseline_repeats": [baseline, baseline, baseline],
                    "candidate_repeats": [
                        verification_candidate,
                        verification_candidate,
                        verification_candidate,
                    ],
                    "improvement": verification_candidate - baseline,
                },
                "success_criteria_met": {
                    "pass": True,
                    "accuracy_ge_0.97": True,
                    "candidate_accuracy": verification_candidate,
                    "improvement": verification_candidate - baseline,
                    "repeats": 3,
                },
                "boundaries_respected": {
                    "pass": True,
                    "sandbox_only": True,
                    "network": "none",
                    "changed_paths": verified_changed,
                },
                "protected_hashes_immutable": {
                    "pass": True,
                    "all_unchanged_flags_true": True,
                },
            },
        }
        (runner_root / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False), encoding="utf-8",
        )
        (runner_root / "run_result.json").write_text(
            json.dumps(run_result, ensure_ascii=False), encoding="utf-8",
        )
        (session_root / "evidence" / "verification.json").write_text(
            json.dumps(verification, ensure_ascii=False), encoding="utf-8",
        )

    def test_verified_runner_projects_cross_checked_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            self._write_runner_outcome(session_root)
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )

        runner = state["runner"]
        self.assertEqual(runner["baseline_accuracy"], 0.71875)
        self.assertEqual(runner["candidate_accuracy"], 0.9781249761581421)
        self.assertEqual(runner["baseline_repeats"], 3)
        self.assertEqual(runner["candidate_repeats"], 3)
        self.assertEqual(runner["minimum_accuracy"], 0.97)
        self.assertAlmostEqual(runner["accuracy_improvement"], 0.2593749761581421)
        self.assertEqual(
            runner["changed_paths"],
            ["sandbox/eval_config.json:evaluation.preprocessing_profile"],
        )
        self.assertTrue(runner["protected_hashes_unchanged"])
        self.assertEqual(state["limitations"], [])

    def test_runner_outcome_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            self._write_runner_outcome(
                session_root,
                run_candidate=0.91,
                verification_changed_paths=["sandbox/other.json:value"],
            )
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )

        self.assertIsNone(state["runner"]["candidate_accuracy"])
        self.assertIsNone(state["runner"]["accuracy_improvement"])
        self.assertEqual(state["runner"]["changed_paths"], [])
        self.assertIn(
            "RUNNER_OUTCOME_CONFLICT: candidate_accuracy, changed_paths",
            state["limitations"],
        )

    def test_runner_outcome_missing_evidence_stays_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT, sessions, "20260831-071", "live", self._matrix_snapshot(), self.NOW,
                )

        runner = state["runner"]
        for field in (
            "baseline_accuracy",
            "candidate_accuracy",
            "baseline_repeats",
            "candidate_repeats",
            "minimum_accuracy",
            "accuracy_improvement",
            "protected_hashes_unchanged",
        ):
            with self.subTest(field=field):
                self.assertIsNone(runner[field])
        self.assertEqual(runner["changed_paths"], [])

    def test_live_timeline_uses_latest_observed_event_for_current_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            self._session(sessions)
            snapshot = self._matrix_snapshot()
            snapshot["events"].append(self._event(
                "manager_to_collector",
                "$event-mgr-collector-attempt-02",
                "labops-manager",
                "RECEIVED",
                "EVIDENCE_COLLECTING",
                "2026-08-28T11:59:09Z",
            ))
            state = build_reviewer_state(
                ROOT, sessions, "20260831-071", "live", snapshot, self.NOW,
            )

        event = next(item for item in state["timeline"] if item["kind"] == "manager_to_collector")
        self.assertEqual(event["event_id"], "$event-mgr-collector-attempt-02")

    def test_verified_handoff_manifest_projects_rca_participation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            session_root = self._session(sessions)
            event_ids = [f"$handoff-{index}" for index in range(1, 7)]
            handoffs = []
            roles = [
                ("labops-manager", "evidence-collector"),
                ("evidence-collector", "rca-analyst"),
                ("rca-analyst", "experiment-planner"),
                ("experiment-planner", "safe-executor"),
                ("safe-executor", "verification-auditor"),
                ("verification-auditor", "labops-manager"),
            ]
            matrix_events = []
            for index, ((source, target), event_id) in enumerate(zip(roles, event_ids), 1):
                handoffs.append({
                    "handoff": index,
                    "from_agent": source,
                    "to_agent": target,
                    "matrix_event_id": event_id,
                    "status": "COMPLETED",
                    "input_artifact_refs": [f"input-{index}.json"],
                    "output_artifact_refs": [f"output-{index}.json"],
                })
                matrix_events.append({
                    "event_id": event_id,
                    "sender_agent": source,
                    "timestamp": f"2026-08-28T11:59:{index:02d}Z",
                })
            (session_root / "evidence" / "handoff_manifest.json").write_text(
                json.dumps({"handoffs": handoffs}, ensure_ascii=False), encoding="utf-8",
            )
            (session_root / "evidence" / "matrix_events.json").write_text(
                json.dumps({"events": matrix_events}, ensure_ascii=False), encoding="utf-8",
            )
            verified = {
                "status": "VERIFIED",
                "evidence_digest": "a" * 64,
                "skill_runtime_evidence": {},
                "errors": [],
            }
            with patch("labops.reviewer_state.verify_session", return_value=verified):
                state = build_reviewer_state(
                    ROOT,
                    sessions,
                    "20260831-071",
                    "live",
                    None,
                    self.NOW,
                )

        rca = next(item for item in state["agents"] if item["agent_id"] == "rca-analyst")
        planner = next(
            item for item in state["agents"] if item["agent_id"] == "experiment-planner"
        )
        self.assertEqual(rca["workflow_state"], "DIAGNOSIS_READY")
        self.assertEqual(rca["evidence_state"], "VERIFIED")
        self.assertEqual(planner["workflow_state"], "PLAN_READY")
        self.assertEqual(planner["evidence_state"], "VERIFIED")
        commander = next(
            item for item in state["agents"] if item["agent_id"] == "labops-manager"
        )
        self.assertEqual(commander["workflow_state"], "EVIDENCE_COLLECTING")
        self.assertEqual(commander["evidence_state"], "VERIFIED")
        by_kind = {item["kind"]: item for item in state["timeline"]}
        self.assertEqual(by_kind["hypotheses_ranked"]["evidence_state"], "VERIFIED")
        self.assertEqual(by_kind["rca_to_planner"]["evidence_state"], "VERIFIED")
        self.assertEqual(by_kind["rca_to_planner"]["source"], "VERIFIED_HANDOFF_MANIFEST")
        self.assertEqual(by_kind["rca_to_planner"]["event_id"], "$handoff-3")
        self.assertEqual(by_kind["verification_completed"]["evidence_state"], "VERIFIED")
        self.assertEqual(by_kind["commander_published"]["evidence_state"], "CONFIGURED")

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
