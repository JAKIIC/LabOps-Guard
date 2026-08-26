"""Contracts and state-boundary tests for the v0.2 workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from labops.contracts import ContractError, validate_document
from labops.trace import TraceLog
from labops.workflow import IncidentStateMachine, StateTransitionError


class TestFormalSchemas(unittest.TestCase):
    def test_incident_sample_is_valid(self):
        root = Path(__file__).resolve().parent.parent
        document = json.loads((root / "demos" / "checkpoint-regression" / "incident.json").read_text(encoding="utf-8"))
        validate_document(document, "incident.schema.json")

    def test_missing_required_field_fails(self):
        with self.assertRaises(ContractError):
            validate_document({"schema_version": "1.0"}, "incident.schema.json")

    def test_required_schemas_exist_and_are_valid_json(self):
        root = Path(__file__).resolve().parent.parent / "schemas"
        expected = {
            "incident",
            "state",
            "evidence",
            "hypothesis",
            "plan",
            "run",
            "verification",
            "trace",
            "trust_contract",
            "skill_registry",
            "skill_usage_event",
            "tool_contract",
            "trust_snapshot",
        }
        schema_paths = list(root.glob("*.schema.json"))
        self.assertTrue(expected.issubset({p.name.split(".")[0] for p in schema_paths}))
        for path in schema_paths:
            with self.subTest(schema=path.name):
                self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


class TestRoleRestrictedStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.machine = IncidentStateMachine("DEMO-RCA-001", root / "state.json", TraceLog(root / "trace.jsonl"))
        self.machine.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_evidence_collector_cannot_resolve(self):
        with self.assertRaises(StateTransitionError):
            self.machine.transition("RESOLVED", "evidence-collector")

    def test_only_verifier_can_resolve(self):
        route = [
            ("TRIAGED", "incident-commander"),
            ("EVIDENCE_COLLECTING", "incident-commander"),
            ("EVIDENCE_READY", "evidence-collector"),
            ("DIAGNOSING", "incident-commander"),
            ("HYPOTHESES_READY", "rca-analyst"),
            ("PLAN_READY", "experiment-planner"),
            ("POLICY_CHECKING", "incident-commander"),
            ("EXECUTING", "incident-commander"),
            ("VERIFYING", "safe-executor"),
            ("RESOLVED", "verification-auditor"),
        ]
        for state, actor in route:
            self.machine.transition(state, actor)
        self.assertEqual(self.machine.read()["state"], "RESOLVED")


if __name__ == "__main__":
    unittest.main(verbosity=2)

