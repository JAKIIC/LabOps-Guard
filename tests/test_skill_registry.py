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
    validate_skill_output,
    validate_skill_usage_event,
)


ROOT = Path(__file__).resolve().parents[1]


class TestSkillRegistry(unittest.TestCase):
    def test_event_emitting_skills_define_one_atomic_completion_recipe(self) -> None:
        expected = {
            "collect-lab-evidence": ("0.2.2", "collector_to_rca"),
            "diagnose-lab-incident": ("0.2.1", "rca_to_planner"),
            "plan-lab-experiment": ("0.2.2", "approval_pending"),
            "control-lab-action": ("0.2.1", "executor_to_auditor"),
            "verify-lab-result": ("0.2.1", "verification_completed"),
            "pack-lab-evidence": ("0.2.1", "commander_published"),
        }
        registry = {item["skill_id"]: item for item in list_skills(ROOT)}

        for skill_id, (version, event_kind) in expected.items():
            with self.subTest(skill_id=skill_id):
                text = (ROOT / "skills" / skill_id / "SKILL.md").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(registry[skill_id]["version"], version)
                self.assertIn(f"Skill version: `{version}`", text)
                self.assertEqual(text.count("## Atomic AgentTeams completion"), 1)
                self.assertIn("scripts/emit_handoff.py", text)
                self.assertIn(f"`{event_kind}`", text)
                self.assertIn("`EMITTED`", text)
                self.assertIn("`ALREADY_EMITTED`", text)

    def test_evidence_incomplete_requires_a_validated_failure_artifact_first(self) -> None:
        skill_root = ROOT / "skills" / "collect-lab-evidence"
        text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        normalized_text = " ".join(text.split())
        contract = json.loads(
            (skill_root / "references" / "io-schema.json").read_text(encoding="utf-8")
        )

        self.assertIn("write and validate the assigned output artifact", normalized_text)
        self.assertIn("`handoff_state: BLOCKED`", normalized_text)
        self.assertIn("before emitting `evidence_incomplete`", normalized_text)
        self.assertEqual(contract["skill_version"], "0.2.2")
        self.assertEqual(
            contract["output"]["failure_artifact"]["required_when"],
            "handoff_state=BLOCKED",
        )
        self.assertEqual(
            set(contract["output"]["failure_artifact"]["required_fields"]),
            {
                "session_id",
                "task_instance_id",
                "incident_instance_id",
                "attempt_id",
                "run_id",
                "gaps",
                "errors",
                "excluded_data_not_read",
                "handoff_state",
            },
        )

        blocked = {
            "registry_record": {},
            "collected_evidence": [],
            "verification_status": "BLOCKED",
            "evidence_count": 0,
            "gaps_count": 1,
            "excluded_data_not_read": True,
            "handoff_state": "BLOCKED",
        }
        with self.assertRaisesRegex(SkillInputError, "failure artifact"):
            validate_skill_output(
                "collect-lab-evidence",
                blocked,
                ROOT,
                caller_agent_id="evidence-collector",
            )

        failure = {
            "session_id": "20260903-003",
            "task_instance_id": "LIVE-TASK-20260903-003",
            "incident_instance_id": "LIVE-INCIDENT-20260903-003",
            "attempt_id": "LIVE-ATTEMPT-20260903-003-01",
            "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-003",
            "gaps": ["evaluation-config-snapshot-current"],
            "errors": ["EVIDENCE_MISSING"],
            "excluded_data_not_read": True,
            "handoff_state": "BLOCKED",
        }
        result = validate_skill_output(
            "collect-lab-evidence",
            {**blocked, "failure_artifact": failure},
            ROOT,
            caller_agent_id="evidence-collector",
        )
        self.assertTrue(result["valid"])

        with self.assertRaisesRegex(SkillInputError, "handoff_state"):
            validate_skill_output(
                "collect-lab-evidence",
                {**blocked, "failure_artifact": {**failure, "handoff_state": "EVIDENCE_READY"}},
                ROOT,
                caller_agent_id="evidence-collector",
            )

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

    def test_planning_invocation_is_read_only_but_its_plan_still_requires_approval(self) -> None:
        skill = describe_skill("plan-lab-experiment", ROOT, caller_agent_id="experiment-planner")
        self.assertEqual(skill["policy_class"], "read_only_auto")
        result = validate_skill_input(
            "plan-lab-experiment",
            {"hypothesis_id": "H-1", "evidence_ids": ["E-1"], "claim": "bounded claim"},
            ROOT,
            caller_agent_id="experiment-planner",
        )
        self.assertTrue(result["valid"])

    def test_validate_output_enforces_the_registered_output_contract(self) -> None:
        with self.assertRaises(SkillInputError) as caught:
            validate_skill_output(
                "control-lab-action",
                {"effective_policy_class": "manual_approval"},
                ROOT,
                caller_agent_id="safe-executor",
            )
        self.assertIn("execution_status", str(caught.exception))

        result = validate_skill_output(
            "control-lab-action",
            {
                "effective_policy_class": "manual_approval",
                "approval_status": "APPROVED",
                "dry_run": {},
                "execution_status": "completed",
                "simulated": False,
                "handoff_state": "VERIFYING",
            },
            ROOT,
            caller_agent_id="safe-executor",
        )
        self.assertEqual(result, {"valid": True, "skill_id": "control-lab-action", "version": "0.2.1"})

    def test_usage_event_must_bind_real_registry_identity_version_and_artifacts(self) -> None:
        event = {
            "schema_version": "1.0",
            "run_mode": "LIVE_AGENTTEAMS",
            "event_id": "$new-live-matrix-event",
            "task_id": "LABOPS-AT-004-EVAL-DRIFT-RECORDING",
            "incident_id": "DEMO-EVAL-DRIFT-RECORDING",
            "skill_id": "control-lab-action",
            "skill_version": "0.2.1",
            "owner_agent": "safe-executor",
            "input_schema_version": "1.0",
            "output_schema_version": "1.0",
            "started_at": "2026-08-26T10:00:00Z",
            "completed_at": "2026-08-26T10:00:08Z",
            "status": "COMPLETED",
            "input_artifact_refs": [
                {"path": "shared/tasks/recording/plan.json", "sha256": "a" * 64}
            ],
            "output_artifact_refs": [
                {"path": "shared/tasks/recording/run_result.json", "sha256": "b" * 64}
            ],
            "trace_reference": {"source": "matrix", "event_id": "$new-live-matrix-event"},
        }
        result = validate_skill_usage_event(event, ROOT)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["skill_id"], "control-lab-action")

        wrong_owner = dict(event, owner_agent="rca-analyst")
        with self.assertRaises(SkillAuthorizationError):
            validate_skill_usage_event(wrong_owner, ROOT)

        missing_output = dict(event, output_artifact_refs=[])
        with self.assertRaises(SkillInputError):
            validate_skill_usage_event(missing_output, ROOT)

        invalid_artifact = dict(
            event,
            output_artifact_refs=[{"path": "C:\\private\\result.json", "sha256": "not-a-hash"}],
        )
        with self.assertRaises(SkillInputError):
            validate_skill_usage_event(invalid_artifact, ROOT)

        invalid_time = dict(event, completed_at="not-a-timestamp")
        with self.assertRaises(SkillInputError):
            validate_skill_usage_event(invalid_time, ROOT)

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
