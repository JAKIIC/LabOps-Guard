"""Behavioral tests for the repository-native Skill Registry."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from labops.skill_registry import (
    KNOWN_TOOL_DEPENDENCIES,
    SkillAuthorizationError,
    SkillInputError,
    describe_skill,
    list_skills,
    validate_skill_input,
)


ROOT = Path(__file__).resolve().parents[1]


class TestSkillRegistry(unittest.TestCase):
    def test_lists_seven_registered_skills_with_resolvable_contracts(self) -> None:
        skills = list_skills(ROOT)

        self.assertEqual(len(skills), 7)
        self.assertEqual(
            {skill["skill_id"] for skill in skills},
            {
                "collect-lab-evidence",
                "diagnose-lab-incident",
                "plan-lab-experiment",
                "control-lab-action",
                "verify-lab-result",
                "pack-lab-evidence",
                "publish-case-memory",
            },
        )
        for skill in skills:
            self.assertTrue((ROOT / skill["io_schema"]).is_file())
            self.assertTrue(skill["owner_agents"])
            self.assertTrue(skill["failure_states"])
            self.assertTrue(set(skill["tool_dependencies"]).issubset(KNOWN_TOOL_DEPENDENCIES))
            io_contract = json.loads((ROOT / skill["io_schema"]).read_text(encoding="utf-8"))
            self.assertEqual(io_contract["skill_version"], skill["version"])

    def test_describe_rejects_an_unauthorized_agent(self) -> None:
        with self.assertRaises(SkillAuthorizationError):
            describe_skill("control-lab-action", ROOT, caller_agent_id="rca-analyst")

        skill = describe_skill(
            "control-lab-action", ROOT, caller_agent_id="safe-executor"
        )
        self.assertEqual(skill["policy_class"], "manual_approval")

    def test_validate_input_reports_missing_required_fields(self) -> None:
        with self.assertRaises(SkillInputError) as caught:
            validate_skill_input("control-lab-action", {"task_id": "T-1"}, ROOT)

        self.assertIn("incident_id", str(caught.exception))
        self.assertIn("approval", str(caught.exception))

    def test_malformed_registry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            (root / "skills" / "registry.json").write_text(
                json.dumps({"schema_version": "1.0", "skills": [{"skill_id": "broken"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                list_skills(root)

    def test_cli_lists_skills_as_json(self) -> None:
        from labops.cli import main

        output = StringIO()
        with redirect_stdout(output):
            result = main(["skills", "list", "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(len(payload["skills"]), 7)


if __name__ == "__main__":
    unittest.main()
