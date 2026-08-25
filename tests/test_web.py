"""Dashboard and container packaging tests (standard library only)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from labops.web import build_agentteams_v2_state, build_agentteams_v3_state, build_at004_state, build_checkpoint_demo_state, build_dashboard_state, make_handler, run_bundled_demo
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

    def test_trust_layer_exposes_ordered_evidence_chain_without_score(self):
        root = repo_root()
        state = build_dashboard_state(
            self.workspace,
            agentteams_v2_workspace=root / "demo" / "output-agentteams-at002",
            at004_workspace=root / "demo" / "output-agentteams-at004",
        )

        trust = state["trust_layer"]
        self.assertEqual(trust["contract"], "Trust Contract v1")
        self.assertEqual(trust["state_machine"], "Trust State Machine v1")
        self.assertEqual(
            trust["positioning"],
            "Trust Infrastructure for Production Agent Systems",
        )
        self.assertTrue(trust["read_only"])
        self.assertEqual(
            trust["evidence_chain"],
            ["identity", "policy", "execution", "evidence", "audit"],
        )
        self.assertEqual(trust["skills"]["registered_count"], 7)
        for domain_id in trust["evidence_chain"]:
            with self.subTest(domain_id=domain_id):
                domain = trust[domain_id]
                self.assertIn(domain["status"], {"VERIFIED", "CONFIGURED", "LIMITED", "BLOCKED"})
                self.assertTrue(domain["summary"])
                self.assertIsInstance(domain["checks"], dict)
                self.assertTrue(domain["evidence_refs"])
        self.assertNotIn("score", json.dumps(trust, ensure_ascii=False).lower())

    def test_blocked_trust_layer_does_not_expose_host_paths(self):
        with tempfile.TemporaryDirectory() as missing_root:
            state = build_dashboard_state(self.workspace, project_root=missing_root)

        payload = json.dumps(state["trust_layer"], ensure_ascii=False)
        self.assertEqual(state["trust_layer"]["contract_status"], "BLOCKED")
        self.assertNotIn(missing_root, payload)
        self.assertNotIn(Path(missing_root).name, payload)
        self.assertNotIn("FileNotFoundError", payload)


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
        self.assertIn("Trust Contract v1", html)
        self.assertIn("Trust State Machine v1", html)
        self.assertNotIn("Trust Score", html)
        self.assertNotIn("state_machine_v3", html)
        self.assertNotIn("<form", html.lower())
        payload = json.load(urllib.request.urlopen(self.base + "/api/status", timeout=3))
        self.assertTrue(payload["ready"])
        health = json.load(urllib.request.urlopen(self.base + "/healthz", timeout=3))
        self.assertTrue(health["ok"])

    def test_dashboard_is_read_only(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                request = urllib.request.Request(self.base + "/api/status", data=b"{}", method=method)
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
        self.assertIn('./demo/output-agentteams-at002:/agentteams-v2:ro', compose)
        self.assertIn('./demo/output-agentteams-at003:/agentteams-v3:ro', compose)
        self.assertIn('./demo/output-agentteams-at004:/at004:ro', compose)
        self.assertIn('"--workspace", "/evidence"', compose)
        self.assertIn('"--agentteams-v2-workspace", "/agentteams-v2"', compose)
        self.assertIn('"--agentteams-v3-workspace", "/agentteams-v3"', compose)
        self.assertIn('"--at004-workspace", "/at004"', compose)
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


class TestAgentTeamsV2DashboardState(unittest.TestCase):
    def test_real_bundle_is_revalidated_and_summarized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_paths = []
            for incident, count in (("DEMO-RCA-001", 8), ("DEMO-RCA-002", 9)):
                path = root / f"{incident}.jsonl"
                trace = TraceLog(path)
                for index in range(count):
                    trace.append("handoff", incident, f"event-{index}", actor="worker")
                trace_paths.append(path)

            handoffs = [{"handoff": index, "role": role, "worker": worker, "task_id": "LABOPS-AT-002", "input": ["input"], "output": ["output"], "time": "2026-08-03T10:00:00Z", "status": "VALID"} for index, (role, worker) in enumerate((
                ("evidence-collector", "evidence-collector"),
                ("rca-analyst", "rca-analyst"),
                ("experiment-planner", "researcher"),
                ("safe-executor", "controlled-executor"),
                ("verification-auditor", "verification-auditor"),
                ("labops-manager", "labops-manager"),
            ), 1)]
            payloads = {
                "artifacts/handoff_manifest.json": {"task_id": "LABOPS-AT-002", "final_state": "BLOCKED", "six_roles_run": True, "roles_mapping": {"labops-manager": "labops-manager", "evidence-collector": "evidence-collector", "rca-analyst": "rca-analyst", "experiment-planner": "researcher", "safe-executor": "controlled-executor", "verification-auditor": "verification-auditor"}, "handoffs": handoffs, "unresolved_limitations": ["torch missing"]},
                "artifacts/approval_request_LABOPS-AT-002.json": {"approval_id": "A-1", "decision": "APPROVED", "decided_by": "human-user", "approved_at": "2026-08-03T10:00:00Z", "scope": {"A": "sandbox"}, "not_approved": ["metric.py"]},
                "artifacts/DEMO-RCA-001/verification.json": {"decision": "INCONCLUSIVE", "resolution_status": "DEMO_PASSED_NOT_RESOLVED", "resolved": False, "reason": "torch missing", "checks": {"approval_before_execution": {"pass": True}, "changed_paths_within_sandbox": {"pass": True}, "metric_immutability": {"hash_unchanged": True}, "concrete_postcondition": {"failure": "ModuleNotFoundError: torch"}}},
                "artifacts/DEMO-RCA-002/verification.json": {"decision": "POLICY_VIOLATION", "resolution_status": "ROLLED_BACK", "resolved": True, "checks": {"tamper_detected": {"pass": True}, "restored_hash_matches_frozen": {"hash_match": True, "restored_metric_hash": "abc", "frozen_baseline_hash": "abc"}}},
                "artifacts/DEMO-RCA-001/plan.json": {"changes": [{"file": "eval_config.json", "field": "checkpoint"}], "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False}, "forbidden_changes": ["metric.py", "dataset", "target_metric"], "rollback": "discard sandbox"},
                "artifacts/DEMO-RCA-002/approvals/POLICY-REJECTION.json": {"decision": "POLICY_REJECTED"},
                "artifacts/DEMO-RCA-001/runs/RUN-DEMO-001/run_manifest.json": {"status": "failed"},
                "artifacts/DEMO-RCA-002/runs/RUN-DEMO-UNSAFE-001/rollback.json": {"metric_hash_restored": True},
            }
            raw_files = {name: json.dumps(payload, ensure_ascii=False).encode("utf-8") for name, payload in payloads.items()}
            raw_files["artifacts/DEMO-RCA-001/trace.jsonl"] = trace_paths[0].read_bytes()
            raw_files["artifacts/DEMO-RCA-002/trace.jsonl"] = trace_paths[1].read_bytes()
            bundle_path = root / "LABOPS-AT-002-evidence-bundle.zip"
            with zipfile.ZipFile(bundle_path, "w") as bundle:
                for name, data in raw_files.items():
                    bundle.writestr(name, data)
            top_manifest = {
                "task_id": "LABOPS-AT-002",
                "final_state": "BLOCKED",
                "artifacts": {name: hashlib.sha256(data).hexdigest() for name, data in raw_files.items()},
                "zip_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            }
            (root / "evidence_bundle_manifest.json").write_text(json.dumps(top_manifest), encoding="utf-8")
            state = build_agentteams_v2_state(root)

        self.assertTrue(state["ready"])
        self.assertTrue(state["six_roles_run"])
        self.assertEqual(len(state["roles"]), 6)
        self.assertEqual(len(state["handoffs"]), 6)
        self.assertEqual(state["valid_case"]["decision"], "INCONCLUSIVE")
        self.assertEqual(state["unsafe_case"]["decision"], "POLICY_VIOLATION")
        self.assertTrue(state["unsafe_case"]["hash_restored"])
        self.assertEqual(state["trace_chains"]["DEMO-RCA-001"]["entries"], 8)
        self.assertEqual(state["trace_chains"]["DEMO-RCA-002"]["entries"], 9)
        self.assertTrue(state["bundle"]["zip_hash_ok"])
        self.assertTrue(state["bundle"]["artifact_hashes_ok"])
        self.assertTrue(all(state["planner_checks"].values()))


class TestAgentTeamsV3DashboardState(unittest.TestCase):
    def test_real_at003_bundle_is_revalidated_and_summarized(self):
        root = repo_root() / "demo" / "output-agentteams-at003"
        state = build_agentteams_v3_state(root)

        self.assertTrue(state["ready"])
        self.assertEqual(state["task_id"], "LABOPS-AT-003")
        self.assertEqual(state["final_state"], "RESOLVED")
        self.assertTrue(state["six_roles_run"])
        self.assertEqual(len(state["roles"]), 6)
        self.assertEqual(len(state["handoffs"]), 6)
        self.assertTrue(all(state["planner_checks"].values()))
        self.assertTrue(state["approval"]["before_execution"])
        self.assertEqual(state["runner"]["network"], "none")
        self.assertTrue(state["runner"]["metric_unchanged"])
        self.assertTrue(state["runner"]["validation_data_unchanged"])
        self.assertAlmostEqual(state["runner"]["baseline_accuracy"], 0.70, places=5)
        self.assertAlmostEqual(state["runner"]["candidate_accuracy"], 0.98125, places=5)
        self.assertTrue(state["capability"]["all_pass"])
        self.assertEqual(state["verification"]["decision"], "PASS")
        self.assertEqual(state["verification"]["resolution_status"], "RESOLVED")
        self.assertTrue(state["verification"]["checks_all_pass"])
        self.assertTrue(state["trace"]["ok"])
        self.assertEqual(state["trace"]["entries"], 10)
        self.assertTrue(state["trace"]["event_ids_unique"])
        self.assertTrue(state["trace"]["issue_preserved"])
        self.assertTrue(state["trace"]["final_audit_ok"])
        self.assertTrue(state["bundle"]["zip_hash_ok"])
        self.assertTrue(state["bundle"]["artifact_hashes_ok"])
        self.assertTrue(state["bundle"]["runner_artifact_hashes_ok"])


class TestAT004DashboardState(unittest.TestCase):
    def test_missing_local_validation_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = build_at004_state(Path(tmp))
        self.assertFalse(state["ready"])

    def test_main_payload_uses_committed_agentteams_provenance(self):
        root = repo_root() / "demo" / "output-agentteams-at004"
        state = build_dashboard_state(repo_root() / "demo" / "output-agentteams", at004_workspace=root)
        self.assertEqual(state["main_demo"]["source_mode"], "AGENTTEAMS_RUN")
        self.assertTrue(state["main_demo"]["agentteams"]["six_roles_run"])

    def test_real_agentteams_bundle_is_revalidated_and_becomes_main_demo(self):
        root = repo_root() / "demo" / "output-agentteams-at004"
        state = build_at004_state(root)

        self.assertTrue(state["ready"])
        self.assertEqual(state["source_mode"], "AGENTTEAMS_RUN")
        self.assertEqual(state["task_id"], "LABOPS-AT-004-EVAL-DRIFT")
        self.assertEqual(state["status"], "PASS")
        self.assertEqual(state["resolution_status"], "RESOLVED")
        self.assertTrue(state["agentteams"]["six_roles_run"])
        self.assertEqual(len(state["agentteams"]["roles"]), 6)
        self.assertEqual(len(state["agentteams"]["handoffs"]), 6)
        self.assertEqual(state["trace"]["entries"], 7)
        self.assertTrue(state["trace"]["event_ids_unique"])
        self.assertEqual(state["trace"]["final_audit"], "CHAIN_OK")
        self.assertEqual(state["trace"]["final_acceptance"], "ACCEPTED")
        self.assertTrue(state["trace"]["first_issue_preserved"])
        self.assertEqual(len(state["runs"]), 1)
        self.assertAlmostEqual(state["runs"][0]["baseline_accuracy"], 0.71875)
        self.assertAlmostEqual(state["runs"][0]["candidate_accuracy"], 0.9781249761581421)
        self.assertTrue(all(state["plan_checks"].values()))
        self.assertTrue(all(state["integrity"].values()))
        self.assertTrue(state["verification"]["checks_all_pass"])
        self.assertEqual(state["bundle"]["sha256"], "4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd")


if __name__ == "__main__":
    unittest.main(verbosity=2)
