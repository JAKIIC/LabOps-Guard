"""Contract tests for the AgentTeams and Skill integration."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from labops import demo as demo_mod


ROOT = Path(__file__).resolve().parent.parent
SKILLS = [
    "collect-lab-evidence",
    "diagnose-lab-incident",
    "control-lab-action",
    "verify-lab-result",
    "pack-lab-evidence",
]


class TestAgentIdentities(unittest.TestCase):
    def setUp(self):
        self.identities = json.loads((ROOT / "agentteams" / "agent_identities.json").read_text(encoding="utf-8"))
        self.task = json.loads((ROOT / "agentteams" / "tasks" / "LABOPS-AT-001.json").read_text(encoding="utf-8"))

    def test_distinct_agents_have_boundaries(self):
        agents = self.identities["agents"]
        self.assertGreaterEqual(len(agents), 3)
        ids = [a["agent_id"] for a in agents]
        self.assertEqual(len(ids), len(set(ids)))
        for agent in agents:
            for key in ("mission", "inputs", "outputs", "skills", "permissions", "forbidden", "handoff_condition"):
                self.assertTrue(agent[key], f"{agent['agent_id']} missing {key}")

    def test_task_references_real_agents_and_skills(self):
        agent_ids = {a["agent_id"] for a in self.identities["agents"]}
        self.assertEqual(set(self.task["assigned_agents"]), agent_ids)
        self.assertEqual(set(self.task["required_skills"]), set(SKILLS))
        self.assertIn("never_read", self.task["risk_policy"].values())
        self.assertIn("Only real non-simulated", self.task["close_rule"])

    def test_state_machine_has_safe_closure(self):
        machine = json.loads((ROOT / "agentteams" / "state_machine.json").read_text(encoding="utf-8"))
        close = [t for t in machine["transitions"] if t["to"] == "CLOSED"]
        self.assertEqual(len(close), 1)
        self.assertIn("real_action=true", close[0]["requires"])
        self.assertIn("postcondition=true", close[0]["requires"])


class TestSkillPackages(unittest.TestCase):
    def test_skills_are_complete_and_named(self):
        for name in SKILLS:
            path = ROOT / "skills" / name / "SKILL.md"
            self.assertTrue(path.exists(), name)
            text = path.read_text(encoding="utf-8")
            match = re.match(r"---\s*\nname:\s*([^\n]+)\n", text)
            self.assertIsNotNone(match, name)
            self.assertEqual(match.group(1).strip(), name)
            self.assertNotIn("TODO", text)
            schema = ROOT / "skills" / name / "references" / "io-schema.json"
            payload = json.loads(schema.read_text(encoding="utf-8"))
            self.assertIn("input", payload)
            self.assertIn("output", payload)

    def test_evidence_packer_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "output"
            rc = demo_mod.run_demo(
                workspace=workspace,
                snapshot_dir=ROOT / "demo" / "fixtures" / "project_snapshot_lite",
                audit_dir=ROOT / "demo" / "fixtures" / "audit",
                verification_json=ROOT / "demo" / "fixtures" / "snapshot_verification.json",
                allowed_list=ROOT / "demo" / "allowed_files.json",
            )
            self.assertEqual(rc, 0)
            output = workspace / "evidence_bundle.zip"
            script = ROOT / "skills" / "pack-lab-evidence" / "scripts" / "build_bundle.py"
            result = subprocess.run(
                [sys.executable, "-B", str(script), "--workspace", str(workspace), "--output", str(output)],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["underlying_issue_resolved"])
            with zipfile.ZipFile(output) as bundle:
                names = set(bundle.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("trace.jsonl", names)
            self.assertFalse(any("fixtures" in name or name.endswith(".csv") for name in names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
