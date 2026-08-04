#!/usr/bin/env python3
"""Independently verify LABOPS-AT-002/003 evidence archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_trace(raw: bytes) -> tuple[bool, str]:
    previous = None
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    for index, record in enumerate(records):
        if record.get("seq") != index or record.get("prev_hash") != previous:
            return False, f"chain link mismatch at seq {index}"
        canonical = json.dumps({k: v for k, v in record.items() if k != "hash"}, ensure_ascii=False, sort_keys=True)
        expected = sha256(canonical.encode("utf-8"))
        if record.get("hash") != expected:
            return False, f"record hash mismatch at seq {index}"
        previous = expected
    return bool(records), f"chain ok, {len(records)} entries"


def verify_bundle(bundle_path: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    bundle_raw = bundle_path.read_bytes()
    if sha256(bundle_raw) != manifest.get("zip_sha256"):
        errors.append("bundle SHA-256 mismatch")
    with zipfile.ZipFile(bundle_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("duplicate ZIP member")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                errors.append(f"unsafe ZIP member: {name}")
        expected = manifest.get("artifacts", {})
        if set(names) != set(expected):
            errors.append("ZIP member set differs from manifest")
        for name, expected_hash in expected.items():
            try:
                if sha256(archive.read(name)) != expected_hash:
                    errors.append(f"artifact hash mismatch: {name}")
            except KeyError:
                errors.append(f"missing artifact: {name}")

        task_id = manifest.get("task_id")
        trace_results = {}
        if task_id == "LABOPS-AT-002":
            for name in ("artifacts/DEMO-RCA-001/trace.jsonl", "artifacts/DEMO-RCA-002/trace.jsonl"):
                ok, message = verify_trace(archive.read(name))
                trace_results[name] = {"ok": ok, "message": message}
                if not ok:
                    errors.append(f"trace failed: {name}")
            if manifest.get("final_state") != "BLOCKED":
                errors.append("AT-002 final state changed")
        elif task_id == "LABOPS-AT-003":
            ok, message = verify_trace(archive.read("agentteams_trace.jsonl"))
            trace_results["agentteams_trace.jsonl"] = {"ok": ok, "message": message}
            final_audit = json.loads(archive.read("agentteams_trace_audit_final.json"))
            if not ok or final_audit.get("decision") not in ("ACCEPTED", "CHAIN_OK") and final_audit.get("status") != "CHAIN_OK":
                errors.append("AT-003 final trace audit failed")
            runner_manifest = json.loads(archive.read("artifact_manifest.json")).get("artifacts", {})
            for name, record in runner_manifest.items():
                raw = archive.read(name)
                if sha256(raw) != record.get("sha256") or len(raw) != record.get("size"):
                    errors.append(f"runner manifest mismatch: {name}")
            verification = json.loads(archive.read("verification.json"))
            if verification.get("decision") != "PASS" or verification.get("resolution_status") != "RESOLVED":
                errors.append("AT-003 verification is not PASS / RESOLVED")
        else:
            errors.append(f"unexpected task_id: {task_id}")
    return {
        "task_id": manifest.get("task_id"),
        "status": "PASS" if not errors else "FAIL",
        "bundle": str(bundle_path),
        "sha256": sha256(bundle_raw),
        "artifact_count": len(manifest.get("artifacts", {})),
        "trace": trace_results,
        "errors": errors,
    }


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--at002-bundle", type=Path, default=root / "demo/output-agentteams-at002/LABOPS-AT-002-evidence-bundle.zip")
    parser.add_argument("--at002-manifest", type=Path, default=root / "demo/output-agentteams-at002/evidence_bundle_manifest.json")
    parser.add_argument("--at003-bundle", type=Path, default=root / "demo/output-agentteams-at003/artifacts/DEMO-RCA-003/LABOPS-AT-003-evidence-bundle.zip")
    parser.add_argument("--at003-manifest", type=Path, default=root / "demo/output-agentteams-at003/artifacts/DEMO-RCA-003/evidence_bundle_manifest.json")
    args = parser.parse_args()
    results = [
        verify_bundle(args.at002_bundle.resolve(), args.at002_manifest.resolve()),
        verify_bundle(args.at003_bundle.resolve(), args.at003_manifest.resolve()),
    ]
    print(json.dumps({"status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL", "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "PASS" for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
