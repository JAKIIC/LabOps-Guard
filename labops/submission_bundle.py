"""Build a commit-bound GOAI semifinal attachment without Runner images."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Mapping


VERSION = "v1.0-rc1"

FORMAL_EVIDENCE_SHA256 = {
    "demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip":
        "1a957940bed0ef6c01745273854a2d08946ab191198441a80b7fa102df8f9365",
    "demo/output-agentteams-at003/artifacts/DEMO-RCA-003/LABOPS-AT-003-evidence-bundle.zip":
        "630bc18ed92f4f094ffc5fcb5a6ea7337408fbee87fe549450e1df420dbd1703",
    "demo/output-agentteams-at004/LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip":
        "4092b43f39df52db3847caa28ca01e4321129a1c17ec7ca5efd2029ab1fb77cd",
}

ATTACHMENT_FILES = {
    "README.md": "00_提交说明/README.md",
    "FINAL_SUBMISSION_CHECKLIST.md": "00_提交说明/FINAL_SUBMISSION_CHECKLIST.md",
    "submission/复赛提交清单.md": "00_提交说明/复赛提交清单.md",
    "submission/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pptx":
        "01_项目方案/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pptx",
    "submission/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pdf":
        "01_项目方案/LabOps-Guard-GOAI-复赛方案-v1.0-rc1.pdf",
    "docs/final-demo-guide.md": "03_演示与运行/final-demo-guide.md",
    "docs/final-demo-recording-runbook.md": "03_演示与运行/final-demo-recording-runbook.md",
    "docs/final-demo-video-script.md": "03_演示与运行/final-demo-video-script.md",
    "submission/复赛视频录制检查表.md": "03_演示与运行/复赛视频录制检查表.md",
    "docs/trust-evaluation-report-v1.0.md": "05_治理评测/trust-evaluation-report-v1.0.md",
    "evaluation/results/trust-evaluation-suite-v1.json": "05_治理评测/trust-evaluation-suite-v1.json",
    "LICENSE": "06_开源合规/LICENSE",
    "THIRD_PARTY_NOTICES.md": "06_开源合规/THIRD_PARTY_NOTICES.md",
    "docs/compliance/runner-sbom.json": "06_开源合规/runner-sbom.json",
    "docs/compliance/runner-license-review.md": "06_开源合规/runner-license-review.md",
    "docs/compliance/runner-notice-review.md": "06_开源合规/runner-notice-review.md",
}


class SubmissionBundleError(RuntimeError):
    """Raised when a competition attachment cannot be built safely."""


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_required(repo_root: Path, stage_root: Path) -> None:
    for source_name, destination_name in ATTACHMENT_FILES.items():
        source = repo_root / source_name
        if not source.is_file():
            raise SubmissionBundleError(f"required submission file is missing: {source_name}")
        destination = stage_root / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _write_checksums(stage_root: Path) -> None:
    lines = []
    for path in sorted(stage_root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            relative = path.relative_to(stage_root).as_posix()
            lines.append(f"{_sha256(path)}  {relative}")
    (stage_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _zip_tree(stage_root: Path, destination: Path, prefix: str) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage_root.rglob("*")):
            if path.is_file():
                archive.write(path, prefix + path.relative_to(stage_root).as_posix())


def verify_submission_bundle(
    bundle: Path,
    *,
    expected_evidence_hashes: Mapping[str, str] | None = None,
) -> dict:
    """Verify attachment membership, checksums, frozen Evidence and source boundaries."""

    bundle = Path(bundle).resolve()
    if not bundle.is_file():
        raise SubmissionBundleError(f"submission attachment is missing: {bundle}")
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise SubmissionBundleError("duplicate archive member")
        manifest_names = [name for name in names if name.endswith("/FINAL_CANDIDATE_MANIFEST.json")]
        if len(manifest_names) != 1:
            raise SubmissionBundleError("attachment must contain one final candidate manifest")
        prefix = manifest_names[0][: -len("FINAL_CANDIDATE_MANIFEST.json")]
        if not prefix or any(not name.startswith(prefix) for name in names):
            raise SubmissionBundleError("attachment members do not share one candidate prefix")

        forbidden_suffixes = (".tar", ".img", ".pem", ".key", ".p12", ".env")
        for name in names:
            lowered = name.lower()
            if lowered.endswith(forbidden_suffixes) or "/.git/" in lowered or "live-sessions" in lowered:
                raise SubmissionBundleError(f"forbidden attachment member: {name}")

        manifest = json.loads(archive.read(manifest_names[0]).decode("utf-8"))
        classification = manifest.get("classification")
        if classification not in {"SOURCE_ONLY_NO_VIDEO", "COMPLETE_WITH_VIDEO"}:
            raise SubmissionBundleError("unexpected attachment classification")
        if manifest.get("runner_images_included") is not False:
            raise SubmissionBundleError("Runner image boundary is inconsistent")
        video_members = [name for name in names if name.lower().endswith(".mp4")]
        pending_name = prefix + "VIDEO_PENDING.txt"
        if classification == "SOURCE_ONLY_NO_VIDEO":
            if manifest.get("video_status") != "VIDEO_PENDING" or video_members or pending_name not in names:
                raise SubmissionBundleError("no-video attachment boundary is inconsistent")
        else:
            expected_video = prefix + manifest.get("video_path", "")
            if (
                manifest.get("video_status") != "INCLUDED"
                or video_members != [expected_video]
                or pending_name in names
            ):
                raise SubmissionBundleError("video attachment boundary is inconsistent")
            actual_video_sha = hashlib.sha256(archive.read(expected_video)).hexdigest()
            if actual_video_sha != manifest.get("video_sha256"):
                raise SubmissionBundleError("video checksum mismatch")

        checksum_name = prefix + "SHA256SUMS.txt"
        checksums = {}
        for line in archive.read(checksum_name).decode("utf-8").splitlines():
            digest, separator, relative = line.partition("  ")
            if not separator or len(digest) != 64 or relative in checksums:
                raise SubmissionBundleError("invalid checksum manifest entry")
            checksums[relative] = digest
        expected_members = {
            name[len(prefix):]
            for name in names
            if name != checksum_name
        }
        if set(checksums) != expected_members:
            raise SubmissionBundleError("checksum manifest does not cover attachment members exactly")
        for relative, expected in checksums.items():
            actual = hashlib.sha256(archive.read(prefix + relative)).hexdigest()
            if actual != expected:
                raise SubmissionBundleError(f"attachment checksum mismatch: {relative}")

        evidence_hashes = manifest.get("formal_evidence_sha256", {})
        if not isinstance(evidence_hashes, dict) or len(evidence_hashes) != 3:
            raise SubmissionBundleError("manifest must bind three formal Evidence archives")
        frozen_hashes = dict(expected_evidence_hashes or FORMAL_EVIDENCE_SHA256)
        if evidence_hashes != frozen_hashes:
            raise SubmissionBundleError("frozen Evidence SHA-256 mismatch")
        for source_name, expected in evidence_hashes.items():
            member = prefix + "04_正式证据/" + Path(source_name).name
            actual = hashlib.sha256(archive.read(member)).hexdigest()
            if actual != expected:
                raise SubmissionBundleError(f"formal Evidence checksum mismatch: {source_name}")

        source_member = prefix + manifest["source_archive"]
        with zipfile.ZipFile(io.BytesIO(archive.read(source_member))) as source_archive:
            source_names = source_archive.namelist()
            if not source_names or any(
                "/.git/" in name.lower()
                or "live-sessions" in name.lower()
                or name.lower().endswith((".tar", ".img", ".mp4"))
                for name in source_names
            ):
                raise SubmissionBundleError("source archive contains forbidden content")

    return {
        "status": "PASS",
        "bundle": str(bundle),
        "bundle_sha256": _sha256(bundle),
        "git_commit": manifest["git_commit"],
        "file_count": len(names),
        "video_status": manifest["video_status"],
    }


def build_submission_bundle(
    repo_root: Path,
    output_dir: Path,
    *,
    expected_evidence_hashes: Mapping[str, str] | None = None,
    video_path: Path | None = None,
) -> dict:
    """Create a competition attachment bound to the clean Git ``HEAD``."""

    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir).resolve()
    resolved_video = Path(video_path).resolve() if video_path is not None else None
    if resolved_video is not None and (
        not resolved_video.is_file() or resolved_video.suffix.lower() != ".mp4"
    ):
        raise SubmissionBundleError("video must be an existing MP4 file")
    if _run_git(repo_root, "status", "--porcelain"):
        raise SubmissionBundleError("Git worktree must be clean before packaging")

    commit = _run_git(repo_root, "rev-parse", "HEAD")
    short_commit = commit[:7]
    evidence_hashes = dict(expected_evidence_hashes or FORMAL_EVIDENCE_SHA256)
    for relative, expected in evidence_hashes.items():
        source = repo_root / relative
        if not source.is_file():
            raise SubmissionBundleError(f"formal Evidence is missing: {relative}")
        actual = _sha256(source)
        if actual != expected:
            raise SubmissionBundleError(
                f"formal Evidence SHA-256 mismatch: {relative}: expected {expected}, got {actual}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    video_status = "INCLUDED" if resolved_video is not None else "VIDEO_PENDING"
    bundle_suffix = "WITH-VIDEO" if resolved_video is not None else "NO-VIDEO"
    bundle = output_dir / f"LabOps-Guard-GOAI-复赛附件-{VERSION}-{short_commit}-{bundle_suffix}.zip"
    if bundle.exists():
        raise SubmissionBundleError(f"refusing to overwrite existing attachment: {bundle}")

    with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
        stage_root = Path(temporary) / "stage"
        stage_root.mkdir()
        _copy_required(repo_root, stage_root)

        source_name = f"LabOps-Guard-{VERSION}-{short_commit}-source.zip"
        source_path = stage_root / "02_代码包" / source_name
        source_path.parent.mkdir(parents=True)
        subprocess.run(
            [
                "git",
                "archive",
                "--format=zip",
                f"--prefix=LabOps-Guard-{VERSION}/",
                f"--output={source_path}",
                "HEAD",
            ],
            cwd=repo_root,
            check=True,
        )

        evidence_root = stage_root / "04_正式证据"
        evidence_root.mkdir(parents=True)
        for relative in evidence_hashes:
            shutil.copyfile(repo_root / relative, evidence_root / Path(relative).name)

        video_relative = "07_Demo视频/LabOps-Guard-GOAI-复赛-Demo.mp4"
        if resolved_video is None:
            (stage_root / "VIDEO_PENDING.txt").write_text(
                "Demo video is intentionally absent. Re-run scripts/build_submission_bundle.py "
                "with --video after the final MP4 passes privacy review.\n",
                encoding="utf-8",
            )
        else:
            video_destination = stage_root / video_relative
            video_destination.parent.mkdir(parents=True)
            shutil.copyfile(resolved_video, video_destination)
        manifest = {
            "schema_version": "1.0",
            "project": "LabOps-Guard",
            "version": VERSION,
            "classification": "COMPLETE_WITH_VIDEO" if resolved_video is not None else "SOURCE_ONLY_NO_VIDEO",
            "video_status": video_status,
            "git_commit": commit,
            "source_archive": f"02_代码包/{source_name}",
            "formal_evidence_sha256": evidence_hashes,
            "repository": "https://github.com/JAKIIC/LabOps-Guard",
            "public_demo": "https://jakiic.github.io/LabOps-Guard/",
            "runner_images_included": False,
        }
        if resolved_video is not None:
            manifest["video_path"] = video_relative
            manifest["video_sha256"] = _sha256(resolved_video)
        (stage_root / "FINAL_CANDIDATE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_checksums(stage_root)
        prefix = f"LabOps-Guard-GOAI-Semifinal-{VERSION}-{short_commit}/"
        _zip_tree(stage_root, bundle, prefix)

    verification = verify_submission_bundle(
        bundle,
        expected_evidence_hashes=evidence_hashes,
    )
    return {
        "status": "PASS",
        "commit": commit,
        "video_status": video_status,
        "bundle": str(bundle),
        "bundle_sha256": _sha256(bundle),
        "verified_file_count": verification["file_count"],
    }
