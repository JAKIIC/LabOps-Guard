"""Dedicated PyTorch CPU Runner contracts and Phase 3 regressions."""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from http.server import ThreadingHTTPServer

from labops.at003 import build_plan
from labops.checkpoint_incident import collect_checkpoint_evidence, diagnose_checkpoint, diagnose_policy_violation
from labops.runner import RUNNER_IMAGE, runtime_capability_check
from labops.runner_gateway import MAX_BODY, RUN_ID, RUN_ID_AT004, TASK_CONTRACTS, make_handler


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestRunnerContracts(unittest.TestCase):
    def test_dockerfile_is_pinned_non_root_and_runtime_is_offline(self):
        dockerfile = (repo_root() / "runner" / "Dockerfile").read_text(encoding="utf-8")
        adapter = (repo_root() / "labops" / "runner.py").read_text(encoding="utf-8")
        self.assertIn("agentteams-copaw-worker@sha256:dcdd9103", dockerfile)
        self.assertIn("--requirement /tmp/requirements.lock", dockerfile)
        requirements = (repo_root() / "runner" / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("torch==2.5.1+cpu", requirements)
        self.assertTrue(all("==" in line for line in requirements.splitlines() if line.strip()))
        self.assertIn("USER runner", dockerfile)
        self.assertNotRegex(dockerfile, r"(?i)(api[_-]?key|access[_-]?token|password)\s*=")
        self.assertIn('"--network", "none"', adapter)
        self.assertIn('"--read-only"', adapter)
        self.assertIn('"--cap-drop", "ALL"', adapter)
        self.assertIn('"no-new-privileges:true"', adapter)

    def test_runtime_capability_check_covers_all_required_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            baseline = root / "run"
            project.mkdir()
            (baseline / "checkpoints").mkdir(parents=True)
            for name in ("evaluate.py", "metric.py", "model.py"):
                (project / name).write_text("# fixture", encoding="utf-8")
            for name in ("last.pt", "best.pt"):
                (baseline / "checkpoints" / name).write_bytes(b"fixture")
            (baseline / "eval_config.json").write_text(json.dumps({"checkpoint": "checkpoints/last.pt", "metric": "accuracy"}), encoding="utf-8")
            hypothesis = {"hypothesis_id": "H-1", "evidence_ids": ["E-1"]}
            plan = build_plan(hypothesis, "RUN-1")
            self.assertIn("original_workspace", plan["forbidden_changes"])
            labels = {
                "io.labops.runner.image": RUNNER_IMAGE,
                "io.labops.runner.python": "3.11.15",
                "io.labops.runner.torch": "2.5.1+cpu",
                "io.labops.runner.network-runtime": "none",
            }
            responses = [
                subprocess.CompletedProcess([], 0, json.dumps(labels), ""),
                subprocess.CompletedProcess([], 0, json.dumps({"python": "3.11.15", "torch": "2.5.1+cpu", "cuda": False}), ""),
            ]
            with mock.patch("labops.runner.docker_binary", return_value="docker"), mock.patch("labops.runner._run", side_effect=responses):
                result = runtime_capability_check(plan, project, baseline)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(set(result["checks"]), {"runner_image", "torch", "checkpoint", "config", "paths", "resource_budget", "command_allowlist", "plan_policy"})
        self.assertTrue(all(result["checks"].values()))

    def test_runner_outputs_exact_required_evidence(self):
        source = (repo_root() / "runner" / "runner.py").read_text(encoding="utf-8")
        for name in ("run_result.json", "metrics.json", "stdout.log", "stderr.log", "artifact_manifest.json"):
            self.assertIn(name, source)
        self.assertIn("COMMAND_ALLOWLIST", source)
        self.assertIn('hashes["validation_data"]', source)
        self.assertIn('protected[f"{name}_unchanged"]', source)

    def test_gateway_has_two_fixed_task_contracts_and_requires_approval(self):
        source = (repo_root() / "labops" / "runner_gateway.py").read_text(encoding="utf-8")
        self.assertEqual(MAX_BODY, 64 * 1024)
        self.assertIsNotNone(RUN_ID.fullmatch("RUN-LABOPS-AT-003-AGENTTEAMS-001"))
        self.assertIsNotNone(RUN_ID_AT004.fullmatch("RUN-LABOPS-AT-004-AGENTTEAMS-001"))
        self.assertIsNone(RUN_ID.fullmatch("RUN-ARBITRARY-001"))
        self.assertEqual(set(TASK_CONTRACTS), {"LABOPS-AT-003", "LABOPS-AT-004-EVAL-DRIFT"})
        self.assertIn('approval.get("decision") == "APPROVED"', source)
        self.assertIn("run_id already exists; evidence is append-only", source)
        self.assertIn('default="127.0.0.1"', source)
        self.assertIn('TASK_CONTRACTS.get(task_id)', source)
        self.assertNotIn("shell=True", source)

    def test_gateway_rejects_non_object_plan_with_structured_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, root / "runs"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            payload = json.dumps({"experiment_plan": "not-an-object", "approval": {}}).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/run",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(caught.exception.code, 400)
                response = json.loads(caught.exception.read())
                self.assertEqual(response["ok"], False)
                self.assertEqual(response["code"], "INVALID_SCHEMA")
                self.assertEqual(response["error"], "structured experiment_plan and approval required")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_gateway_normalizes_legacy_request_to_tool_contract(self):
        from labops.runner_gateway import normalize_tool_contract

        request = {
            "experiment_plan": {
                "task_id": "LABOPS-AT-004-EVAL-DRIFT",
                "incident_id": "DEMO-EVAL-DRIFT-004",
                "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-002",
                "runtime": {"image": "labops/pytorch-cpu-runner:0.2.0"},
                "budget": {"device": "cpu", "network": False},
                "success_criteria": {"accuracy": {"minimum": 0.97}},
            },
            "approval": {
                "approval_id": "APR-2",
                "task_id": "LABOPS-AT-004-EVAL-DRIFT",
                "decision": "APPROVED",
                "decided_by": "human-user",
                "approved_at": "2026-08-25T00:00:00Z",
            },
        }

        contract = normalize_tool_contract(request)

        self.assertEqual(contract["tool_id"], "labops.runner.execute")
        self.assertEqual(contract["caller_agent_id"], "safe-executor")
        self.assertEqual(contract["skill_id"], "control-lab-action")
        self.assertEqual(contract["approval_reference"], "APR-2")
        self.assertEqual(contract["idempotency_key"], "RUN-LABOPS-AT-004-AGENTTEAMS-002")

    def test_gateway_rejects_tool_contract_identity_binding_mismatch(self):
        from labops.runner_gateway import normalize_tool_contract

        request = {
            "experiment_plan": {
                "task_id": "LABOPS-AT-004-EVAL-DRIFT",
                "incident_id": "DEMO-EVAL-DRIFT-004",
                "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-003",
                "budget": {},
                "success_criteria": {},
            },
            "approval": {"approval_id": "APR-3"},
            "tool_contract": {"task_id": "ANOTHER-TASK"},
        }

        with self.assertRaisesRegex(ValueError, "binding"):
            normalize_tool_contract(request)


class TestIncidentIdentityRegression(unittest.TestCase):
    def test_legal_and_unsafe_cases_have_distinct_incident_and_hypotheses(self):
        demo = repo_root() / "demos" / "checkpoint-regression"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            baseline.mkdir()
            (baseline / "eval_config.json").write_text(
                json.dumps({"checkpoint": "checkpoints/last.pt", "metric": "accuracy"}),
                encoding="utf-8",
            )
            (baseline / "training_log.json").write_text(
                json.dumps({
                    "best_checkpoint": "checkpoints/best.pt",
                    "best_accuracy": 0.98125,
                    "best_state_sha256": "best-state",
                    "last_state_sha256": "last-state",
                }),
                encoding="utf-8",
            )
            (baseline / "baseline_metrics.json").write_text(
                json.dumps({"configured_accuracy": 0.70, "best_accuracy": 0.98125}),
                encoding="utf-8",
            )
            valid = collect_checkpoint_evidence(demo, baseline, root / "valid", "DEMO-RCA-003")
            unsafe = collect_checkpoint_evidence(demo, baseline, root / "unsafe", "DEMO-RCA-002")
            valid_hypotheses = diagnose_checkpoint(valid)
            unsafe_hypotheses = diagnose_policy_violation(unsafe)
        self.assertEqual(valid["incident_id"], "DEMO-RCA-003")
        self.assertEqual(unsafe["incident_id"], "DEMO-RCA-002")
        self.assertEqual(valid_hypotheses["incident_id"], "DEMO-RCA-003")
        self.assertEqual(unsafe_hypotheses["incident_id"], "DEMO-RCA-002")
        self.assertNotEqual(valid_hypotheses["hypotheses"], unsafe_hypotheses["hypotheses"])
        self.assertTrue(all(item["hypothesis_id"].startswith("H-DEMO-UNSAFE") for item in unsafe_hypotheses["hypotheses"]))

    def test_at003_does_not_reference_or_overwrite_at002(self):
        task = json.loads((repo_root() / "agentteams" / "tasks" / "LABOPS-AT-003.json").read_text(encoding="utf-8"))
        prompt = (repo_root() / "agentteams" / "prompts" / "checkpoint_runner_task.md").read_text(encoding="utf-8")
        self.assertEqual(task["task_id"], "LABOPS-AT-003")
        self.assertEqual(task["incident_ids"], ["DEMO-RCA-003"])
        self.assertIn("Do not modify or replace any LABOPS-AT-002 artifact", prompt)
        self.assertEqual(len(task["assigned_agents"]), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
