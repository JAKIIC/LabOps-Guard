#!/usr/bin/env python3
"""Conservative tracked-source credential scan without printing secret values."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "assigned_secret": re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)\b\s*[:=]\s*['\"][^'\"\r\n]{8,}['\"]"),
}
TEXT_SUFFIXES = {".py", ".ps1", ".cmd", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".html", ".css", ".js"}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def scan(root: Path) -> dict:
    findings = []
    for path in tracked_files(root):
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append({"file": path.relative_to(root).as_posix(), "pattern": name})
    return {"status": "PASS" if not findings else "FAIL", "tracked_files_scanned": len(tracked_files(root)), "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    result = scan(args.repo_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
