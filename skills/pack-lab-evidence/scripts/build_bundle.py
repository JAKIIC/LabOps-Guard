#!/usr/bin/env python3
"""Build an allowlisted LabOps Guard evidence ZIP with SHA-256 manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import zipfile
from pathlib import Path


REQUIRED = (
    "registry_record.json",
    "collected_evidence.json",
    "diagnosis_candidates.json",
    "verification_result.json",
    "trace.jsonl",
)
OPTIONAL = (
    "approval_requests.json",
    "execution_result.json",
    "demo/demo_summary.json",
    "demo/demo_transcript.txt",
)
EXPLICIT_EXCLUSIONS = (
    "source snapshots",
    "training/test datasets",
    "private labels",
    "archives",
    "secrets and environment files",
    "checkpoints and calibration artifacts",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def build_bundle(workspace: str | Path, output: str | Path) -> dict:
    workspace = Path(workspace).resolve()
    output = Path(output).resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace not found: {workspace}")
    if not _inside(output, workspace):
        raise PermissionError("output must stay inside workspace")

    missing_required = [rel for rel in REQUIRED if not (workspace / rel).is_file()]
    if missing_required:
        raise FileNotFoundError(f"required artifacts missing: {missing_required}")

    included = []
    missing_optional = []
    for rel in REQUIRED + OPTIONAL:
        path = workspace / rel
        if path.is_file():
            included.append({"path": rel, "sha256": _sha256(path), "size": path.stat().st_size})
        elif rel in OPTIONAL:
            missing_optional.append(rel)

    verification = json.loads((workspace / "verification_result.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": "1.0",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "incident_state": verification.get("incident_state", "UNKNOWN"),
        "underlying_issue_resolved": bool(verification.get("underlying_issue_resolved", False)),
        "included_artifacts": included,
        "missing_optional": missing_optional,
        "explicit_exclusions": list(EXPLICIT_EXCLUSIONS),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in included:
            bundle.write(workspace / item["path"], arcname=item["path"])
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return {
        "bundle": str(output),
        "bundle_sha256": _sha256(output),
        **manifest,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_bundle(args.workspace, args.output)
    except (ValueError, PermissionError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(f"EVIDENCE_PACK_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
