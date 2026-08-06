"""Phase 5 release-readiness and messaging contracts."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ROLE_SKILLS = {
    "collect-lab-evidence",
    "control-lab-action",
    "diagnose-lab-incident",
    "pack-lab-evidence",
    "plan-lab-experiment",
    "verify-lab-result",
}


class TestPhase5Contracts(unittest.TestCase):
    def test_six_agents_remain_generic_and_commander_owns_memory_publish(self):
        payload = json.loads((ROOT / "agentteams" / "agent_identities_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["agents"]), 6)
        self.assertNotIn("checkpoint regression", payload["system"].lower())
        manager = next(item for item in payload["agents"] if item["agent_id"] == "labops-manager")
        self.assertIn("publish-case-memory", manager["skills"])

    def test_supported_skill_schemas_are_versioned_and_todo_free(self):
        self.assertFalse((ROOT / "skills" / "execute-controlled-action").exists())
        for name in ROLE_SKILLS | {"publish-case-memory"}:
            skill = ROOT / "skills" / name
            self.assertNotIn("TODO", (skill / "SKILL.md").read_text(encoding="utf-8"))
            schema = json.loads((skill / "references" / "io-schema.json").read_text(encoding="utf-8"))
            self.assertTrue(schema["schema_version"])
            self.assertTrue(schema["skill_version"])
            self.assertIn("input", schema)
            self.assertIn("output", schema)
            self.assertIn("errors", schema)

    def test_public_main_copy_uses_at004_and_no_host_absolute_paths(self):
        files = [
            ROOT / "README.md",
            ROOT / "docs" / "competition-mapping.md",
            ROOT / "docs" / "competition-submission-draft.md",
            ROOT / "submission" / "初赛提交清单.md",
            ROOT / "submission" / "现场演示脚本.md",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertIn("AT-004", text)
        self.assertIn("0.2.0", text)
        self.assertNotRegex(text, re.compile(r"[A-Za-z]:\\"))
        self.assertNotIn("OpenLabOps", text)

    def test_submission_intro_is_within_500_non_whitespace_characters(self):
        text = (ROOT / "docs" / "competition-submission-draft.md").read_text(encoding="utf-8")
        intro = text.split("## 500 字以内作品简介", 1)[1].split("## 官方模板", 1)[0]
        count = len(re.sub(r"\s+", "", intro))
        self.assertLessEqual(count, 500, count)

    def test_release_builder_includes_at004_closure_without_replacing_source(self):
        text = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn("LABOPS-AT-004-closure-v2.zip", text)
        self.assertIn("main_demo = 'LABOPS-AT-004-EVAL-DRIFT'", text)


if __name__ == "__main__":
    unittest.main()
