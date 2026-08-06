"""Phase 4B evaluation-drift contracts and evidence reasoning tests."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from labops.at004 import (
    INCIDENT_ID,
    TASK_ID,
    build_plan,
    collect_eval_drift_evidence,
    diagnose_eval_drift,
    verify_run,
)
from labops.planner import check_plan_policy
from labops.runner import AT004_RUNNER_IMAGE, COMMAND_PROJECT_FILES


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestAt004EvidenceAndRca(unittest.TestCase):
    def setUp(self):
        self.demo = repo_root() / "demos" / "eval-drift"
        self.fixture = self.demo / "fixture" / "run-01"

    def test_fixture_metrics_are_real_and_not_embedded_in_evaluator(self):
        record = json.loads((self.fixture / "historical_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(record["current_accuracy_values"], [0.71875] * 3)
        self.assertEqual(len(record["historical_accuracy_values"]), 3)
        self.assertTrue(all(abs(value - 0.978125) < 0.00001 for value in record["historical_accuracy_values"]))
        evaluator = (self.demo / "evaluate.py").read_text(encoding="utf-8")
        runner = (repo_root() / "runner" / "runner.py").read_text(encoding="utf-8")
        for value in ("0.71875", "0.978125"):
            self.assertNotIn(value, evaluator)
            self.assertNotIn(value, runner)

    def test_collector_emits_ten_hashed_facts_without_diagnosing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = collect_eval_drift_evidence(self.demo, self.fixture, Path(tmp))
        self.assertEqual(bundle["task_id"], TASK_ID)
        self.assertEqual(bundle["incident_id"], INCIDENT_ID)
        self.assertEqual(len(bundle["evidence"]), 10)
        self.assertTrue(all(item["content_hash"] for item in bundle["evidence"]))
        self.assertFalse(bundle["original_workspace_modified"])
        self.assertNotIn("root_cause", bundle)

    def test_rca_ranks_drift_first_and_records_contradicting_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = collect_eval_drift_evidence(self.demo, self.fixture, Path(tmp))
        diagnosis = diagnose_eval_drift(bundle)
        self.assertEqual(diagnosis["top_hypothesis_id"], "H-AT004-PREPROCESSING-DRIFT")
        by_id = {item["hypothesis_id"]: item for item in diagnosis["hypotheses"]}
        self.assertEqual(by_id["H-AT004-CHECKPOINT"]["contradicting_evidence"], ["E-AT004-001"])
        self.assertEqual(by_id["H-AT004-VALIDATION-DATA"]["contradicting_evidence"], ["E-AT004-002"])
        self.assertIn("E-AT004-007", by_id["H-AT004-RANDOMNESS"]["contradicting_evidence"])

    def test_ranking_changes_when_profile_matches_and_repeats_are_unstable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = collect_eval_drift_evidence(self.demo, self.fixture, Path(tmp))
        altered = copy.deepcopy(bundle)
        for item in altered["evidence"]:
            if item["fact"] == "current_preprocessing_profile":
                item["observation"] = "Current evaluation preprocessing profile is eval_standard."
            elif item["fact"] == "baseline_repeat_results":
                item["observation"] = "Three current evaluations differ; repeat spread is 0.020000."
        diagnosis = diagnose_eval_drift(altered)
        self.assertNotEqual(diagnosis["top_hypothesis_id"], "H-AT004-PREPROCESSING-DRIFT")


class TestAt004PlanAndVerification(unittest.TestCase):
    def setUp(self):
        self.hypothesis = {"hypothesis_id": "H-AT004-PREPROCESSING-DRIFT", "evidence_ids": ["E-AT004-004"]}

    def test_plan_is_single_variable_offline_and_policy_approved(self):
        plan = build_plan(self.hypothesis, "RUN-LABOPS-AT-004-LOCAL-01")
        self.assertEqual(plan["runtime"]["image"], AT004_RUNNER_IMAGE)
        self.assertEqual(plan["changes"], [{
            "file": "eval_config.json",
            "field": "evaluation.preprocessing_profile",
            "before": "train_augmented",
            "after": "eval_standard",
        }])
        self.assertFalse(plan["budget"]["network"])
        self.assertTrue(plan["approval_required"])
        self.assertEqual(check_plan_policy(plan)["decision"], "AUTO_APPROVED")

    def test_illegal_metric_or_checkpoint_change_is_rejected(self):
        plan = build_plan(self.hypothesis, "RUN-LABOPS-AT-004-LOCAL-01")
        for illegal in (
            {"file": "metric.py", "field": "accuracy", "before": "real", "after": "1.0"},
            {"file": "eval_config.json", "field": "checkpoint", "before": "reference.pt", "after": "other.pt"},
        ):
            candidate = copy.deepcopy(plan)
            candidate["changes"] = [illegal]
            self.assertEqual(check_plan_policy(candidate)["decision"], "REJECTED")

    def test_auditor_requires_metrics_hashes_approval_and_single_change(self):
        plan = build_plan(self.hypothesis, "RUN-LABOPS-AT-004-LOCAL-01")
        checks = {
            "runner_image": True, "python": True, "torch": True, "checkpoint": True,
            "config": True, "paths": True, "resource_budget": True,
            "command_allowlist": True, "single_approved_change": True, "no_credentials": True,
        }
        host_checks = {key: True for key in (
            "runner_image", "torch", "checkpoint", "config", "paths",
            "resource_budget", "command_allowlist", "plan_policy",
        )}
        result = {
            "run_id": plan["run_id"], "status": "completed", "return_code": 0,
            "start_time": "2026-08-05T02:00:01Z", "network": "none",
            "sandbox_only": True, "original_project_modified": False,
            "changed_paths": ["sandbox/eval_config.json:evaluation.preprocessing_profile"],
            "capability_check": {"status": "PASS", "checks": checks},
            "host_capability_check": {"status": "PASS", "checks": host_checks},
            "metrics": {
                "baseline_accuracy_values": [0.71875] * 3,
                "candidate_accuracy_values": [0.9781249761581421] * 3,
                "baseline_accuracy": 0.71875,
                "candidate_accuracy": 0.9781249761581421,
                "baseline_spread": 0.0,
                "candidate_spread": 0.0,
                "reproducible": True,
            },
            "protected_hashes": {
                "metric_unchanged": True,
                "validation_data_unchanged": True,
                "checkpoint_unchanged": True,
                "evaluation_protocol_unchanged": True,
            },
        }
        approval = {"decision": "APPROVED", "approved_at": "2026-08-05T02:00:00Z"}
        report = verify_run(result, approval)
        self.assertEqual(report["decision"], "PASS")
        result["protected_hashes"]["metric_unchanged"] = False
        self.assertEqual(verify_run(result, approval)["decision"], "INCONCLUSIVE")

    def test_v2_runner_contract_has_only_the_required_project_files(self):
        self.assertEqual(
            COMMAND_PROJECT_FILES["evaluate_preprocessing_profile"],
            ("evaluate.py", "metric.py", "model.py", "preprocessing.py", "evaluation_protocol.yaml"),
        )
        dockerfile = (repo_root() / "runner" / "Dockerfile.at004").read_text(encoding="utf-8")
        self.assertIn('io.labops.runner.image="labops/pytorch-cpu-runner:0.2.0"', dockerfile)
        self.assertIn("USER runner", dockerfile)
        self.assertNotRegex(dockerfile, r"(?i)(api[_-]?key|access[_-]?token|password)\s*=")


if __name__ == "__main__":
    unittest.main(verbosity=2)
