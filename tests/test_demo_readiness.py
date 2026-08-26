"""Read-only readiness checks for the real AgentTeams recording workflow."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from labops import cli, demo_readiness


ROOT = Path(__file__).resolve().parent.parent


class TestDemoReadiness(unittest.TestCase):
    def test_repository_readiness_preserves_live_replay_boundary(self):
        report = demo_readiness.build_readiness(ROOT)

        self.assertEqual(report["status"], "LOCAL_READY")
        self.assertEqual(report["mode"], "READINESS_CHECK_ONLY")
        self.assertFalse(report["executes_agentteams"])
        self.assertFalse(report["archived_replay_is_live"])
        self.assertEqual(report["live_agentteams"], "MANUAL_CHECK_REQUIRED")
        self.assertEqual(
            report["task"]["agent_order"],
            [
                "labops-manager",
                "evidence-collector",
                "rca-analyst",
                "experiment-planner",
                "safe-executor",
                "verification-auditor",
            ],
        )
        self.assertTrue(all(item["status"] == "PASS" for item in report["evidence"]))
        self.assertEqual(
            {item["task_id"] for item in report["evidence"]},
            {"LABOPS-AT-002", "LABOPS-AT-003", "LABOPS-AT-004-EVAL-DRIFT"},
        )
        self.assertEqual(report["skills"]["status"], "CONFIGURED")
        self.assertEqual(report["skills"]["registered_count"], 7)
        self.assertEqual(
            [item["skill_id"] for item in report["skills"]["expected_pipeline"]],
            [
                "collect-lab-evidence",
                "diagnose-lab-incident",
                "plan-lab-experiment",
                "control-lab-action",
                "verify-lab-result",
                "pack-lab-evidence",
                "publish-case-memory",
            ],
        )
        self.assertEqual(report["skills"]["runtime_event_emission"], "NOT_IMPLEMENTED")
        self.assertFalse(report["skills"]["historical_at004_has_skill_usage_events"])
        self.assertEqual(report["skills"]["live_visibility"], "AGENTTEAMS_HOOK_REQUIRED")
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(ROOT), serialized)

    def test_cli_can_print_the_exact_manager_prompt_without_running_agents(self):
        output = io.StringIO()
        with redirect_stdout(output):
            rc = cli.main(["demo-readiness", "--show-prompt"])

        self.assertEqual(rc, 0)
        payload = json.loads(output.getvalue())
        self.assertIn("You are `labops-manager`", payload["task"]["manager_prompt"])
        self.assertFalse(payload["executes_agentteams"])

    def test_service_checks_use_the_real_gateway_and_dashboard_service_names(self):
        with (
            patch.object(demo_readiness, "_check_docker", return_value={"status": "PASS"}),
            patch.object(demo_readiness, "_check_health", return_value={"status": "PASS"}) as health,
        ):
            report = demo_readiness.build_readiness(ROOT, service_checks=True)

        self.assertEqual(report["status"], "LOCAL_READY")
        self.assertEqual(
            [call.args[1] for call in health.call_args_list],
            ["labops-runner-gateway", "labops-guard"],
        )

    def test_health_check_rejects_non_local_urls(self):
        result = demo_readiness._check_health("https://example.invalid/healthz", "ignored")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("local HTTP", result["detail"])

    def test_final_guide_names_all_three_execution_modes_and_recording_boundaries(self):
        guide = (ROOT / "docs" / "final-demo-guide.md").read_text(encoding="utf-8")

        for phrase in (
            "A. AgentTeams live execution",
            "B. 本地确定性控制面 / 测试执行",
            "C. Archived Evidence Replay",
            "python -B -m labops demo-readiness --service-checks --show-prompt",
            "POLICY_VIOLATION / ROLLED_BACK",
            "不能描述为真实资源已被越权修改",
            "不会自动变成新一次 live run 的监控页",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
