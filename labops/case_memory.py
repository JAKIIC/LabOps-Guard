"""Search and package lightweight, evidence-backed incident case memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


CASE_SCHEMA_VERSION = "1.0"
DEFAULT_CASE_ROOT = Path(__file__).resolve().parent.parent / "memory" / "cases"
TOKEN_RE = re.compile(r"[\w.-]+", re.UNICODE)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"case memory must be an object: {path}")
    if value.get("schema_version") != CASE_SCHEMA_VERSION:
        raise ValueError(f"unsupported case schema in {path}")
    if not value.get("incident_id") or not value.get("title"):
        raise ValueError(f"case memory missing incident_id/title: {path}")
    return value


def load_cases(root: str | Path = DEFAULT_CASE_ROOT) -> list[dict]:
    """Load valid case-memory JSON files without following external indexes."""
    case_root = Path(root).resolve()
    if not case_root.is_dir():
        return []
    return [_read_json(path) for path in sorted(case_root.glob("*.json")) if path.is_file()]


def search_cases(query: str = "", root: str | Path = DEFAULT_CASE_ROOT) -> list[dict]:
    """Return compact case summaries ranked by literal token matches."""
    terms = [token.lower() for token in TOKEN_RE.findall(query)]
    results = []
    for case in load_cases(root):
        haystack = json.dumps(case, ensure_ascii=False, sort_keys=True).lower()
        if terms and not all(term in haystack for term in terms):
            continue
        score = sum(haystack.count(term) for term in terms)
        results.append({
            "score": score,
            "incident_id": case["incident_id"],
            "title": case["title"],
            "final_state": case.get("final_state"),
            "failure_signature": case.get("failure_signature"),
            "top_hypothesis": case.get("diagnosis", {}).get("top_hypothesis"),
            "approved_change": case.get("resolution", {}).get("approved_change"),
            "source_bundle": case.get("evidence", {}).get("source_bundle"),
        })
    return sorted(results, key=lambda item: (-item["score"], item["incident_id"]))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_closure_bundle(source: str | Path, output: str | Path) -> dict:
    """Build a deterministic closure pack without modifying the source evidence bundle."""
    source_dir = Path(source).resolve()
    output_path = Path(output).resolve()
    required = ("postmortem.json", "case_memory.json", "postmortem.md")
    missing = [name for name in required if not (source_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"closure source missing: {', '.join(missing)}")
    manifest = {
        "schema_version": "1.0",
        "bundle_type": "incident_closure_v2",
        "files": [
            {"path": name, "sha256": _sha256(source_dir / name), "size": (source_dir / name).stat().st_size}
            for name in required
        ],
    }
    manifest_path = source_dir / "closure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in (*required, "closure_manifest.json"):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (source_dir / name).read_bytes())
    return {
        "status": "PASS",
        "bundle": str(output_path),
        "sha256": _sha256(output_path),
        "file_count": len(required) + 1,
        "manifest": str(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="search local incident case memory")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--root", default=str(DEFAULT_CASE_ROOT))
    pack = sub.add_parser("pack", help="build a deterministic incident closure bundle")
    pack.add_argument("--source", required=True)
    pack.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = search_cases(args.query, args.root) if args.command == "search" else build_closure_bundle(args.source, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
