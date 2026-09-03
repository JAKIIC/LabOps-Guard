"""Governed recovery and human takeover overlay contracts."""

from __future__ import annotations

import json
import io
import hashlib
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from labops.cli import main as cli_main
from labops.approval_grant import canonical_plan_sha256
from labops.live_demo import HANDOFFS, prepare_session, verify_session
from labops.runner_gateway import RUN_ID_AT004, normalize_tool_contract
from labops.trace import TraceLog
from labops.recovery import (
    RecoveryError,
    accept_human_takeover,
    load_recovery_overlay,
    request_recovery,
    resume_human_takeover,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestRecoveryOverlay(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.sessions_root = Path(self.temp.name)
        prepare_session(repo_root(), self.sessions_root, "20260831-031")
        self.session_root = self.sessions_root / "20260831-031"
        evidence = self.session_root / "evidence"
        (evidence / "verification.json").write_text(
            json.dumps({"decision": "INCONCLUSIVE"}), encoding="utf-8"
        )
        (evidence / "gateway_response.json").write_text(
            json.dumps({"ok": False}), encoding="utf-8"
        )
        (evidence / "matrix_events.json").write_text(
            json.dumps({"events": []}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_complete_live_evidence(self, attempt: dict) -> None:
        manifest = json.loads((self.session_root / "session.json").read_text(encoding="utf-8"))
        evidence = self.session_root / "evidence"

        def write(relative: str, value: object) -> Path:
            path = evidence / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        events = []
        handoffs = []
        for index, (source, target) in enumerate(HANDOFFS, 1):
            event_id = f"$recovery-live-{index}"
            events.append({
                "event_id": event_id,
                "sender_agent": source,
                "room_id": "!recovery-live:example.org",
                "timestamp": f"2026-08-31T13:{index:02d}:00Z",
            })
            handoffs.append({
                "from_agent": source,
                "to_agent": target,
                "matrix_event_id": event_id,
                "status": "COMPLETED",
                "input_artifact_refs": [f"shared/recovery-input-{index}.json"],
                "output_artifact_refs": [f"shared/recovery-output-{index}.json"],
            })
        write("matrix_events.json", {"events": events})
        write("handoff_manifest.json", {"agent_order": manifest["agent_order"], "handoffs": handoffs})

        plan = {
            "task_id": manifest["scenario_contract"],
            "incident_id": manifest["scenario_incident"],
            "plan_id": "PLAN-RECOVERY-031",
            "run_id": attempt["run_id"],
            "changes": [{
                "file": "eval_config.json",
                "field": "evaluation.preprocessing_profile",
                "before": "train_augmented",
                "after": "eval_standard",
            }],
            "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
            "forbidden_changes": ["metric.py", "validation_data.pt", "checkpoint"],
            "live_context": {
                "classification": manifest["classification"],
                "session_id": manifest["session_id"],
                "task_instance_id": manifest["task_instance_id"],
                "incident_instance_id": manifest["incident_instance_id"],
                "attempt_id": attempt["attempt_id"],
                "storage_namespace": manifest["storage_namespace"],
            },
        }
        approval = {
            "schema_version": "1.0",
            "approval_id": "APR-RECOVERY-031",
            "task_id": plan["task_id"],
            "incident_id": plan["incident_id"],
            "plan_id": plan["plan_id"],
            "canonical_plan_sha256": canonical_plan_sha256(plan),
            "run_id": plan["run_id"],
            "decision": "APPROVED",
            "approved_scope": ["eval_config.json:evaluation.preprocessing_profile"],
            "allowed_side_effects": ["write sandbox output"],
            "protected_resources": list(plan["forbidden_changes"]),
            "resource_budget": dict(plan["budget"]),
            "decided_by": "human-operator",
            "approved_at": "2026-08-31T13:40:00Z",
            "expires_at": "2026-08-31T13:50:00Z",
            "nonce": "nonce-recovery-031",
        }
        tool_contract = normalize_tool_contract({
            "experiment_plan": plan,
            "approval": approval,
        })
        write("approval_grant.json", approval)
        write("gateway_request.json", {
            "experiment_plan": plan,
            "approval": approval,
            "tool_contract": tool_contract,
            "approval_binding": {"status": "VALID"},
            "approval_consumption": {"status": "CONSUMED"},
        })
        write("gateway_response.json", {"ok": True, "run_id": plan["run_id"]})
        write("runner/run_result.json", {
            "run_id": plan["run_id"],
            "status": "completed",
            "start_time": "2026-08-31T13:45:00Z",
            "network": "none",
            "sandbox_only": True,
        })
        write("runner/metrics.json", {"candidate_accuracy_values": [0.978125] * 3})
        (evidence / "runner/stdout.log").write_text("recovery runner output", encoding="utf-8")
        (evidence / "runner/stderr.log").write_text("", encoding="utf-8")
        artifacts = {}
        for name in ("run_result.json", "metrics.json", "stdout.log", "stderr.log"):
            path = evidence / "runner" / name
            artifacts[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        write("runner/artifact_manifest.json", {"run_id": plan["run_id"], "artifacts": artifacts})
        write("verification.json", {
            "verified_by": "verification-auditor",
            "attempt_id": attempt["attempt_id"],
            "run_id": plan["run_id"],
            "decision": "PASS",
            "resolution_status": "RESOLVED",
            "checks": {"runner": True, "approval": True, "evidence": True, "recovery": True},
        })
        trace_path = evidence / "trace.jsonl"
        if trace_path.exists():
            trace_path.unlink()
        trace = TraceLog(trace_path)
        for index, (source, target) in enumerate(HANDOFFS, 1):
            trace.append("handoff", f"handoff-{index}", "completed", actor=source,
                         status="COMPLETED", extra={"to_agent": target})
        trace.append("runner", plan["run_id"], "completed", actor="safe-executor", status="completed")
        trace.append("verification", "VERIFY-RECOVERY-031", "independent_check",
                     actor="verification-auditor", status="PASS",
                     extra={"attempt_id": attempt["attempt_id"]})

    def test_evidence_incomplete_preserves_original_and_creates_new_attempt(self) -> None:
        result = request_recovery(
            self.session_root,
            failure_type="EVIDENCE_INCOMPLETE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        overlay = load_recovery_overlay(self.session_root)
        self.assertEqual(result["decision"], "RETRY_AFTER_EVIDENCE")
        self.assertEqual(len(overlay["attempts"]), 2)
        self.assertEqual(overlay["attempts"][0]["attempt_id"], "LIVE-ATTEMPT-20260831-031-01")
        self.assertIsNone(overlay["attempts"][0]["parent_attempt_id"])
        second = overlay["attempts"][1]
        self.assertEqual(second["parent_attempt_id"], overlay["attempts"][0]["attempt_id"])
        self.assertEqual(second["start_state"], "RECEIVED")
        self.assertEqual(second["resume_point"], "EVIDENCE_COLLECTING")
        self.assertEqual(second["owner_id"], "labops-manager")
        self.assertNotEqual(second["run_id"], overlay["attempts"][0]["run_id"])

    def test_recovery_skips_run_ids_owned_by_adjacent_sessions(self) -> None:
        prepare_session(repo_root(), self.sessions_root, "20260831-032")

        result = request_recovery(
            self.session_root,
            failure_type="EVIDENCE_INCOMPLETE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )

        self.assertEqual(
            result["attempt"]["run_id"],
            "RUN-LABOPS-AT-004-AGENTTEAMS-033",
        )
        reservation = (
            self.sessions_root
            / ".labops-run-reservations"
            / "RUN-LABOPS-AT-004-AGENTTEAMS-033.json"
        )
        self.assertEqual(
            json.loads(reservation.read_text(encoding="utf-8"))["session_id"],
            "20260831-031",
        )

    def test_read_only_show_does_not_create_recovery_storage(self) -> None:
        overlay = load_recovery_overlay(self.session_root)
        self.assertEqual(overlay["recovery_trace"]["status"], "ABSENT")
        self.assertFalse((self.session_root / "recovery").exists())

    def test_worker_timeout_retries_once_then_requires_human_takeover(self) -> None:
        first = request_recovery(
            self.session_root,
            failure_type="WORKER_TIMEOUT",
            failed_role="rca-analyst",
            requested_by="labops-manager",
            source_refs=["evidence/matrix_events.json"],
        )
        second = request_recovery(
            self.session_root,
            failure_type="WORKER_TIMEOUT",
            failed_role="rca-analyst",
            requested_by="labops-manager",
            source_refs=["evidence/matrix_events.json"],
        )
        self.assertEqual(first["decision"], "RETRY")
        self.assertEqual(second["decision"], "HUMAN_TAKEOVER")
        self.assertEqual(second["takeover_status"], "TAKEOVER_PENDING")
        overlay = load_recovery_overlay(self.session_root)
        self.assertEqual(overlay["retry_counters"]["WORKER_TIMEOUT:rca-analyst"], 1)
        self.assertEqual(len(overlay["attempts"]), 2)

    def test_capability_missing_without_alternate_records_unavailable_then_takeover(self) -> None:
        result = request_recovery(
            self.session_root,
            failure_type="CAPABILITY_MISSING",
            failed_role="safe-executor",
            requested_by="labops-manager",
            source_refs=["evidence/matrix_events.json"],
        )
        self.assertEqual(result["decision"], "HUMAN_TAKEOVER")
        trace = (self.session_root / "recovery" / "recovery_trace.jsonl").read_text(encoding="utf-8")
        self.assertIn("REASSIGN_UNAVAILABLE", trace)
        self.assertIn("TAKEOVER_PENDING", trace)

    def test_capability_missing_reassigns_only_with_structured_alternate_evidence(self) -> None:
        capability = self.session_root / "evidence" / "capabilities" / "safe-executor-secondary.json"
        capability.parent.mkdir(parents=True)
        capability.write_text(
            json.dumps({
                "worker_id": "safe-executor-secondary",
                "role": "safe-executor",
                "status": "READY",
            }),
            encoding="utf-8",
        )
        (self.session_root / "evidence" / "matrix_events.json").write_text(
            json.dumps({
                "events": [{
                    "event_id": "$alternate-worker-ready",
                    "worker_id": "safe-executor-secondary",
                    "sender_agent": "safe-executor",
                    "room_id": "!labops-live:example.org",
                    "timestamp": "2026-08-31T12:00:00Z",
                }]
            }),
            encoding="utf-8",
        )
        alternate = {
            "worker_id": "safe-executor-secondary",
            "role": "safe-executor",
            "matrix_event_id": "$alternate-worker-ready",
            "capability_ref": "evidence/capabilities/safe-executor-secondary.json",
        }
        result = request_recovery(
            self.session_root,
            failure_type="CAPABILITY_MISSING",
            failed_role="safe-executor",
            failed_worker_id="safe-executor-primary",
            requested_by="labops-manager",
            source_refs=["evidence/matrix_events.json"],
            alternate_worker_evidence=alternate,
        )
        self.assertEqual(result["decision"], "REASSIGN")
        overlay = load_recovery_overlay(self.session_root)
        self.assertEqual(overlay["attempts"][-1]["assigned_worker_id"], "safe-executor-secondary")
        self.assertEqual(overlay["attempts"][-1]["alternate_worker_evidence"], alternate)

    def test_structured_alternate_without_live_references_fails_closed(self) -> None:
        with self.assertRaises(RecoveryError):
            request_recovery(
                self.session_root,
                failure_type="CAPABILITY_MISSING",
                failed_role="safe-executor",
                failed_worker_id="safe-executor-primary",
                requested_by="labops-manager",
                source_refs=["evidence/matrix_events.json"],
                alternate_worker_evidence={
                    "worker_id": "safe-executor-secondary",
                    "role": "safe-executor",
                    "matrix_event_id": "$missing-event",
                    "capability_ref": "evidence/capabilities/missing.json",
                },
            )
        self.assertFalse((self.session_root / "recovery" / "recovery_trace.jsonl").exists())

    def test_invalid_alternate_worker_evidence_fails_closed(self) -> None:
        with self.assertRaises(RecoveryError):
            request_recovery(
                self.session_root,
                failure_type="CAPABILITY_MISSING",
                failed_role="safe-executor",
                failed_worker_id="safe-executor-primary",
                requested_by="labops-manager",
                source_refs=["evidence/matrix_events.json"],
                alternate_worker_evidence={
                    "worker_id": "safe-executor-primary",
                    "role": "safe-executor",
                    "matrix_event_id": "not-a-matrix-event",
                    "capability_ref": "C:/private/capability.json",
                },
            )

    def test_tool_failure_retries_only_when_idempotent_and_safe(self) -> None:
        unsafe = request_recovery(
            self.session_root,
            failure_type="TOOL_FAILURE",
            failed_role="safe-executor",
            requested_by="labops-manager",
            source_refs=["evidence/gateway_response.json"],
            idempotent=False,
            safe_to_retry=True,
        )
        self.assertEqual(unsafe["decision"], "HUMAN_TAKEOVER")

        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            prepare_session(repo_root(), sessions, "20260831-032")
            (sessions / "20260831-032" / "evidence" / "gateway_response.json").write_text(
                json.dumps({"ok": False}), encoding="utf-8"
            )
            safe = request_recovery(
                sessions / "20260831-032",
                failure_type="TOOL_FAILURE",
                failed_role="safe-executor",
                requested_by="labops-manager",
                source_refs=["evidence/gateway_response.json"],
                idempotent=True,
                safe_to_retry=True,
            )
            self.assertEqual(safe["decision"], "RETRY")

    def test_policy_violation_never_retries(self) -> None:
        result = request_recovery(
            self.session_root,
            failure_type="POLICY_VIOLATION",
            failed_role="safe-executor",
            requested_by="verification-auditor",
            source_refs=["evidence/gateway_response.json"],
        )
        self.assertEqual(result["decision"], "ROLLBACK_REQUIRED")
        overlay = load_recovery_overlay(self.session_root)
        self.assertEqual(len(overlay["attempts"]), 1)
        self.assertIsNone(overlay["pending_takeover"])

    def test_recovery_source_reference_must_exist_inside_session(self) -> None:
        with self.assertRaises(RecoveryError):
            request_recovery(
                self.session_root,
                failure_type="EVIDENCE_INCOMPLETE",
                requested_by="verification-auditor",
                source_refs=["../formal-evidence.zip"],
            )

    def test_audit_inconclusive_requires_human_takeover(self) -> None:
        result = request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        self.assertEqual(result["decision"], "HUMAN_TAKEOVER")
        self.assertEqual(result["takeover_status"], "TAKEOVER_PENDING")

    def test_agents_cannot_accept_human_takeover(self) -> None:
        requested = request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        with self.assertRaises(RecoveryError):
            accept_human_takeover(
                self.session_root,
                takeover_id=requested["takeover_id"],
                accepted_by="labops-manager",
            )

    def test_takeover_must_be_accepted_before_same_human_can_resume(self) -> None:
        requested = request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        with self.assertRaises(RecoveryError):
            resume_human_takeover(
                self.session_root,
                takeover_id=requested["takeover_id"],
                resumed_by="human-operator",
                resume_point="VERIFYING",
            )
        accept_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            accepted_by="human-operator",
        )
        with self.assertRaises(RecoveryError):
            resume_human_takeover(
                self.session_root,
                takeover_id=requested["takeover_id"],
                resumed_by="different-human",
                resume_point="VERIFYING",
            )
        resumed = resume_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            resumed_by="human-operator",
            resume_point="VERIFYING",
        )
        self.assertEqual(resumed["decision"], "HUMAN_TAKEOVER_RESUMED")
        overlay = load_recovery_overlay(self.session_root)
        latest = overlay["attempts"][-1]
        self.assertEqual(latest["start_state"], "RECEIVED")
        self.assertEqual(latest["resume_point"], "VERIFYING")
        self.assertEqual(latest["owner_id"], "labops-manager")
        self.assertEqual(latest["required_final_actor"], "verification-auditor")
        self.assertIsNone(overlay["pending_takeover"])
        self.assertIsNotNone(RUN_ID_AT004.fullmatch(latest["run_id"]))
        self.assertNotEqual(latest["run_id"], overlay["attempts"][0]["run_id"])

    def test_takeover_cannot_resume_directly_to_terminal_state(self) -> None:
        requested = request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        accept_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            accepted_by="human-operator",
        )
        for terminal in ("PASS", "RESOLVED", "ROLLED_BACK"):
            with self.assertRaises(RecoveryError):
                resume_human_takeover(
                    self.session_root,
                    takeover_id=requested["takeover_id"],
                    resumed_by="human-operator",
                    resume_point=terminal,
                )

    def test_tampered_recovery_trace_fails_closed(self) -> None:
        request_recovery(
            self.session_root,
            failure_type="EVIDENCE_INCOMPLETE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        path = self.session_root / "recovery" / "recovery_trace.jsonl"
        records = path.read_text(encoding="utf-8").splitlines()
        first = json.loads(records[0])
        first["event"] = "TAMPERED"
        records[0] = json.dumps(first, sort_keys=True)
        path.write_text("\n".join(records) + "\n", encoding="utf-8")
        with self.assertRaises(RecoveryError):
            load_recovery_overlay(self.session_root)

    def test_live_verifier_blocks_while_human_takeover_is_pending(self) -> None:
        request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        result = verify_session(repo_root(), self.sessions_root, "20260831-031")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["recovery_status"], "BLOCKED")
        self.assertTrue(any("takeover" in error.lower() for error in result["errors"]))

    def test_live_verifier_uses_latest_resumed_attempt_and_recovery_digest(self) -> None:
        requested = request_recovery(
            self.session_root,
            failure_type="AUDIT_INCONCLUSIVE",
            requested_by="verification-auditor",
            source_refs=["evidence/verification.json"],
        )
        accept_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            accepted_by="human-operator",
        )
        resumed = resume_human_takeover(
            self.session_root,
            takeover_id=requested["takeover_id"],
            resumed_by="human-operator",
            resume_point="VERIFYING",
        )
        self.write_complete_live_evidence(resumed["attempt"])
        result = verify_session(repo_root(), self.sessions_root, "20260831-031")
        self.assertEqual(result["status"], "VERIFIED", result["errors"])
        self.assertEqual(result["effective_attempt_id"], resumed["attempt"]["attempt_id"])
        self.assertEqual(result["recovery_status"], "VERIFIED")
        self.assertIn("recovery/recovery_trace.jsonl", result["evidence_files"])
        self.assertEqual(
            result["skill_runtime_evidence"]["control-lab-action"]["status"],
            "VERIFIED",
        )

    def _write_initial_complete_evidence(self) -> None:
        manifest = json.loads((self.session_root / "session.json").read_text(encoding="utf-8"))
        self.write_complete_live_evidence({
            "attempt_id": manifest["attempt_id"],
            "run_id": manifest["run_id"],
        })

    def _mutate_gateway_tool_contract(self, field: str, value: str) -> dict:
        request_path = self.session_root / "evidence" / "gateway_request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["tool_contract"][field] = value
        request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
        return verify_session(repo_root(), self.sessions_root, "20260831-031")

    def test_live_verifier_rejects_forged_skill_binding(self) -> None:
        self._write_initial_complete_evidence()
        result = self._mutate_gateway_tool_contract("skill_id", "diagnose-lab-incident")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(
            result["skill_runtime_evidence"]["control-lab-action"]["status"],
            "BLOCKED",
        )
        self.assertTrue(any("Tool Contract" in error for error in result["errors"]))

    def test_live_verifier_rejects_non_executor_caller(self) -> None:
        self._write_initial_complete_evidence()
        result = self._mutate_gateway_tool_contract("caller_agent_id", "labops-manager")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("Tool Contract" in error for error in result["errors"]))

    def test_live_verifier_rejects_tool_contract_identity_mismatch(self) -> None:
        self._write_initial_complete_evidence()
        result = self._mutate_gateway_tool_contract("approval_reference", "APR-FORGED")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("Tool Contract" in error for error in result["errors"]))

    def test_live_verifier_rejects_reduced_gateway_archive(self) -> None:
        self._write_initial_complete_evidence()
        request_path = self.session_root / "evidence" / "gateway_request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        del request["tool_contract"]["input_schema_version"]
        request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

        result = verify_session(repo_root(), self.sessions_root, "20260831-031")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("complete normalized archive" in error for error in result["errors"]))

    def test_cli_requires_explicit_human_confirmation_and_exposes_overlay(self) -> None:
        request = io.StringIO()
        with redirect_stdout(request):
            rc = cli_main([
                "recovery", "request",
                "--session", "20260831-031",
                "--sessions-root", str(self.sessions_root),
                "--failure-type", "AUDIT_INCONCLUSIVE",
                "--requested-by", "verification-auditor",
                "--source-ref", "evidence/verification.json",
            ])
        requested = json.loads(request.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(requested["decision"], "HUMAN_TAKEOVER")

        denied = io.StringIO()
        with redirect_stdout(denied):
            rc = cli_main([
                "recovery", "accept",
                "--session", "20260831-031",
                "--sessions-root", str(self.sessions_root),
                "--takeover-id", requested["takeover_id"],
                "--accepted-by", "human-operator",
                "--confirm", "wrong-id",
            ])
        self.assertEqual(rc, 2)

        accepted = io.StringIO()
        with redirect_stdout(accepted):
            rc = cli_main([
                "recovery", "accept",
                "--session", "20260831-031",
                "--sessions-root", str(self.sessions_root),
                "--takeover-id", requested["takeover_id"],
                "--accepted-by", "human-operator",
                "--confirm", requested["takeover_id"],
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(accepted.getvalue())["takeover_status"], "TAKEOVER_ACCEPTED")

        resumed = io.StringIO()
        with redirect_stdout(resumed):
            rc = cli_main([
                "recovery", "resume",
                "--session", "20260831-031",
                "--sessions-root", str(self.sessions_root),
                "--takeover-id", requested["takeover_id"],
                "--resumed-by", "human-operator",
                "--resume-point", "VERIFYING",
                "--confirm", requested["takeover_id"],
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(resumed.getvalue())["decision"], "HUMAN_TAKEOVER_RESUMED")

        shown = io.StringIO()
        with redirect_stdout(shown):
            rc = cli_main([
                "recovery", "show",
                "--session", "20260831-031",
                "--sessions-root", str(self.sessions_root),
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(shown.getvalue())["attempts"][-1]["resume_point"], "VERIFYING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
