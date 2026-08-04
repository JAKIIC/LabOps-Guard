#!/usr/bin/env python3
"""Run AT-003 three times using an optional portable baseline fixture."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from labops.at003 import run_local_validation


def extract_fixture(archive_path: Path, target: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe fixture member: {info.filename}")
        archive.extractall(target)
    candidate = target / "run-01"
    baseline = candidate if candidate.is_dir() else target
    required = ["eval_config.json", "checkpoints/last.pt", "checkpoints/best.pt"]
    if not all((baseline / item).is_file() for item in required):
        raise ValueError("fixture does not contain a complete run-01 baseline")
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fixture-zip", type=Path)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    baseline = extract_fixture(args.fixture_zip.resolve(), output / "input-fixture") if args.fixture_zip else None
    result = run_local_validation(args.repo_root.resolve(), output, baseline_run=baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" and result.get("resolution_status") == "RESOLVED" else 1


if __name__ == "__main__":
    sys.exit(main())
