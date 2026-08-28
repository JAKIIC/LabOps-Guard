"""Behavioral tests for the source-only competition submission bundle."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from labops.submission_bundle import (
    SubmissionBundleError,
    build_submission_bundle,
    verify_submission_bundle,
)


def _write(root: Path, relative: str, data: bytes = b"fixture") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


class SubmissionBundleTests(unittest.TestCase):
    def test_cli_exposes_output_directory_without_building(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/build_submission_bundle.py", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--output-dir", completed.stdout)
        self.assertIn("--video", completed.stdout)

    def test_builds_commit_bound_source_only_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            output = base / "output"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.invalid")
            _git(repo, "config", "user.name", "LabOps Test")

            required = {
                "README.md": b"# LabOps Guard\n",
                "FINAL_SUBMISSION_CHECKLIST.md": b"final checklist\n",
                "LICENSE": b"Apache-2.0\n",
                "THIRD_PARTY_NOTICES.md": b"notices\n",
                "submission/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pptx": b"pptx",
                "submission/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pdf": b"pdf",
                "submission/复赛提交清单.md": b"checklist",
                "submission/复赛视频录制检查表.md": b"video checklist",
                "docs/reviewer-edition.md": b"reviewer runbook",
                "docs/final-demo-guide.md": b"guide",
                "docs/final-demo-recording-runbook.md": b"runbook",
                "docs/final-demo-video-script.md": b"script",
                "docs/trust-evaluation-report-v1.0.md": b"evaluation",
                "docs/compliance/runner-sbom.json": b"{}",
                "docs/compliance/runner-license-review.md": b"license review",
                "docs/compliance/runner-notice-review.md": b"notice review",
                "evaluation/results/trust-evaluation-suite-v1.json": b"{}",
                "demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip": b"at002",
                "demo/output-agentteams-at003/artifacts/DEMO-RCA-003/LABOPS-AT-003-evidence-bundle.zip": b"at003",
                "demo/output-agentteams-at004/LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip": b"at004",
            }
            evidence_hashes = {}
            for relative, data in required.items():
                path = _write(repo, relative, data)
                if relative.endswith("evidence-bundle.zip"):
                    evidence_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "fixture")
            commit = _git(repo, "rev-parse", "HEAD")

            dirty = _write(repo, "untracked.tmp", b"must block packaging")
            with self.assertRaisesRegex(SubmissionBundleError, "worktree must be clean"):
                build_submission_bundle(repo, output, expected_evidence_hashes=evidence_hashes)
            dirty.unlink()

            wrong_hashes = dict(evidence_hashes)
            first_evidence = next(iter(wrong_hashes))
            wrong_hashes[first_evidence] = "0" * 64
            with self.assertRaisesRegex(SubmissionBundleError, "Evidence SHA-256 mismatch"):
                build_submission_bundle(repo, output, expected_evidence_hashes=wrong_hashes)

            result = build_submission_bundle(
                repo,
                output,
                expected_evidence_hashes=evidence_hashes,
            )

            self.assertEqual(commit, result["commit"])
            self.assertEqual("VIDEO_PENDING", result["video_status"])
            self.assertGreater(result["verified_file_count"], 10)
            bundle = Path(result["bundle"])
            self.assertTrue(bundle.is_file())

            prefix = f"LabOps-Guard-GOAI-Semifinal-v1.0-rc1-{commit[:7]}/"
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                self.assertIn(prefix + "01_项目方案/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pdf", names)
                self.assertIn(prefix + "02_代码包/LabOps-Guard-v1.0-rc1-" + commit[:7] + "-source.zip", names)
                self.assertIn(prefix + "03_演示与运行/reviewer-edition.md", names)
                self.assertIn(prefix + "04_正式证据/LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip", names)
                self.assertIn(prefix + "FINAL_CANDIDATE_MANIFEST.json", names)
                self.assertIn(prefix + "SHA256SUMS.txt", names)
                self.assertIn(prefix + "VIDEO_PENDING.txt", names)
                self.assertFalse(any(name.endswith((".tar", ".img")) for name in names))
                self.assertFalse(any("live-sessions" in name or "/.git/" in name for name in names))

                manifest = json.loads(
                    archive.read(prefix + "FINAL_CANDIDATE_MANIFEST.json").decode("utf-8")
                )
                self.assertEqual(commit, manifest["git_commit"])
                self.assertEqual("SOURCE_ONLY_NO_VIDEO", manifest["classification"])

            verification = verify_submission_bundle(
                bundle,
                expected_evidence_hashes=evidence_hashes,
            )
            self.assertEqual("PASS", verification["status"])

            wrong_expected = dict(evidence_hashes)
            wrong_expected[first_evidence] = "f" * 64
            with self.assertRaisesRegex(
                SubmissionBundleError,
                "frozen Evidence SHA-256 mismatch",
            ):
                verify_submission_bundle(
                    bundle,
                    expected_evidence_hashes=wrong_expected,
                )

            video = _write(base, "LabOps-Guard-final-demo.mp4", b"privacy-reviewed-video")
            complete = build_submission_bundle(
                repo,
                output,
                expected_evidence_hashes=evidence_hashes,
                video_path=video,
            )
            self.assertEqual("INCLUDED", complete["video_status"])
            with zipfile.ZipFile(complete["bundle"]) as archive:
                complete_names = set(archive.namelist())
                complete_prefix = f"LabOps-Guard-GOAI-Semifinal-v1.0-rc1-{commit[:7]}/"
                self.assertNotIn(complete_prefix + "VIDEO_PENDING.txt", complete_names)
                self.assertIn(
                    complete_prefix + "07_Demo视频/LabOps-Guard-GOAI-复赛-Demo.mp4",
                    complete_names,
                )
                complete_manifest = json.loads(
                    archive.read(complete_prefix + "FINAL_CANDIDATE_MANIFEST.json").decode("utf-8")
                )
                self.assertEqual("COMPLETE_WITH_VIDEO", complete_manifest["classification"])
                self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(), complete_manifest["video_sha256"])
            self.assertEqual(
                "PASS",
                verify_submission_bundle(
                    complete["bundle"],
                    expected_evidence_hashes=evidence_hashes,
                )["status"],
            )

            tampered = bundle.with_name("tampered.zip")
            with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(tampered, "w") as destination:
                for name in source.namelist():
                    data = source.read(name)
                    if name == prefix + "VIDEO_PENDING.txt":
                        data = b"tampered"
                    destination.writestr(name, data)
            with self.assertRaisesRegex(SubmissionBundleError, "attachment checksum mismatch"):
                verify_submission_bundle(
                    tampered,
                    expected_evidence_hashes=evidence_hashes,
                )


if __name__ == "__main__":
    unittest.main()
