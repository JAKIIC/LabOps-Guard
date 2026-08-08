"""Evidence collection: load audit evidence (strong/weak/missing) + gaps.

REAL component. Loads evidence_index.json and evidence_gaps.json from a
compatibility audit; records states. Never reads excluded data.
"""

from __future__ import annotations

import json
from pathlib import Path

# Paths that are FORBIDDEN to touch (excluded data / private labels / keys).
EXCLUDED_MARKERS = [
    "test_noisy_y_public.csv",
    "test_codeword_x_private.csv",
    "train_codeword_x_shard_",
    "train_noisy_y_shard_",
    "submit_sample.csv",
    "submission.csv",
    ".npz",  # calibration artifacts are treated as excluded (not read)
    ".pt",   # model checkpoints excluded
    ".pem", ".key", ".p12",  # secrets
]


def is_excluded(rel_path: str) -> bool:
    low = rel_path.lower()
    return any(m.lower() in low for m in EXCLUDED_MARKERS)


def collect_evidence(
    audit_dir: str | Path,
    workspace: str | Path,
    trace=None,
) -> dict:
    """Load evidence_index + evidence_gaps; produce collected_evidence.json."""
    audit_dir = Path(audit_dir)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    ev_idx_path = audit_dir / "evidence_index.json"
    gaps_path = audit_dir / "evidence_gaps.json"

    evidence_items = []
    if ev_idx_path.exists():
        ev_idx = json.loads(ev_idx_path.read_text(encoding="utf-8"))
        for it in ev_idx.get("evidence", []):
            evidence_items.append(
                {
                    "evidence_id": it.get("id"),
                    "strength": it.get("strength"),
                    "claim": it.get("claim"),
                    "refs": it.get("refs", []),
                    "status": "CONFIRMED" if it.get("strength") == "strong" else (
                        "PARTIAL" if it.get("strength") == "weak" else "MISSING"
                    ),
                }
            )

    gaps = []
    if gaps_path.exists():
        gaps_doc = json.loads(gaps_path.read_text(encoding="utf-8"))
        for g in gaps_doc.get("gaps", []):
            gaps.append(
                {
                    "gap_id": g.get("id"),
                    "category": g.get("category"),
                    "title": g.get("title"),
                    "status": "MISSING",  # all gaps are missing evidence by definition
                }
            )

    record = {
        "incident_id": "incident-001",
        "evidence_count": len(evidence_items),
        "gaps_count": len(gaps),
        "evidence": evidence_items,
        "gaps": gaps,
        "excluded_data_not_read": True,
    }
    (workspace / "collected_evidence.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if trace:
        trace.append("incident", "incident-001", "evidence_collected",
                     from_state="IN_PROGRESS", to_state="IN_PROGRESS",
                     extra={"evidence": len(evidence_items), "gaps": len(gaps)})
    return record


def collect_from_files(
    allowed_files: list[str],
    workspace: str | Path,
    trace=None,
) -> dict:
    """Scan allowed files; any excluded marker encountered -> flagged (should not happen)."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    hits = [f for f in allowed_files if is_excluded(f)]
    record = {
        "scanned": len(allowed_files),
        "excluded_hits": hits,
        "ok": len(hits) == 0,
    }
    (workspace / "file_scan.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if trace and hits:
        trace.append("incident", "incident-001", "excluded_data_encountered",
                     from_state="IN_PROGRESS", to_state="BLOCKED",
                     extra={"hits": hits})
    return record
