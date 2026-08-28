#!/usr/bin/env python3
"""Build the commit-bound GOAI semifinal attachment from the current commit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labops.submission_bundle import SubmissionBundleError, build_submission_bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a commit-bound LabOps-Guard semifinal attachment without Runner images."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="clean LabOps-Guard Git worktree (default: repository root)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("release"),
        help="ignored directory that receives the final attachment (default: release)",
    )
    parser.add_argument(
        "--video",
        type=Path,
        default=None,
        help="optional final privacy-reviewed MP4; omit to build the VIDEO_PENDING candidate",
    )
    args = parser.parse_args()
    try:
        result = build_submission_bundle(args.repo_root, args.output_dir, video_path=args.video)
    except (SubmissionBundleError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
