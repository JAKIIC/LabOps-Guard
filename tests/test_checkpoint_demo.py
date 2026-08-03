"""Contract and optional runtime tests for DEMO-RCA-001."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestCheckpointDemoContract(unittest.TestCase):
    def test_demo_contract_is_offline_and_scoped(self):
        incident = json.loads((repo_root() / "demos" / "checkpoint-regression" / "incident.json").read_text(encoding="utf-8"))
        self.assertEqual(incident["incident_id"], "DEMO-RCA-001")
        self.assertFalse(incident["constraints"]["network_access"])
        self.assertEqual(incident["constraints"]["modifiable_scope"], ["eval_config.json:checkpoint"])
        self.assertIn("metric.py", incident["constraints"]["forbidden_scope"])

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch runtime is optional for core tests")
    def test_three_run_baseline_is_stable(self):
        demo_dir = repo_root() / "demos" / "checkpoint-regression"
        sys.path.insert(0, str(demo_dir))
        try:
            from run_demo import run_stability_demo
            with tempfile.TemporaryDirectory() as tmp:
                report = run_stability_demo(tmp, repeats=3)
        finally:
            sys.path.remove(str(demo_dir))
        self.assertTrue(report["passed"])
        self.assertTrue(report["stable"])

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch runtime is optional for core tests")
    def test_valid_repair_and_metric_tamper_cases(self):
        demo_dir = repo_root() / "demos" / "checkpoint-regression"
        sys.path.insert(0, str(demo_dir))
        try:
            from run_demo import run_stability_demo
            from labops.checkpoint_incident import run_incident
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                baseline_root = tmp_path / "baseline"
                run_stability_demo(baseline_root, repeats=1)
                valid = json.loads((demo_dir / "incident.json").read_text(encoding="utf-8"))
                valid["baseline_artifact"] = str(baseline_root / "run-01")
                valid_path = tmp_path / "valid.json"
                valid_path.write_text(json.dumps(valid), encoding="utf-8")
                valid_result = run_incident(valid_path, tmp_path / "valid-output")

                unsafe = json.loads((demo_dir / "incident-policy-violation.json").read_text(encoding="utf-8"))
                unsafe["baseline_artifact"] = str(baseline_root / "run-01")
                unsafe_path = tmp_path / "unsafe.json"
                unsafe_path.write_text(json.dumps(unsafe), encoding="utf-8")
                unsafe_result = run_incident(unsafe_path, tmp_path / "unsafe-output")
        finally:
            sys.path.remove(str(demo_dir))
        self.assertEqual(valid_result["decision"], "PASS")
        self.assertEqual(valid_result["state"], "RESOLVED")
        self.assertTrue(valid_result["trace_ok"])
        self.assertEqual(unsafe_result["decision"], "POLICY_VIOLATION")
        self.assertEqual(unsafe_result["state"], "ROLLED_BACK")
        self.assertTrue(unsafe_result["rollback_ok"])
        self.assertTrue(unsafe_result["trace_ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
