"""Dedicated PyTorch CPU Runner contracts and Phase 3 regressions."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from labops.at003 import build_plan
from labops.checkpoint_incident import collect_checkpoint_evidence, diagnose_checkpoint, diagnose_policy_violation
from labops.runner import RUNNER_IMAGE, runtime_capability_check
from labops.runner_gateway import MAX_BODY, RUN_ID


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
        self.assertIn("validation_data_unchanged", source)

    def test_gateway_is_fixed_to_at003_and_requires_approval(self):
        source = (repo_root() / "labops" / "runner_gateway.py").read_text(encoding="utf-8")
        self.assertEqual(MAX_BODY, 64 * 1024)
        self.assertIsNotNone(RUN_ID.fullmatch("RUN-LABOPS-AT-003-AGENTTEAMS-001"))
        self.assertIsNone(RUN_ID.fullmatch("RUN-ARBITRARY-001"))
        self.assertIn('approval.get("decision") == "APPROVED"', source)
        self.assertIn("run_id already exists; evidence is append-only", source)
        self.assertIn('default="127.0.0.1"', source)
        self.assertIn('plan.get("task_id") == "LABOPS-AT-003"', source)
        self.assertNotIn("shell=True", source)


class TestIncidentIdentityRegression(unittest.TestCase):
    def test_legal_and_unsafe_cases_have_distinct_incident_and_hypotheses(self):
        demo = repo_root() / "demos" / "checkpoint-regression"
        baseline = repo_root() / "artifacts" / "DEMO-RCA-001" / "baseline" / "run-01"
        with tempfile.TemporaryDirectory() as tmp:
            valid = collect_checkpoint_evidence(demo, baseline, Path(tmp) / "valid", "DEMO-RCA-003")
            unsafe = collect_checkpoint_evidence(demo, baseline, Path(tmp) / "unsafe", "DEMO-RCA-002")
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
