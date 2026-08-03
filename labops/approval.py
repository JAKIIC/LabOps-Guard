"""Approval gate: classify actions (read-only auto / manual / forbidden),
track approve/reject/timeout. Rejection & timeout are first-class states.

REAL policy enforcement. Action execution is gated on approval.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

READ_ONLY_AUTO = "read_only_auto"
MANUAL_APPROVAL = "manual_approval"
FORBIDDEN = "forbidden"

# severity: higher is stricter
_SEVERITY = {READ_ONLY_AUTO: 1, MANUAL_APPROVAL: 2, FORBIDDEN: 3}

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 3600


class ActionForbiddenError(Exception):
    """Action is in forbidden class; refused even if approved."""


class PolicyDowngradeError(ValueError):
    """Explicit action-class attempts to downgrade a stricter inferred class."""

def _infer_class(command: str) -> str:
    low = command.lower()
    # forbidden heuristics
    if any(m in low for m in [
        "test_codeword_x_private", "test_noisy_y_public",
        "train_codeword_x_shard", "train_noisy_y_shard",
        "submit_sample.csv", "submission.csv", ".npz", ".pt", ".pem", ".key",
    ]):
        return FORBIDDEN
    if "sudo" in low or "chmod" in low or "rm -rf" in low or "del /" in low:
        return FORBIDDEN
    if low.startswith(("pip install", "pip3 install", "wget ", "curl ", "git clone")):
        return MANUAL_APPROVAL
    if low.startswith(("python baseline.py", "python3 baseline.py", "train", "download")):
        return MANUAL_APPROVAL
    return READ_ONLY_AUTO


def classify_action(
    action_id: str,
    command: str,
    action_class: str | None = None,
) -> str:
    """Determine effective action class.

    If an explicit action_class is given, it may only be equal-or-stricter than
    the inferred class. Attempting to downgrade a stricter inferred class
    (e.g. forbidden -> read_only_auto) raises PolicyDowngradeError.
    """
    inferred = _infer_class(command)
    if action_class is None:
        return inferred
    if _SEVERITY[action_class] < _SEVERITY[inferred]:
        raise PolicyDowngradeError(
            f"action {action_id}: explicit class {action_class} downgrades inferred "
            f"{inferred}; refusing (no_approval_no_execution)"
        )
    return action_class


def create_approval(
    approval_id: str,
    hypothesis_id: str,
    action_id: str,
    command: str,
    action_class: str,
    workspace: str | Path,
    trace=None,
) -> dict:
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    req = {
        "approval_id": approval_id,
        "hypothesis_id": hypothesis_id,
        "action_id": action_id,
        "command": command,
        "action_class": action_class,
        "status": "PENDING",
        "requested_by": "labops",
        "decided_by": None,
        "decided_at": None,
        "reason": None,
    }
    _append_req(workspace, req)
    if trace:
        trace.append("approval", approval_id, "requested",
                     from_state=None, to_state="PENDING",
                     extra={"action_class": action_class, "command": command})
    return req


def decide(
    approval_id: str,
    decision: str,
    workspace: str | Path,
    decided_by: str = "human-approver",
    reason: str | None = None,
    trace=None,
) -> dict:
    """Approve or reject an approval. decision in {approve, reject}."""
    workspace = Path(workspace)
    reqs = load_approvals(workspace)
    req = next((r for r in reqs if r["approval_id"] == approval_id), None)
    if req is None:
        raise KeyError(f"approval {approval_id} not found")
    decision = decision.lower()
    if decision == "approve":
        req["status"] = "APPROVED"
    elif decision == "reject":
        req["status"] = "REJECTED"
    else:
        raise ValueError(f"invalid decision: {decision}")
    req["decided_by"] = decided_by
    req["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    req["reason"] = reason
    _append_req(workspace, req)
    if trace:
        trace.append("approval", approval_id, "decided",
                     from_state="PENDING", to_state=req["status"],
                     extra={"decision": decision, "decided_by": decided_by})
    return req


def mark_timeout(approval_id: str, workspace: str | Path, trace=None) -> dict:
    workspace = Path(workspace)
    reqs = load_approvals(workspace)
    req = next((r for r in reqs if r["approval_id"] == approval_id), None)
    if req is None:
        raise KeyError(f"approval {approval_id} not found")
    req["status"] = "TIMEOUT"
    req["reason"] = "approval timeout exceeded"
    _append_req(workspace, req)
    if trace:
        trace.append("approval", approval_id, "timeout",
                     from_state="PENDING", to_state="TIMEOUT")
    return req


def is_approved(approval_id: str, workspace: str | Path) -> bool:
    reqs = load_approvals(workspace)
    req = next((r for r in reqs if r["approval_id"] == approval_id), None)
    return req is not None and req["status"] == "APPROVED"


def load_approvals(workspace: str | Path) -> list[dict]:
    workspace = Path(workspace)
    p = workspace / "approval_requests.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _append_req(workspace: Path, req: dict):
    p = workspace / "approval_requests.json"
    reqs = load_approvals(workspace)
    # replace by id (upsert) so decisions update the same approval
    reqs = [r for r in reqs if r["approval_id"] != req["approval_id"]]
    reqs.append(req)
    p.write_text(json.dumps(reqs, ensure_ascii=False, indent=2), encoding="utf-8")
