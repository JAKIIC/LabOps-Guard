"""Non-formal live Demo session preparation and verification contracts."""

from __future__ import annotations

import json
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from labops.approval_grant import canonical_plan_sha256
from labops.live_demo import HANDOFFS, prepare_session, verify_session
from labops.trace import TraceLog
from labops.cli import main as cli_main


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestLiveDemoSession(unittest.TestCase):
    def test_cli_prepare_and_verify_use_the_session_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                prepared = cli_main([
                    "live-demo", "prepare", "--session", "20260831-009",
                    "--sessions-root", tmp,
                ])
            self.assertEqual(prepared, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "PREPARED")
            output = io.StringIO()
            with redirect_stdout(output):
                verified = cli_main([
                    "live-demo", "verify", "--session", "20260831-009",
                    "--sessions-root", tmp,
                ])
            self.assertEqual(verified, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")

    def test_prepare_creates_non_formal_isolated_envelope_without_execution_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = prepare_session(repo_root(), root, "20260831-001")
            session = root / "20260831-001"
            manifest = json.loads((session / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "PREPARED")
            self.assertEqual(manifest["classification"], "NON_FORMAL_LIVE_DEMO")
            self.assertEqual(manifest["task_instance_id"], "LIVE-TASK-20260831-001")
            self.assertEqual(manifest["incident_instance_id"], "LIVE-INCIDENT-20260831-001")
            self.assertEqual(manifest["attempt_id"], "LIVE-ATTEMPT-20260831-001-01")
            self.assertEqual(manifest["run_id"], "RUN-LABOPS-AT-004-AGENTTEAMS-001")
            self.assertTrue((session / "manager_task.md").is_file())
            manager_task = (session / "manager_task.md").read_text(encoding="utf-8")
            self.assertIn("LIVE-TASK-20260831-001", manager_task)
            self.assertIn("0.71875", manager_task)
            self.assertIn("Required real handoffs, in order", manager_task)
            self.assertEqual(list((session / "evidence").iterdir()), [])
            self.assertFalse((session / "approval_grant.json").exists())

    def test_prepare_refuses_to_overwrite_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_session(repo_root(), root, "20260831-001")
            with self.assertRaises(FileExistsError):
                prepare_session(repo_root(), root, "20260831-001")

    def test_two_sessions_have_distinct_task_incident_attempt_and_storage_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = prepare_session(repo_root(), root, "20260831-001")["session"]
            second = prepare_session(repo_root(), root, "20260831-002")["session"]
            for key in ("task_instance_id", "incident_instance_id", "attempt_id", "run_id", "storage_namespace"):
                self.assertNotEqual(first[key], second[key])
            second_prompt = (root / "20260831-002" / "manager_task.md").read_text(encoding="utf-8")
            self.assertIn("RUN-LABOPS-AT-004-AGENTTEAMS-002", second_prompt)
            self.assertNotIn("RUN-LABOPS-AT-004-AGENTTEAMS-001", second_prompt)

    def test_verify_blocks_when_real_six_agent_evidence_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_session(repo_root(), root, "20260831-001")
            result = verify_session(repo_root(), root, "20260831-001")
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["executes_agentteams"])
            self.assertFalse(result["archived_replay_is_live"])
            self.assertIn("handoff_manifest.json", " ".join(result["errors"]))

    def test_verify_rejects_placeholder_files_without_real_matrix_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_session(repo_root(), root, "20260831-001")
            evidence = root / "20260831-001" / "evidence"
            files = [
                "handoff_manifest.json",
                "matrix_events.json",
                "approval_grant.json",
                "gateway_request.json",
                "gateway_response.json",
                "runner/run_result.json",
                "runner/metrics.json",
                "runner/artifact_manifest.json",
                "runner/stdout.log",
                "runner/stderr.log",
                "verification.json",
                "trace.jsonl",
            ]
            for relative in files:
                path = evidence / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}" if path.suffix == ".json" else "", encoding="utf-8")
            result = verify_session(repo_root(), root, "20260831-001")
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("handoff" in item.lower() for item in result["errors"]))

    def test_complete_bound_live_evidence_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared = prepare_session(repo_root(), root, "20260831-021")["session"]
            evidence = root / "20260831-021" / "evidence"

            def write(relative: str, value: object) -> Path:
                path = evidence / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                return path

            events = []
            handoffs = []
            for index, (source, target) in enumerate(HANDOFFS, 1):
                event_id = f"$live-event-{index}"
                events.append({
                    "event_id": event_id,
                    "sender_agent": source,
                    "room_id": "!real-labops-room:example.org",
                    "timestamp": f"2026-08-31T11:{index:02d}:00Z",
                })
                handoffs.append({
                    "from_agent": source,
                    "to_agent": target,
                    "matrix_event_id": event_id,
                    "status": "COMPLETED",
                    "input_artifact_refs": [f"shared/input-{index}.json"],
                    "output_artifact_refs": [f"shared/output-{index}.json"],
                })
            write("matrix_events.json", {"events": events})
            write("handoff_manifest.json", {
                "agent_order": prepared["agent_order"],
                "handoffs": handoffs,
            })

            plan = {
                "task_id": prepared["scenario_contract"],
                "incident_id": prepared["scenario_incident"],
                "plan_id": "PLAN-LIVE-021",
                "run_id": prepared["run_id"],
                "changes": [{
                    "file": "eval_config.json",
                    "field": "evaluation.preprocessing_profile",
                    "before": "train_augmented",
                    "after": "eval_standard",
                }],
                "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
                "forbidden_changes": ["metric.py", "validation_data.pt", "checkpoint"],
                "live_context": {
                    "classification": prepared["classification"],
                    "session_id": prepared["session_id"],
                    "task_instance_id": prepared["task_instance_id"],
                    "incident_instance_id": prepared["incident_instance_id"],
                    "attempt_id": prepared["attempt_id"],
                    "storage_namespace": prepared["storage_namespace"],
                },
            }
            approval = {
                "schema_version": "1.0",
                "approval_id": "APR-LIVE-021",
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
                "approved_at": "2026-08-31T11:55:00Z",
                "expires_at": "2026-08-31T12:05:00Z",
                "nonce": "nonce-live-021",
            }
            tool_contract = {
                "task_id": plan["task_id"],
                "incident_id": plan["incident_id"],
                "run_id": plan["run_id"],
                "approval_reference": approval["approval_id"],
                "allowed_side_effects": list(approval["allowed_side_effects"]),
                "protected_resources": list(approval["protected_resources"]),
                "resource_budget": dict(approval["resource_budget"]),
            }
            write("approval_grant.json", approval)
            write("gateway_request.json", {
                "experiment_plan": plan,
                "approval": approval,
                "tool_contract": tool_contract,
                "approval_binding": {"status": "VALID"},
                "approval_consumption": {"status": "CONSUMED"},
            })
            write("gateway_response.json", {"ok": True, "run_id": plan["run_id"]})

            run_result = {
                "run_id": plan["run_id"],
                "status": "completed",
                "start_time": "2026-08-31T12:00:00Z",
                "network": "none",
                "sandbox_only": True,
            }
            metrics = {"candidate_accuracy_values": [0.978125, 0.978125, 0.978125]}
            write("runner/run_result.json", run_result)
            write("runner/metrics.json", metrics)
            (evidence / "runner/stdout.log").write_text("real runner output", encoding="utf-8")
            (evidence / "runner/stderr.log").write_text("", encoding="utf-8")
            artifacts = {}
            for name in ("run_result.json", "metrics.json", "stdout.log", "stderr.log"):
                path = evidence / "runner" / name
                artifacts[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            write("runner/artifact_manifest.json", {"run_id": plan["run_id"], "artifacts": artifacts})
            write("verification.json", {
                "verified_by": "verification-auditor",
                "run_id": plan["run_id"],
                "decision": "PASS",
                "resolution_status": "RESOLVED",
                "checks": {"runner": True, "approval": True, "evidence": True},
            })

            trace = TraceLog(evidence / "trace.jsonl")
            for index, (source, target) in enumerate(HANDOFFS, 1):
                trace.append(
                    "handoff", f"handoff-{index}", "completed",
                    actor=source, status="COMPLETED", extra={"to_agent": target},
                )
            trace.append("runner", plan["run_id"], "completed", actor="safe-executor", status="completed")
            trace.append("verification", "VERIFY-LIVE-021", "independent_check", actor="verification-auditor", status="PASS")

            result = verify_session(repo_root(), root, "20260831-021")
            self.assertEqual(result["status"], "VERIFIED", result["errors"])
            self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
