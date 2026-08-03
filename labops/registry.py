"""Snapshot registry: register allowed files + SHA-256 + verification.

REAL component. Reads only allowed snapshot files; computes hashes; optionally
cross-checks against a verification JSON (e.g. snapshot_verification.json).
Never reads excluded data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from labops.evidence import is_excluded


class PathEscapeError(PermissionError):
    """Raised when an allowed-file path escapes the snapshot dir or is excluded."""


def _inside(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def register_snapshot(
    snapshot_dir: str | Path,
    allowed_files: list[str],
    workspace: str | Path,
    verification_json: str | Path | None = None,
    trace=None,
    project_ref: str = "polar-baseline",
) -> dict:
    """Register allowed files with hashes; optionally verify against JSON.

    Returns a registry record dict. Writes registry_record.json into workspace.
    """
    snapshot_dir = Path(snapshot_dir)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    snapshot_root = snapshot_dir.resolve()

    entries = []
    missing = []
    refused = []
    for rel in allowed_files:
        # fail closed on excluded markers
        if is_excluded(rel):
            refused.append({"path": rel, "reason": "excluded_marker"})
            entries.append({"path": rel, "sha256": None, "present": False,
                            "refused": "excluded_marker"})
            continue
        full = (snapshot_dir / rel).resolve()
        # fail closed on path escape (../ or absolute traversal)
        if not _inside(snapshot_root, full):
            refused.append({"path": rel, "reason": "path_escape"})
            entries.append({"path": rel, "sha256": None, "present": False,
                            "refused": "path_escape"})
            continue
        if not full.exists():
            missing.append(rel)
            entries.append({"path": rel, "sha256": None, "present": False})
        else:
            entries.append(
                {"path": rel, "sha256": sha256_file(full), "present": True, "size": full.stat().st_size}
            )

    verification = None
    verification_status = None
    if verification_json:
        vp = Path(verification_json)
        if vp.exists():
            verification = json.loads(vp.read_text(encoding="utf-8"))
            verification_status = verification.get("verification")

    # cross-check hashes against verification if available
    mismatches = []
    if verification and verification_status == "VERIFIED":
        expected = verification.get("all_allowed_file_sha256", {})
        for e in entries:
            if e["present"] and e["path"] in expected and expected[e["path"]] != e["sha256"]:
                mismatches.append(e["path"])

    record = {
        "incident_id": "incident-001",
        "project_ref": project_ref,
        "snapshot_dir": str(snapshot_dir),
        "allowed_file_count": len(allowed_files),
        "entries": entries,
        "missing": missing,
        "refused": refused,
        "verification_status": verification_status,
        "hash_mismatches_vs_verification": mismatches,
        "excluded_data_not_read": True,
    }
    (workspace / "registry_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if trace:
        trace.append("incident", record["incident_id"], "registry",
                     from_state="OPEN", to_state="IN_PROGRESS",
                     extra={"allowed_count": len(allowed_files), "missing": missing})
    return record
