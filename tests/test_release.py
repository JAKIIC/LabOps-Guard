import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.verify_evidence import verify_bundle, verify_trace


class TestReleaseEvidenceVerifier(unittest.TestCase):
    def test_trace_hash_chain(self):
        previous = None
        lines = []
        for seq in range(2):
            record = {"seq": seq, "event": "test", "prev_hash": previous}
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
            record["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
            previous = record["hash"]
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        ok, message = verify_trace(("\n".join(lines) + "\n").encode())
        self.assertTrue(ok, message)

    def test_bundle_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("proof.txt", b"proof")
            manifest = {
                "task_id": "unexpected",
                "zip_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "artifacts": {"proof.txt": hashlib.sha256(b"tampered expectation").hexdigest()},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = verify_bundle(bundle, manifest_path)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("hash mismatch" in error for error in result["errors"]))


class TestReleaseScriptSafety(unittest.TestCase):
    def test_cleanup_is_bounded_and_formal_evidence_is_protected(self):
        text = (Path(__file__).parents[1] / "scripts" / "clean_disposable_runs.ps1").read_text(encoding="utf-8")
        self.assertIn("artifacts\\release-validation", text)
        self.assertIn("output-agentteams-at00[234]", text)
        self.assertIn("SupportsShouldProcess", text)

    def test_release_requires_clean_git_and_verifies_checksums(self):
        text = (Path(__file__).parents[1] / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn("git status --porcelain", text)
        self.assertIn("verify_evidence.py", text)
        self.assertIn("checksums.sha256", text)
        loader = (Path(__file__).parents[1] / "scripts" / "load_runner_image.ps1").read_text(encoding="utf-8")
        self.assertEqual(loader.count("Assert-ReleaseArchiveChecksum"), 4)


class TestReviewerEditionPackage(unittest.TestCase):
    @property
    def project_root(self):
        return Path(__file__).parents[1]

    def test_compose_is_quick_only_and_keeps_evidence_read_only(self):
        compose_path = self.project_root / "compose.reviewer.yaml"
        compose = json.loads(compose_path.read_text(encoding="utf-8"))
        service = compose["services"]["reviewer-quick"]

        self.assertEqual(service["image"], "labops-guard:local")
        self.assertEqual(service["build"], {"context": "."})
        self.assertNotIn("network_mode", service)
        self.assertEqual(service["ports"], ["127.0.0.1:18787:18787"])
        self.assertTrue(service["read_only"])
        self.assertEqual(service["command"][:7], [
            "python", "-B", "-m", "labops", "reviewer", "start", "--mode",
        ])
        self.assertEqual(service["command"][7], "quick")
        self.assertIn("--container-bind", service["command"])
        self.assertIn("--host", service["command"])
        self.assertEqual(service["command"][service["command"].index("--host") + 1], "127.0.0.1")

        mounts = service["volumes"]
        for source, target in (
            ("./labops", "/app/labops"),
            ("./agentteams", "/app/agentteams"),
            ("./skills", "/app/skills"),
            ("./schemas", "/app/schemas"),
            ("./scripts", "/app/scripts"),
        ):
            self.assertIn(f"{source}:{target}:ro", mounts)
        for case_id in ("at002", "at003", "at004"):
            prefix = f"./demo/output-agentteams-{case_id}:"
            matching = [value for value in mounts if value.startswith(prefix)]
            self.assertEqual(len(matching), 1)
            self.assertTrue(matching[0].endswith(":ro"))
        self.assertIn("./demo/live-sessions:/live-sessions:ro", mounts)
        self.assertIn("/tmp:size=64m,mode=1777", service["tmpfs"])
        sessions_index = service["command"].index("--sessions-root")
        self.assertEqual(service["command"][sessions_index + 1], "/tmp/reviewer-sessions")

        serialized = json.dumps(compose, ensure_ascii=False).lower()
        self.assertNotIn("matrix_access_token", serialized)
        self.assertNotIn("bearer ", serialized)
        self.assertNotIn("reviewer-live", compose["services"])

    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper is exercised on Windows")
    def test_powershell_wrapper_delegates_and_preserves_preflight_failure(self):
        script = self.project_root / "scripts" / "start_reviewer_demo.ps1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "calls.log"
            fake_python = root / "python.cmd"
            fake_python.write_text(
                "@echo off\n"
                "echo %*>>\"%CALL_LOG%\"\n"
                "echo %* | findstr /C:\"reviewer preflight\" >nul\n"
                "if not errorlevel 1 if not \"%FAKE_PREFLIGHT_EXIT%\"==\"\" exit /b %FAKE_PREFLIGHT_EXIT%\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["PATH"] = f"{root}{os.pathsep}{environment['PATH']}"
            environment["CALL_LOG"] = str(log)

            success = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script), "-Mode", "quick",
                ],
                cwd=self.project_root,
                env=environment,
                check=False,
                capture_output=True,
            )
            self.assertEqual(success.returncode, 0, success.stderr.decode(errors="replace"))
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), [
                "-B -m labops reviewer pack-check --mode quick",
                "-B -m labops reviewer preflight --mode quick",
                "-B -m labops reviewer start --mode quick",
            ])

            log.unlink()
            environment["FAKE_PREFLIGHT_EXIT"] = "7"
            blocked = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script), "-Mode", "live",
                ],
                cwd=self.project_root,
                env=environment,
                check=False,
                capture_output=True,
            )
            self.assertEqual(blocked.returncode, 7)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), [
                "-B -m labops reviewer pack-check --mode live",
                "-B -m labops reviewer preflight --mode live",
            ])

    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper is exercised on Windows")
    def test_powershell_wrapper_sets_live_evidence_defaults_only_for_live_mode(self):
        script = self.project_root / "scripts" / "start_reviewer_demo.ps1"
        text = script.read_text(encoding="utf-8")
        source_config = json.loads(
            (self.project_root / "config" / "reviewer-evidence-source.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("LABOPS_LIVE_EVIDENCE_CONTAINER", text)
        self.assertIn("LABOPS_LIVE_EVIDENCE_ROOT", text)
        self.assertIn("reviewer-evidence-source.json", text)
        self.assertEqual(source_config["container"], "hiclaw-manager")
        self.assertTrue(source_config["root"].endswith("/shared/tasks/live-demo"))
        self.assertNotIn("LABOPS_MATRIX_ACCESS_TOKEN", text)
        self.assertNotIn("!manager:matrix-local", text)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "environment.log"
            fake_python = root / "python.cmd"
            fake_python.write_text(
                "@echo off\n"
                "echo %LABOPS_LIVE_EVIDENCE_CONTAINER%^|%LABOPS_LIVE_EVIDENCE_ROOT%>>\"%CALL_LOG%\"\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["PATH"] = f"{root}{os.pathsep}{environment['PATH']}"
            environment["CALL_LOG"] = str(log)
            environment.pop("LABOPS_LIVE_EVIDENCE_CONTAINER", None)
            environment.pop("LABOPS_LIVE_EVIDENCE_ROOT", None)

            quick = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script), "-Mode", "quick",
                ],
                cwd=self.project_root,
                env=environment,
                check=False,
                capture_output=True,
            )
            self.assertEqual(quick.returncode, 0)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ["|", "|", "|"])

            log.unlink()
            live = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script), "-Mode", "live",
                ],
                cwd=self.project_root,
                env=environment,
                check=False,
                capture_output=True,
            )
            self.assertEqual(live.returncode, 0)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                [
                    f"{source_config['container']}|{source_config['root']}",
                    f"{source_config['container']}|{source_config['root']}",
                    f"{source_config['container']}|{source_config['root']}",
                ],
            )

            log.unlink()
            custom = dict(environment)
            custom["LABOPS_LIVE_EVIDENCE_CONTAINER"] = "custom-manager"
            custom["LABOPS_LIVE_EVIDENCE_ROOT"] = "/custom/read-only-root"
            overridden = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script), "-Mode", "live",
                ],
                cwd=self.project_root,
                env=custom,
                check=False,
                capture_output=True,
            )
            self.assertEqual(overridden.returncode, 0)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                [
                    "custom-manager|/custom/read-only-root",
                    "custom-manager|/custom/read-only-root",
                    "custom-manager|/custom/read-only-root",
                ],
            )

    @unittest.skipUnless(os.name != "nt" and shutil.which("sh"), "shell wrapper is exercised on POSIX")
    def test_shell_wrapper_delegates_and_preserves_preflight_failure(self):
        script = self.project_root / "scripts" / "start_reviewer_demo.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "calls.log"
            fake_python = root / "python"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >>\"$CALL_LOG\"\n"
                "case \"$*\" in *'reviewer preflight'*) exit \"${FAKE_PREFLIGHT_EXIT:-0}\";; esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{root}{os.pathsep}{environment['PATH']}"
            environment["CALL_LOG"] = str(log)
            result = subprocess.run(
                ["sh", str(script), "quick"],
                cwd=self.project_root,
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), [
                "-B -m labops reviewer pack-check --mode quick",
                "-B -m labops reviewer preflight --mode quick",
                "-B -m labops reviewer start --mode quick",
            ])


if __name__ == "__main__":
    unittest.main()
