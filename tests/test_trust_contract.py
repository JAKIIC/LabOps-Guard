"""Cross-layer Trust Contract and snapshot tests."""

from __future__ import annotations

import json
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from labops.trust import build_trust_snapshot, validate_trust_contract


ROOT = Path(__file__).resolve().parents[1]
AT004 = ROOT / "demo" / "output-agentteams-at004"
AT002 = ROOT / "demo" / "output-agentteams-at002"


class TestTrustContract(unittest.TestCase):
    def test_package_metadata_uses_the_public_positioning(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            metadata["project"]["description"],
            "Trust Infrastructure for Production Agent Systems",
        )

    def test_contract_cross_references_are_consistent(self) -> None:
        self.assertEqual(validate_trust_contract(ROOT), [])

        task = json.loads(
            (ROOT / "agentteams" / "tasks" / "LABOPS-AT-004-EVAL-DRIFT.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            task["assigned_agents"],
            [
                "labops-manager",
                "evidence-collector",
                "rca-analyst",
                "experiment-planner",
                "safe-executor",
                "verification-auditor",
            ],
        )

    def test_snapshot_is_deterministic_and_contains_six_trust_domains(self) -> None:
        first = build_trust_snapshot(ROOT, AT004, AT002)
        second = build_trust_snapshot(ROOT, AT004, AT002)

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "1.0")
        self.assertEqual(
            first["positioning"],
            "Trust Infrastructure for Production Agent Systems",
        )
        self.assertEqual(
            set(first["domains"]),
            {"identity", "skills", "policy", "execution", "evidence", "audit"},
        )
        self.assertEqual(first["domains"]["identity"]["status"], "CONFIGURED")
        self.assertEqual(first["domains"]["execution"]["status"], "VERIFIED")
        self.assertEqual(first["domains"]["evidence"]["status"], "VERIFIED")
        self.assertEqual(first["domains"]["audit"]["status"], "VERIFIED")
        self.assertNotIn(str(ROOT), json.dumps(first, ensure_ascii=False))

    def test_missing_evidence_fails_closed(self) -> None:
        snapshot = build_trust_snapshot(ROOT, ROOT / "missing-at004", AT002)

        self.assertEqual(snapshot["domains"]["execution"]["status"], "BLOCKED")
        self.assertEqual(snapshot["domains"]["evidence"]["status"], "BLOCKED")
        self.assertEqual(snapshot["domains"]["audit"]["status"], "BLOCKED")

    def test_cli_emits_the_archived_trust_snapshot(self) -> None:
        from labops.cli import main

        output = StringIO()
        with redirect_stdout(output):
            result = main(["trust", "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["contract_status"], "CONFIGURED")
        self.assertEqual(payload["domains"]["audit"]["status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
