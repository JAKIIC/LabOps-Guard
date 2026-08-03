"""Diagnosis engine: produce hypotheses from evidence. Every hypothesis MUST
carry >=1 evidence_id. No evidence -> UNKNOWN/BLOCKED (never a fabricated fact).

REAL, rule-based. No ML, no model-optimization suggestions.
"""

from __future__ import annotations

import json
from pathlib import Path


class NoEvidenceError(ValueError):
    """Raised when a hypothesis is created without any evidence_id."""


def build_hypothesis(
    hypothesis_id: str,
    claim: str,
    evidence_ids: list[str],
    state: str = "CANDIDATE",
    block_reason: str | None = None,
    suggested_action_id: str | None = None,
) -> dict:
    """Create a hypothesis dict. Rejects empty evidence_ids (mandatory rule)."""
    if not evidence_ids:
        raise NoEvidenceError(
            f"hypothesis {hypothesis_id} has no evidence_id; refusing to diagnose (no_evidence_no_diagnosis)"
        )
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "evidence_ids": list(evidence_ids),
        "state": state,
        "block_reason": block_reason,
        "suggested_action_id": suggested_action_id,
    }


def unknown_hypothesis(hypothesis_id: str, claim: str, reason: str) -> dict:
    """Explicit UNKNOWN hypothesis (no fabricated conclusion)."""
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "evidence_ids": [],
        "state": "UNKNOWN",
        "block_reason": reason,
        "suggested_action_id": None,
    }


def blocked_hypothesis(hypothesis_id: str, claim: str, reason: str) -> dict:
    """Explicit BLOCKED hypothesis (evidence missing; not guessed)."""
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "evidence_ids": [],
        "state": "BLOCKED",
        "block_reason": reason,
        "suggested_action_id": None,
    }


def diagnose_from_gaps(
    gaps: list[dict],
    workspace: str | Path,
    trace=None,
) -> dict:
    """Turn evidence gaps into hypotheses.

    Gap categories map to states:
      - data/config/artifact/environment gaps -> BLOCKED (need approval to act)
      - runtime/documentation gaps (BER not verifiable) -> UNKNOWN
      - private-test-label gap -> FORBIDDEN (never read/request)
    Every actionable hypothesis carries an evidence_id (= gap_id).
    """
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    forbidden_ids = {"GAP-009"}  # private test labels: forbidden

    hypotheses = []
    for g in gaps:
        gid = g.get("gap_id")
        title = g.get("title", "")
        cat = g.get("category", "")
        if gid in forbidden_ids:
            hypotheses.append({
                "hypothesis_id": f"H-{gid}",
                "claim": f"{title} (private test labels; forbidden to read/request)",
                "evidence_ids": [gid],
                "state": "FORBIDDEN",
                "block_reason": "forbidden action class; never read/request private test labels",
                "suggested_action_id": None,
            })
        elif cat == "runtime" or "not independently verifiable" in title or "not verifiable" in title:
            # GAP-007 has evidence (the gap itself); must carry evidence_id.
            # UNKNOWN state conveys no-fabricated-conclusion; evidence still referenced.
            hypotheses.append({
                "hypothesis_id": f"H-{gid}",
                "claim": title,
                "evidence_ids": [gid],
                "state": "UNKNOWN",
                "block_reason": "documented value not independently verifiable; recorded UNKNOWN, not asserted as fact",
                "suggested_action_id": None,
            })
        else:
            hypotheses.append(build_hypothesis(
                f"H-{gid}", title, [gid],
                state="BLOCKED",
                block_reason=f"missing evidence ({gid}); action requires approval",
                suggested_action_id=f"A-{gid}",
            ))

    record = {
        "incident_id": "incident-001",
        "hypothesis_count": len(hypotheses),
        "hypotheses": hypotheses,
    }
    (workspace / "diagnosis_candidates.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if trace:
        trace.append("incident", "incident-001", "diagnosis",
                     from_state="IN_PROGRESS", to_state="IN_PROGRESS",
                     extra={"hypotheses": len(hypotheses)})
    return record
