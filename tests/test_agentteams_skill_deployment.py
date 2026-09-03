"""Behavioral tests for deploying the seven existing Skills into AgentTeams."""

from __future__ import annotations

import json
import hashlib
import os
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
ROOMS_BY_ROLE = {
    "labops-manager": "!manager:matrix.test",
    "evidence-collector": "!collector:matrix.test",
    "rca-analyst": "!rca:matrix.test",
    "experiment-planner": "!planner:matrix.test",
    "safe-executor": "!executor:matrix.test",
    "verification-auditor": "!auditor:matrix.test",
}
MANAGER_USER = "@manager:matrix.test"


def write_room_map(directory: Path) -> Path:
    path = directory / "reviewer-room-map.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "rooms": {room_id: role for role, room_id in ROOMS_BY_ROLE.items()},
            }
        ),
        encoding="utf-8",
    )
    return path


class InMemoryAgentTeamsRuntime:
    def __init__(
        self,
        *,
        image_version: str = "v1.1.2",
        running: bool = True,
        dry_run_ok: bool = True,
    ) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.skills: dict[str, set[str]] = {}
        self.backups: list[dict[tuple[str, str], bytes]] = []
        self.image_version = image_version
        self.running = running
        self.dry_run_ok = dry_run_ok
        self.dry_runs: list[tuple[str, str]] = []

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
        return self.read_json(
            container_name,
            skill_path.rstrip("/") + "/LABOPS_RUNTIME_BINDING.json",
        )

    def read_json(self, container_name: str, path: str) -> dict | None:
        raw = self.files.get((container_name, path))
        return json.loads(raw) if raw is not None else None

    def copy_skill(self, source: Path, container_name: str, skills_root: str) -> None:
        destination = skills_root.rstrip("/") + "/" + source.name
        for path in source.rglob("*"):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                self.files[(container_name, destination + "/" + relative)] = path.read_bytes()
        self.skills.setdefault(container_name, set()).add(source.name)

    def replace_skill(self, source: Path, container_name: str, destination: str) -> str:
        prefix = destination.rstrip("/") + "/"
        snapshot = {
            key: value
            for key, value in self.files.items()
            if key[0] == container_name and key[1].startswith(prefix)
        }
        self.backups.append(snapshot)
        self.files = {
            key: value
            for key, value in self.files.items()
            if not (key[0] == container_name and key[1].startswith(prefix))
        }
        self.copy_skill(source, container_name, destination.rsplit("/", 1)[0])
        return destination + ".labops-backup-test"

    def file_sha256(self, container_name: str, path: str) -> str | None:
        raw = self.files.get((container_name, path))
        return hashlib.sha256(raw).hexdigest() if raw is not None else None

    def list_skill_names(self, container_name: str) -> set[str]:
        return set(self.skills.get(container_name, set()))

    def dry_run_emitter(self, container_name: str, skill_path: str) -> bool:
        self.dry_runs.append((container_name, skill_path))
        return self.dry_run_ok


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
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp, tempfile.TemporaryDirectory() as config_tmp:
            first = Path(first_tmp) / "stage"
            second = Path(second_tmp) / "stage"
            room_map = write_room_map(Path(config_tmp))
            first_report = deployment.stage_skill_deployment(
                ROOT, first, room_map_path=room_map
            )
            second_report = deployment.stage_skill_deployment(
                ROOT, second, room_map_path=room_map
            )

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
        self.assertEqual(binding["skill_version"], "0.2.1")
        self.assertEqual(binding["canonical_owner_agent"], "safe-executor")
        self.assertEqual(binding["runtime_agent_id"], "controlled-executor")
        self.assertEqual(binding["runtime_event_emission"], "VERIFIED")
        self.assertEqual(len(binding["skill_sha256"]), 64)
        self.assertEqual(len(binding["handoff_emitter_sha256"]), 64)
        self.assertIn(
            "controlled-executor/control-lab-action/references/io-schema.json",
            first_files,
        )
        emitter_path = "controlled-executor/control-lab-action/scripts/emit_handoff.py"
        self.assertIn(emitter_path, first_files)
        self.assertEqual(
            hashlib.sha256(first_files[emitter_path]).hexdigest(),
            binding["handoff_emitter_sha256"],
        )
        collector_runtime = json.loads(
            first_files[
                "evidence-collector/collect-lab-evidence/LABOPS_HANDOFF_RUNTIME.json"
            ].decode("utf-8")
        )
        collector_binding = json.loads(
            first_files[
                "evidence-collector/collect-lab-evidence/LABOPS_RUNTIME_BINDING.json"
            ].decode("utf-8")
        )
        self.assertEqual(collector_binding["skill_version"], "0.2.2")
        self.assertEqual(
            collector_runtime["events"]["collector_to_rca"]["room_id"],
            ROOMS_BY_ROLE["evidence-collector"],
        )
        self.assertEqual(
            collector_runtime["events"]["collector_to_rca"]["recipient_matrix_id"],
            MANAGER_USER,
        )
        manager_runtime = json.loads(
            first_files[
                "labops-manager/pack-lab-evidence/LABOPS_HANDOFF_RUNTIME.json"
            ].decode("utf-8")
        )
        self.assertEqual(
            manager_runtime["events"]["manager_to_collector"]["room_id"],
            ROOMS_BY_ROLE["evidence-collector"],
        )
        self.assertEqual(
            manager_runtime["events"]["manager_to_collector"]["recipient_matrix_id"],
            "@evidence-collector:matrix.test",
        )
        self.assertNotIn("token", json.dumps(manager_runtime).lower())

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
        with tempfile.TemporaryDirectory() as tmp:
            report = deployment.deploy_skill_packages(
                ROOT,
                confirm_version="v1.1.2",
                room_map_path=write_room_map(Path(tmp)),
                runtime=runtime,
            )

        self.assertEqual(report["status"], "DEPLOYED")
        self.assertEqual(report["skill_count"], 7)
        self.assertEqual(report["runtime_event_emission"], "VERIFIED")
        for item in report["skills"]:
            self.assertEqual(item["discovery"], "VERIFIED")
            self.assertEqual(item["binding"], "VERIFIED")
            self.assertEqual(item["event_emitter"], "VERIFIED")
            self.assertEqual(item["emitter_dry_run"], "VERIFIED")
            self.assertEqual(item["invocation"], "UNVERIFIED")
        self.assertEqual(len(runtime.dry_runs), 7)

    def test_verify_is_read_only_and_fails_closed_until_skills_are_deployed(self) -> None:
        runtime = InMemoryAgentTeamsRuntime()
        with tempfile.TemporaryDirectory() as tmp:
            room_map = write_room_map(Path(tmp))
            with self.assertRaises(deployment.AgentTeamsSkillDeploymentError):
                deployment.verify_skill_packages(
                    ROOT, room_map_path=room_map, runtime=runtime
                )
            self.assertEqual(runtime.files, {})

            deployment.deploy_skill_packages(
                ROOT,
                confirm_version="v1.1.2",
                room_map_path=room_map,
                runtime=runtime,
            )
            before = dict(runtime.files)
            report = deployment.verify_skill_packages(
                ROOT, room_map_path=room_map, runtime=runtime
            )

        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(report["runtime_event_emission"], "VERIFIED")
        self.assertEqual(report["skill_count"], 7)
        self.assertEqual(runtime.files, before)
        self.assertTrue(all(item["invocation"] == "UNVERIFIED" for item in report["skills"]))
        self.assertTrue(all(item["emitter_dry_run"] == "VERIFIED" for item in report["skills"]))

    def test_verify_fails_closed_when_a_runtime_emitter_cannot_dry_run(self) -> None:
        runtime = InMemoryAgentTeamsRuntime()
        with tempfile.TemporaryDirectory() as tmp:
            room_map = write_room_map(Path(tmp))
            deployment.deploy_skill_packages(
                ROOT,
                confirm_version="v1.1.2",
                room_map_path=room_map,
                runtime=runtime,
            )
            runtime.dry_run_ok = False

            with self.assertRaisesRegex(
                deployment.AgentTeamsSkillDeploymentError,
                "emitter dry-run",
            ):
                deployment.verify_skill_packages(
                    ROOT, room_map_path=room_map, runtime=runtime
                )

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

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                deployment.AgentTeamsSkillDeploymentError,
                "Runtime Skill conflict",
            ):
                deployment.deploy_skill_packages(
                    ROOT,
                    confirm_version="v1.1.2",
                    room_map_path=write_room_map(Path(tmp)),
                    runtime=runtime,
                )

        self.assertEqual(runtime.files, before)

    def test_deploy_rejects_stopped_or_wrong_version_containers(self) -> None:
        for runtime in (
            InMemoryAgentTeamsRuntime(running=False),
            InMemoryAgentTeamsRuntime(image_version="v1.1.3"),
        ):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(deployment.AgentTeamsSkillDeploymentError):
                    deployment.deploy_skill_packages(
                        ROOT,
                        confirm_version="v1.1.2",
                        room_map_path=write_room_map(Path(tmp)),
                        runtime=runtime,
                    )
                self.assertEqual(runtime.files, {})

    def test_changed_runtime_package_requires_explicit_replacement_and_is_backed_up(self) -> None:
        runtime = InMemoryAgentTeamsRuntime()
        with tempfile.TemporaryDirectory() as tmp:
            room_map = write_room_map(Path(tmp))
            deployment.deploy_skill_packages(
                ROOT,
                confirm_version="v1.1.2",
                room_map_path=room_map,
                runtime=runtime,
            )
            emitter_key = next(
                key
                for key in runtime.files
                if key[0] == "hiclaw-worker-evidence-collector"
                and key[1].endswith("/collect-lab-evidence/scripts/emit_handoff.py")
            )
            runtime.files[emitter_key] = b"drifted emitter"

            with self.assertRaisesRegex(
                deployment.AgentTeamsSkillDeploymentError,
                "Runtime Skill conflict",
            ):
                deployment.deploy_skill_packages(
                    ROOT,
                    confirm_version="v1.1.2",
                    room_map_path=room_map,
                    runtime=runtime,
                )

            report = deployment.deploy_skill_packages(
                ROOT,
                confirm_version="v1.1.2",
                room_map_path=room_map,
                replace_existing=True,
                runtime=runtime,
            )

        collector = next(
            item for item in report["skills"] if item["skill_id"] == "collect-lab-evidence"
        )
        self.assertEqual(collector["deployment"], "REPLACED")
        self.assertEqual(collector["event_emitter"], "VERIFIED")
        self.assertEqual(len(runtime.backups), 1)
        self.assertIn(b"drifted emitter", runtime.backups[0].values())

    def test_verify_cli_emits_the_read_only_runtime_report(self) -> None:
        expected = {
            "schema_version": "1.0",
            "status": "VERIFIED",
            "skill_count": 7,
            "runtime_event_emission": "VERIFIED",
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            room_map = write_room_map(Path(tmp))
            with patch.dict(os.environ, {"LABOPS_MATRIX_ROOM_MAP": str(room_map)}):
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
