"""Behavioral tests for deploying the seven existing Skills into AgentTeams."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from labops import agentteams_skill_deployment as deployment
from labops import cli


ROOT = Path(__file__).resolve().parents[1]


class InMemoryAgentTeamsRuntime:
    def __init__(self, *, image_version: str = "v1.1.2", running: bool = True) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.skills: dict[str, set[str]] = {}
        self.image_version = image_version
        self.running = running

    def inspect_container(self, container_name: str) -> dict:
        return {
            "running": self.running,
            "image": f"example.invalid/hiclaw:{self.image_version}",
            "image_id": "sha256:" + "1" * 64,
        }

    def path_exists(self, container_name: str, path: str) -> bool:
        prefix = (container_name, path.rstrip("/") + "/")
        return any(
            current_container == prefix[0] and current_path.startswith(prefix[1])
            for current_container, current_path in self.files
        )

    def read_binding(self, container_name: str, skill_path: str) -> dict | None:
        raw = self.files.get(
            (container_name, skill_path.rstrip("/") + "/LABOPS_RUNTIME_BINDING.json")
        )
        return json.loads(raw) if raw is not None else None

    def copy_skill(self, source: Path, container_name: str, skills_root: str) -> None:
        destination = skills_root.rstrip("/") + "/" + source.name
        for path in source.rglob("*"):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                self.files[(container_name, destination + "/" + relative)] = path.read_bytes()
        self.skills.setdefault(container_name, set()).add(source.name)

    def file_sha256(self, container_name: str, path: str) -> str | None:
        raw = self.files.get((container_name, path))
        return hashlib.sha256(raw).hexdigest() if raw is not None else None

    def list_skill_names(self, container_name: str) -> set[str]:
        return set(self.skills.get(container_name, set()))


class AgentTeamsSkillDeploymentCLITests(unittest.TestCase):
    def test_plan_maps_all_seven_skills_to_six_runtime_identities(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "labops", "agentteams-skills", "plan"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["skill_count"], 7)
        self.assertEqual(payload["runtime_identity_count"], 6)
        self.assertEqual(
            {item["runtime_agent_id"] for item in payload["deployments"]},
            {
                "labops-manager",
                "evidence-collector",
                "rca-analyst",
                "researcher",
                "controlled-executor",
                "verification-auditor",
            },
        )

    def test_stage_copies_contracts_and_writes_deterministic_version_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            first = Path(first_tmp) / "stage"
            second = Path(second_tmp) / "stage"
            first_report = deployment.stage_skill_deployment(ROOT, first)
            second_report = deployment.stage_skill_deployment(ROOT, second)

            first_files = {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second).as_posix(): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }

        self.assertEqual(first_report["status"], "STAGED")
        self.assertEqual(first_report["skill_count"], 7)
        self.assertEqual(first_report, second_report)
        self.assertEqual(first_files, second_files)
        binding = json.loads(
            first_files[
                "controlled-executor/control-lab-action/LABOPS_RUNTIME_BINDING.json"
            ].decode("utf-8")
        )
        self.assertEqual(binding["skill_version"], "0.2.0")
        self.assertEqual(binding["canonical_owner_agent"], "safe-executor")
        self.assertEqual(binding["runtime_agent_id"], "controlled-executor")
        self.assertEqual(len(binding["skill_sha256"]), 64)
        self.assertIn(
            "controlled-executor/control-lab-action/references/io-schema.json",
            first_files,
        )

    def test_deploy_requires_an_explicit_pinned_version_confirmation(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "labops", "agentteams-skills", "deploy"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.lstrip().startswith("{"), result.stderr)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["error_code"], "VERSION_CONFIRMATION_REQUIRED")

    def test_deploy_verifies_runtime_discovery_without_claiming_invocation(self) -> None:
        runtime = InMemoryAgentTeamsRuntime()

        report = deployment.deploy_skill_packages(
            ROOT,
            confirm_version="v1.1.2",
            runtime=runtime,
        )

        self.assertEqual(report["status"], "DEPLOYED")
        self.assertEqual(report["skill_count"], 7)
        self.assertEqual(report["runtime_event_emission"], "NOT_IMPLEMENTED")
        for item in report["skills"]:
            self.assertEqual(item["discovery"], "VERIFIED")
            self.assertEqual(item["binding"], "VERIFIED")
            self.assertEqual(item["invocation"], "UNVERIFIED")

    def test_verify_is_read_only_and_fails_closed_until_skills_are_deployed(self) -> None:
        runtime = InMemoryAgentTeamsRuntime()

        with self.assertRaises(deployment.AgentTeamsSkillDeploymentError):
            deployment.verify_skill_packages(ROOT, runtime=runtime)
        self.assertEqual(runtime.files, {})

        deployment.deploy_skill_packages(
            ROOT,
            confirm_version="v1.1.2",
            runtime=runtime,
        )
        before = dict(runtime.files)
        report = deployment.verify_skill_packages(ROOT, runtime=runtime)

        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(report["skill_count"], 7)
        self.assertEqual(runtime.files, before)
        self.assertTrue(all(item["invocation"] == "UNVERIFIED" for item in report["skills"]))

    def test_deploy_fails_before_copying_when_any_runtime_binding_conflicts(self) -> None:
        runtime = InMemoryAgentTeamsRuntime()
        controlled_executor = next(
            item
            for item in deployment.build_deployment_plan(ROOT)["deployments"]
            if item["runtime_agent_id"] == "controlled-executor"
        )
        conflicting_path = (
            controlled_executor["skills_root"].rstrip("/")
            + "/control-lab-action/LABOPS_RUNTIME_BINDING.json"
        )
        runtime.files[("hiclaw-worker-controlled-executor", conflicting_path)] = b"{}"
        before = dict(runtime.files)

        with self.assertRaisesRegex(
            deployment.AgentTeamsSkillDeploymentError,
            "Runtime Skill conflict",
        ):
            deployment.deploy_skill_packages(
                ROOT,
                confirm_version="v1.1.2",
                runtime=runtime,
            )

        self.assertEqual(runtime.files, before)

    def test_deploy_rejects_stopped_or_wrong_version_containers(self) -> None:
        for runtime in (
            InMemoryAgentTeamsRuntime(running=False),
            InMemoryAgentTeamsRuntime(image_version="v1.1.3"),
        ):
            with self.subTest(runtime=runtime):
                with self.assertRaises(deployment.AgentTeamsSkillDeploymentError):
                    deployment.deploy_skill_packages(
                        ROOT,
                        confirm_version="v1.1.2",
                        runtime=runtime,
                    )
                self.assertEqual(runtime.files, {})

    def test_verify_cli_emits_the_read_only_runtime_report(self) -> None:
        expected = {
            "schema_version": "1.0",
            "status": "VERIFIED",
            "skill_count": 7,
            "runtime_event_emission": "NOT_IMPLEMENTED",
        }
        output = StringIO()
        with patch.object(deployment, "verify_skill_packages", return_value=expected):
            with redirect_stdout(output):
                rc = cli.main(["agentteams-skills", "verify"])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)

    def test_docker_runtime_decodes_openclaw_json_as_utf8_on_windows(self) -> None:
        def fake_run(args, **kwargs):
            if kwargs.get("encoding") != "utf-8":
                raise UnicodeDecodeError("gbk", b"\x94", 0, 1, "illegal multibyte sequence")
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {"skills": [{"name": "control-lab-action", "description": "受控执行"}]},
                    ensure_ascii=False,
                ),
                stderr="",
            )

        with patch(
            "labops.agentteams_skill_deployment.subprocess.run",
            side_effect=fake_run,
        ):
            names = deployment.DockerSkillRuntime().list_skill_names("hiclaw-worker")

        self.assertEqual(names, {"control-lab-action"})


if __name__ == "__main__":
    unittest.main()
