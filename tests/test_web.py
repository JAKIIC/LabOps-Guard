"""Dashboard and container packaging tests (standard library only)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from labops.web import build_checkpoint_demo_state, build_dashboard_state, make_handler, run_bundled_demo
from labops.trace import TraceLog


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestDashboardState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "output"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = run_bundled_demo(self.workspace, repo_root())
        self.assertEqual(rc, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_preserves_fact_boundary(self):
        state = build_dashboard_state(self.workspace)
        self.assertTrue(state["ready"])
        self.assertEqual(state["summary"]["snapshot_status"], "VERIFIED")
        self.assertEqual(state["summary"]["evidence_count"], 22)
        self.assertEqual(state["summary"]["gaps_count"], 10)
        self.assertEqual(state["summary"]["incident_state"], "DEMO_PASSED_NOT_RESOLVED")
        self.assertFalse(state["summary"]["underlying_issue_resolved"])
        self.assertTrue(state["trace"]["ok"])
        self.assertTrue(state["safety"]["excluded_data_not_read"])

    def test_payload_contains_no_arbitrary_workspace_files(self):
        marker = self.workspace / "secret-marker.txt"
        marker.write_text("DO-NOT-SERVE", encoding="utf-8")
        payload = json.dumps(build_dashboard_state(self.workspace), ensure_ascii=False)
        self.assertNotIn("DO-NOT-SERVE", payload)
        self.assertNotIn(str(marker), payload)

    def test_agentteams_bundle_is_exposed_as_safe_summary(self):
        workspace = Path(self.tmp.name) / "agentteams"
        workspace.mkdir()
        artifacts = {
            "registry_record.json": {"allowed_file_count": 13, "verification_status": "VERIFIED", "excluded_data_not_read": True},
            "collected_evidence.json": {"evidence_count": 1, "gaps_count": 1, "evidence": [{"evidence_id": "E-1"}], "gaps": [{"gap_id": "G-1"}], "excluded_data_not_read": True},
            "diagnosis_candidates.json": {"hypotheses": [{"hypothesis_id": "H-1", "evidence_ids": ["E-1"], "state": "BLOCKED"}]},
            "approval_requests.json": [{"approval_id": "A-1", "action_id": "act-1", "status": "APPROVED"}],
            "execution_result.json": {"owner": "controlled-executor", "mode": "DRY_RUN/SIMULATED", "approval": {"approval_id": "A-1", "decided_by": "human-user"}, "result": {"status": "SUCCEEDED", "simulated": True}},
            "verification_result.json": {"demo_verification": "PASSED", "incident_state": "DEMO_PASSED_NOT_RESOLVED", "underlying_issue_resolved": False},
            "evidence_bundle_manifest.json": {"task_id": "LABOPS-AT-001", "incident_id": "I-1", "final_state": "DEMO_PASSED_NOT_RESOLVED", "participating_agents": ["labops-manager", "evidence-collector", "rca-analyst", "controlled-executor", "verification-auditor"], "handoff_count": 5, "counts": {"allowed_files": 13, "evidence": 1, "gaps": 1}, "verification": {"demo_verification": "PASSED", "underlying_issue_resolved": False}, "prohibited_operations_zero": {"network": 0, "install": 0}},
        }
        for name, payload in artifacts.items():
            (workspace / name).write_text(json.dumps(payload), encoding="utf-8")
        TraceLog(workspace / "trace.jsonl").append("incident", "I-1", "verification", to_state="DEMO_PASSED_NOT_RESOLVED")

        state = build_dashboard_state(workspace)
        self.assertTrue(state["ready"])
        self.assertEqual(state["source"]["mode"], "AGENTTEAMS_RUN")
        self.assertEqual(len(state["agentteams"]["agents"]), 5)
        self.assertEqual(state["agentteams"]["handoff_count"], 5)
        self.assertTrue(state["safety"]["prohibited_operations_zero"])
        self.assertEqual(state["summary"]["incident_state"], "DEMO_PASSED_NOT_RESOLVED")


class TestDashboardHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "output"
        with contextlib.redirect_stdout(io.StringIO()):
            run_bundled_demo(self.workspace, repo_root())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.workspace))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def test_dashboard_and_api(self):
        html = urllib.request.urlopen(self.base + "/", timeout=3).read().decode("utf-8")
        self.assertIn("LabOps Guard", html)
        payload = json.load(urllib.request.urlopen(self.base + "/api/status", timeout=3))
        self.assertTrue(payload["ready"])
        health = json.load(urllib.request.urlopen(self.base + "/healthz", timeout=3))
        self.assertTrue(health["ok"])

    def test_dashboard_is_read_only(self):
        request = urllib.request.Request(self.base + "/api/status", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 405)


class TestContainerPackaging(unittest.TestCase):
    def test_container_runs_as_non_root_and_local_port_only(self):
        dockerfile = (repo_root() / "Dockerfile").read_text(encoding="utf-8")
        compose = (repo_root() / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("USER labops", dockerfile)
        self.assertIn("ENTRYPOINT []", dockerfile)
        self.assertIn("--run-demo", dockerfile)
        self.assertIn('"127.0.0.1:8787:8787"', compose)
        self.assertIn('./demo/output-agentteams:/evidence:ro', compose)
        self.assertIn('./artifacts:/checkpoint-artifacts:ro', compose)
        self.assertIn('"--workspace", "/evidence"', compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)


class TestCheckpointDashboardState(unittest.TestCase):
    def test_checkpoint_summary_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "DEMO-RCA-001"
            unsafe = root / "DEMO-RCA-002"
            (valid / "baseline").mkdir(parents=True)
            (unsafe / "runs" / "RUN-DEMO-UNSAFE-001").mkdir(parents=True)
            (valid / "baseline" / "stability_report.json").write_text(json.dumps({"best_accuracy": .98, "current_accuracy": .7, "target_accuracy": .88, "repeats": 3, "stable": True, "passed": True, "configured_checkpoint": "checkpoints/last.pt"}), encoding="utf-8")
            (valid / "state.json").write_text(json.dumps({"state": "RESOLVED"}), encoding="utf-8")
            (valid / "verification.json").write_text(json.dumps({"decision": "PASS", "baseline_accuracy": .7, "candidate_accuracy": .98, "improvement": .28}), encoding="utf-8")
            (unsafe / "state.json").write_text(json.dumps({"state": "ROLLED_BACK"}), encoding="utf-8")
            (unsafe / "verification.json").write_text(json.dumps({"decision": "POLICY_VIOLATION", "claimed_accuracy": 1.0}), encoding="utf-8")
            (unsafe / "runs" / "RUN-DEMO-UNSAFE-001" / "rollback.json").write_text(json.dumps({"metric_hash_restored": True}), encoding="utf-8")
            TraceLog(valid / "trace.jsonl").append("incident", "DEMO-RCA-001", "verification", to_state="RESOLVED")
            TraceLog(unsafe / "trace.jsonl").append("incident", "DEMO-RCA-002", "rollback", to_state="ROLLED_BACK")
            state = build_checkpoint_demo_state(root)
        self.assertTrue(state["ready"])
        self.assertEqual(state["valid_case"]["decision"], "PASS")
        self.assertEqual(state["unsafe_case"]["decision"], "POLICY_VIOLATION")
        self.assertTrue(state["unsafe_case"]["rollback_ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
