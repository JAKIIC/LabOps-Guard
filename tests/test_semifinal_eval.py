from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from labops.contracts import validate_document
from labops.evaluation import evaluate_case, evaluate_inputs, run_trust_evaluation_suite


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "evaluation" / "cases" / "inputs"
ORACLES = ROOT / "evaluation" / "cases" / "oracles"


class TestTrustEvaluationSuite(unittest.TestCase):
    def test_suite_has_ten_separated_governance_cases(self) -> None:
        inputs = sorted(INPUTS.glob("*.json"))
        oracles = sorted(ORACLES.glob("*.json"))
        self.assertEqual(10, len(inputs))
        self.assertEqual([path.name for path in inputs], [path.name for path in oracles])

        input_ids = set()
        for path in inputs:
            document = json.loads(path.read_text(encoding="utf-8"))
            validate_document(document, "evaluation_case.schema.json", ROOT)
            self.assertNotIn("expected_decision", document)
            self.assertNotIn("expected_terminal_state", document)
            input_ids.add(document["case_id"])

        oracle_ids = set()
        for path in oracles:
            document = json.loads(path.read_text(encoding="utf-8"))
            oracle_ids.add(document["case_id"])
        self.assertEqual(input_ids, oracle_ids)

    def test_suite_focuses_on_four_governance_outcomes(self) -> None:
        report = run_trust_evaluation_suite(INPUTS, ORACLES, ROOT)
        self.assertEqual("Trust Evaluation Suite", report["suite_name"])
        self.assertNotIn("benchmark", report["suite_name"].lower())
        self.assertEqual(
            [
                "Policy violation prevention",
                "Evidence completeness",
                "False resolution prevention",
                "Independent audit",
            ],
            report["focus_areas"],
        )
        self.assertEqual(10, report["case_count"])
        self.assertEqual("PASS", report["status"])
        validate_document(report, "evaluation_report.schema.json", ROOT)

    def test_predictions_match_sealed_oracles_without_false_resolution(self) -> None:
        predictions = evaluate_inputs(INPUTS, ROOT)
        report = run_trust_evaluation_suite(INPUTS, ORACLES, ROOT)
        oracles = {
            json.loads(path.read_text(encoding="utf-8"))["case_id"]: json.loads(
                path.read_text(encoding="utf-8")
            )
            for path in ORACLES.glob("*.json")
        }

        self.assertEqual(set(oracles), {item["case_id"] for item in predictions})
        for item in predictions:
            oracle = oracles[item["case_id"]]
            self.assertEqual(oracle["expected_decision"], item["decision"])
            self.assertEqual(oracle["expected_terminal_state"], item["terminal_state"])
            self.assertEqual(oracle["evidence_complete"], item["evidence_complete"])
            self.assertEqual(oracle["independent_audit_valid"], item["independent_audit_valid"])

        metrics = report["metrics"]
        self.assertEqual(1.0, metrics["policy_violation_prevention_rate"]["value"])
        self.assertEqual(1.0, metrics["evidence_completeness_rate"]["value"])
        self.assertEqual(0.0, metrics["false_resolution_rate"]["value"])
        self.assertEqual(1.0, metrics["independent_audit_accuracy"]["value"])

    def test_policy_evidence_and_audit_failures_are_fail_closed(self) -> None:
        predictions = {item["case_id"]: item for item in evaluate_inputs(INPUTS, ROOT)}

        metric_change = predictions["TES-005-PROTECTED-METRIC"]
        self.assertEqual("POLICY_VIOLATION", metric_change["decision"])
        self.assertEqual("ROLLED_BACK", metric_change["terminal_state"])
        self.assertTrue(metric_change["policy_violation_prevented"])

        missing_evidence = predictions["TES-003-MISSING-EVIDENCE"]
        self.assertEqual("BLOCKED", missing_evidence["terminal_state"])
        self.assertFalse(missing_evidence["evidence_complete"])

        self_audit = predictions["TES-010-SELF-AUDIT"]
        self.assertEqual("BLOCKED", self_audit["terminal_state"])
        self.assertFalse(self_audit["independent_audit_valid"])

    def test_policy_violation_without_independent_audit_stays_blocked(self) -> None:
        case = json.loads(
            (INPUTS / "TES-005-PROTECTED-METRIC.json").read_text(encoding="utf-8")
        )
        case["audit"]["agent_id"] = "safe-executor"
        case["audit"]["independent"] = False

        result = evaluate_case(case, ROOT)

        self.assertEqual("BLOCKED", result["decision"])
        self.assertEqual("BLOCKED", result["terminal_state"])
        self.assertFalse(result["independent_audit_valid"])

    def test_report_generation_is_deterministic(self) -> None:
        first = run_trust_evaluation_suite(INPUTS, ORACLES, ROOT)
        second = run_trust_evaluation_suite(INPUTS, ORACLES, ROOT)
        self.assertEqual(first, second)

    def test_script_writes_json_and_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "result.json"
            report = Path(temp_dir) / "report.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_semifinal_eval.py"),
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("PASS", json.loads(output.read_text(encoding="utf-8"))["status"])
            markdown = report.read_text(encoding="utf-8")
            self.assertIn("# Trust Evaluation Suite v1.0", markdown)
            self.assertNotIn("Benchmark", markdown)
            self.assertIn("False Resolution Rate", markdown)


if __name__ == "__main__":
    unittest.main()
