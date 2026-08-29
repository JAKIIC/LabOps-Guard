from __future__ import annotations

import io
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from labops import cli
from labops.reproducibility import build_pack_report, load_runtime_lock
from scripts import scan_sensitive


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "config/reviewer-runtime-lock.json"
RUNNER_LABELS = {
    "io.labops.runner.image": "labops/pytorch-cpu-runner:0.2.0",
    "io.labops.runner.python": "3.11.15",
    "io.labops.runner.torch": "2.5.1+cpu",
    "io.labops.runner.network-runtime": "none",
}


class RuntimeLockTests(unittest.TestCase):
    def test_committed_lock_is_schema_valid_and_contains_no_secret_fields(self) -> None:
        runtime_lock = load_runtime_lock(ROOT, LOCK)

        self.assertEqual(runtime_lock["agentteams"]["version"], "v1.1.2")
        self.assertEqual(
            runtime_lock["agentteams"]["installer_sha256"],
            "91a616ff80677d2329a6432c2c02c97ab6e397a027922943d8a34c7b53887c09",
        )
        self.assertEqual(runtime_lock["runner"]["image"], "labops/pytorch-cpu-runner:0.2.0")
        rendered = json.dumps(runtime_lock, sort_keys=True).lower()
        for forbidden in ("token", "password", "api_key", "credential", "room_id"):
            self.assertNotIn(forbidden, rendered)

    def test_lock_rejects_unknown_fields_instead_of_silently_accepting_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "lock.json"
            payload = json.loads(LOCK.read_text(encoding="utf-8"))
            payload["unreviewed_component"] = {"version": "latest"}
            lock_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unexpected fields"):
                load_runtime_lock(ROOT, lock_path)

    def test_lock_rejects_a_version_that_does_not_match_the_installer_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "lock.json"
            payload = json.loads(LOCK.read_text(encoding="utf-8"))
            payload["agentteams"]["version"] = "v1.1.1"
            lock_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "version does not match installer URL"):
                load_runtime_lock(ROOT, lock_path)

    def test_lock_rejects_duplicate_bundled_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "lock.json"
            payload = json.loads(LOCK.read_text(encoding="utf-8"))
            payload["bundled_components"] = ["MinIO", "MinIO", "MinIO", "MinIO"]
            lock_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "bundled components are incomplete"):
                load_runtime_lock(ROOT, lock_path)


class ReproducibilityReportTests(unittest.TestCase):
    def test_quick_pack_check_is_credential_free_and_reproducible_offline(self) -> None:
        report = build_pack_report(ROOT, "quick", LOCK, environment={})

        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["requested_mode"], "QUICK")
        self.assertEqual(report["checks"]["runtime_lock"]["status"], "PASS")
        self.assertEqual(report["checks"]["repository"]["status"], "PASS")
        self.assertEqual(report["versions"]["agentteams"], "v1.1.2")
        self.assertEqual(report["fallback"]["mode"], "PUBLIC_EVIDENCE_REPLAY")
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn("LABOPS_MATRIX_ACCESS_TOKEN", rendered)

    def test_live_pack_check_lists_external_runtime_gaps_without_guessing_success(self) -> None:
        report = build_pack_report(
            ROOT,
            "live",
            LOCK,
            environment={},
            docker_probe=lambda _root, _lock: {
                "docker": False,
                "runner_image": False,
                "runner_labels": {},
                "agentteams_controller": False,
                "agentteams_manager": False,
                "agentteams_workers": 0,
                "agentteams_version": None,
                "docker_server_version": None,
            },
        )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(
            report["missing_requirements"],
            [
                "DOCKER_UNAVAILABLE",
                "RUNNER_IMAGE_MISSING",
                "AGENTTEAMS_CONTROLLER_MISSING",
                "AGENTTEAMS_MANAGER_MISSING",
                "AGENTTEAMS_WORKERS_INSUFFICIENT",
                "MATRIX_HOMESERVER_MISSING",
                "MATRIX_ACCESS_TOKEN_MISSING",
                "MATRIX_ROOM_MAP_MISSING",
            ],
        )
        self.assertEqual(report["fallback"]["mode"], "QUICK")

    def test_live_pack_check_accepts_only_pinned_runner_and_six_canonical_rooms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room_map = Path(tmp) / "room-map.json"
            room_map.write_text(
                (ROOT / "config/reviewer-room-map.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            environment = {
                "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                "LABOPS_MATRIX_ACCESS_TOKEN": "private-reviewer-token",
                "LABOPS_MATRIX_ROOM_MAP": str(room_map),
            }
            report = build_pack_report(
                ROOT,
                "live",
                LOCK,
                environment=environment,
                docker_probe=lambda _root, _lock: {
                    "docker": True,
                    "runner_image": True,
                    "runner_labels": dict(RUNNER_LABELS),
                    "agentteams_controller": True,
                    "agentteams_manager": True,
                    "agentteams_workers": 5,
                    "agentteams_version": "v1.1.2",
                    "docker_server_version": "29.6.2",
                },
            )

        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["checks"]["runner_contract"]["status"], "PASS")
        self.assertEqual(report["checks"]["agentteams_runtime"]["status"], "PASS")
        self.assertEqual(report["checks"]["matrix_room_map"]["rooms"], 6)
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("private-reviewer-token", rendered)
        self.assertNotIn(str(room_map), rendered)
        self.assertNotIn("!manager-room:example.invalid", rendered)

    def test_live_pack_check_blocks_a_runner_with_drifted_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room_map = Path(tmp) / "room-map.json"
            room_map.write_text(
                (ROOT / "config/reviewer-room-map.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            labels = dict(RUNNER_LABELS)
            labels["io.labops.runner.network-runtime"] = "bridge"
            report = build_pack_report(
                ROOT,
                "live",
                LOCK,
                environment={
                    "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                    "LABOPS_MATRIX_ACCESS_TOKEN": "secret",
                    "LABOPS_MATRIX_ROOM_MAP": str(room_map),
                },
                docker_probe=lambda _root, _lock: {
                    "docker": True,
                    "runner_image": True,
                    "runner_labels": labels,
                    "agentteams_controller": True,
                    "agentteams_manager": True,
                    "agentteams_workers": 5,
                    "agentteams_version": "v1.1.2",
                    "docker_server_version": "29.6.2",
                },
            )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("RUNNER_CONTRACT_MISMATCH", report["missing_requirements"])

    def test_live_pack_check_blocks_an_unexpected_agentteams_image_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room_map = Path(tmp) / "room-map.json"
            room_map.write_text(
                (ROOT / "config/reviewer-room-map.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            report = build_pack_report(
                ROOT,
                "live",
                LOCK,
                environment={
                    "LABOPS_MATRIX_HOMESERVER": "http://127.0.0.1:18080",
                    "LABOPS_MATRIX_ACCESS_TOKEN": "secret",
                    "LABOPS_MATRIX_ROOM_MAP": str(room_map),
                },
                docker_probe=lambda _root, _lock: {
                    "docker": True,
                    "runner_image": True,
                    "runner_labels": dict(RUNNER_LABELS),
                    "agentteams_controller": True,
                    "agentteams_manager": True,
                    "agentteams_workers": 5,
                    "agentteams_version": "v1.2.2",
                    "docker_server_version": "29.6.2",
                },
            )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("AGENTTEAMS_VERSION_MISMATCH", report["missing_requirements"])


class ReproducibilityCLITests(unittest.TestCase):
    def test_reviewer_pack_check_cli_returns_the_report_status(self) -> None:
        ready = {
            "schema_version": "1.0",
            "requested_mode": "QUICK",
            "status": "READY",
            "checks": {},
            "versions": {},
            "missing_requirements": [],
            "fallback": {"mode": "PUBLIC_EVIDENCE_REPLAY"},
        }
        output = io.StringIO()
        with patch("labops.reproducibility.build_pack_report", return_value=ready):
            with redirect_stdout(output):
                rc = cli.main(["reviewer", "pack-check", "--mode", "quick"])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "READY")


class ReproducibilityWrapperTests(unittest.TestCase):
    def _fake_python(self, directory: Path, *, fail_on: str | None = None) -> tuple[Path, Path]:
        log = directory / "calls.log"
        executable = directory / "python.cmd"
        failure = (
            f'echo %* | %SystemRoot%\\System32\\findstr.exe /c:"{fail_on}" >nul && exit /b 23\r\n'
            if fail_on
            else ""
        )
        executable.write_text(
            "@echo off\r\n"
            f'echo %*>>"{log}"\r\n'
            f"{failure}"
            "exit /b 0\r\n",
            encoding="ascii",
        )
        return executable, log

    def test_windows_start_wrapper_stops_before_preflight_when_pack_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _fake, log = self._fake_python(directory, fail_on="pack-check")
            environment = dict(os.environ)
            environment["PATH"] = str(directory) + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/start_reviewer_demo.ps1"),
                    "-Mode",
                    "quick",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            calls = log.read_text(encoding="ascii").splitlines()

        self.assertEqual(result.returncode, 23)
        self.assertEqual(len(calls), 1)
        self.assertIn("reviewer pack-check --mode quick", calls[0])
        self.assertNotIn("reviewer start", calls[0])

    def test_windows_stop_wrapper_requests_only_the_recorded_reviewer_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _fake, log = self._fake_python(directory)
            environment = dict(os.environ)
            environment["PATH"] = str(directory) + os.pathsep + environment.get("PATH", "")
            sessions = directory / "sessions"
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/stop_reviewer_demo.ps1"),
                    "-SessionsRoot",
                    str(sessions),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            calls = log.read_text(encoding="ascii").splitlines() if log.exists() else []

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("reviewer stop --sessions-root", calls[0])
        self.assertNotIn("docker", " ".join(calls).lower())

    def test_windows_installer_helper_verifies_bytes_before_optional_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "installer-source.ps1"
            source.write_text("Write-Output 'fixture installer'\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            runtime_lock = directory / "runtime-lock.json"
            runtime_lock.write_text(
                json.dumps({
                    "agentteams": {
                        "version": "v1.1.2",
                        "installer_url": "https://example.invalid/installer.ps1",
                        "installer_sha256": digest,
                    }
                }),
                encoding="utf-8",
            )
            destination = directory / "downloaded.ps1"
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/install_agentteams_reviewer.ps1"),
                    "-RuntimeLock",
                    str(runtime_lock),
                    "-SourcePath",
                    str(source),
                    "-Destination",
                    str(destination),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "VERIFIED_DOWNLOAD")
        self.assertEqual(payload["version"], "v1.1.2")
        self.assertFalse(payload["executed"])

    def test_windows_installer_helper_deletes_a_checksum_mismatch_without_running_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "installer-source.ps1"
            source.write_text("throw 'must never execute'\n", encoding="utf-8")
            runtime_lock = directory / "runtime-lock.json"
            runtime_lock.write_text(
                json.dumps({
                    "agentteams": {
                        "version": "v1.1.2",
                        "installer_url": "https://example.invalid/installer.ps1",
                        "installer_sha256": "0" * 64,
                    }
                }),
                encoding="utf-8",
            )
            destination = directory / "downloaded.ps1"
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/install_agentteams_reviewer.ps1"),
                    "-RuntimeLock",
                    str(runtime_lock),
                    "-SourcePath",
                    str(source),
                    "-Destination",
                    str(destination),
                    "-Execute",
                    "-ConfirmVersion",
                    "v1.1.2",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            destination_exists = destination.exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(destination_exists)
        self.assertNotIn("must never execute", result.stdout)

    @unittest.skipUnless(shutil.which("sh"), "POSIX shell is verified on Linux CI")
    def test_posix_start_wrapper_stops_when_pack_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            log = directory / "calls.log"
            python = directory / "python"
            python.write_text(
                "#!/bin/sh\n"
                f'printf "%s\\n" "$*" >> "{log.as_posix()}"\n'
                'case "$*" in *"pack-check"*) exit 23;; esac\n'
                "exit 0\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = str(directory) + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                ["sh", str(ROOT / "scripts/start_reviewer_demo.sh"), "quick"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            calls = log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.returncode, 23)
        self.assertEqual(calls, ["-B -m labops reviewer pack-check --mode quick"])


class ReproducibilitySensitiveScanTests(unittest.TestCase):
    def test_environment_example_files_are_inside_the_credential_scan_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = root / "reviewer.env.example"
            secret_assignment = "access_" + "token" + '="not-a-real-but-secret-shaped-value"\n'
            example.write_text(secret_assignment, encoding="utf-8")
            with patch.object(scan_sensitive, "tracked_files", return_value=[example]):
                result = scan_sensitive.scan(root)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["findings"], [
            {"file": "reviewer.env.example", "pattern": "assigned_secret"}
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
