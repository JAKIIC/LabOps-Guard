"""Verification closer: post-action checks; only a REAL non-simulated action with
>=1 concrete postcondition can CLOSE an incident.

Closure semantics (REV-1):
- DRY_RUN / SIMULATED actions only demonstrate the control flow / audit chain;
  they NEVER indicate root-cause resolution.
- With no concrete postcondition (expected_artifact / postcondition list), the
  incident must NOT close.
- A real non-simulated action + >=1 postcondition all passing -> CLOSED.
- Demo / simulated -> demo_verification=PASSED but incident_state=BLOCKED
  (or DEMO_PASSED_NOT_RESOLVED) and underlying_issue_resolved=false.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# severity for closure
CLOSED = "CLOSED"
BLOCKED = "BLOCKED"
DEMO_PASSED_NOT_RESOLVED = "DEMO_PASSED_NOT_RESOLVED"


def _inside_boundary(path: Path, workspace: Path) -> bool:
    try:
        path.resolve().relative_to(workspace.resolve())
        return True
    except ValueError:
        return False


def _postconditions_ok(checks: list[dict]) -> bool:
    # only existence/hash checks count as concrete postconditions
    concrete = [c for c in checks if c.get("kind") in ("artifact_exists", "hash_match")]
    if not concrete:
        return False
    return all(c["passed"] for c in concrete)


def verify_action(
    action_result: dict,
    workspace: str | Path,
    expected_artifact: str | None = None,
    expected_hash: str | None = None,
    postconditions: list[dict] | None = None,
    trace=None,
) -> dict:
    workspace = Path(workspace)
    # AgentTeams envelopes execution fields under ``result`` while the local
    # CLI historically emitted them at the top level. Accept both shapes and
    # let explicit top-level values win for backward compatibility.
    nested_result = action_result.get("result")
    if not isinstance(nested_result, dict):
        nested_result = {}
    status = action_result.get("status", nested_result.get("status"))
    simulated = bool(action_result.get("simulated", nested_result.get("simulated", False)))
    dry_run = bool(action_result.get("dry_run", nested_result.get("dry_run", False)))
    is_demo_like = simulated or dry_run

    checks: list[dict] = []

    # 1. action status: only SUCCEEDED (non-forbidden, non-timeout) passes
    action_ok = status == "SUCCEEDED"
    checks.append({"check": "action_status_ok", "passed": action_ok,
                   "detail": status, "kind": "action_status"})

    # 2. concrete postconditions (expected_artifact / expected_hash)
    has_postcondition = False
    if expected_artifact:
        ap = Path(expected_artifact)
        if not _inside_boundary(ap, workspace):
            checks.append({"check": "artifact_within_workspace", "passed": False,
                           "detail": f"{ap} outside workspace", "kind": "boundary"})
        else:
            exists = ap.exists()
            checks.append({"check": "artifact_exists", "passed": exists,
                           "detail": str(ap), "kind": "artifact_exists"})
            has_postcondition = has_postcondition or exists
            if exists and expected_hash:
                import hashlib
                h = hashlib.sha256(ap.read_bytes()).hexdigest()
                hm = h == expected_hash
                checks.append({"check": "hash_match", "passed": hm,
                               "detail": f"expected={expected_hash[:12]}... got={h[:12]}...",
                               "kind": "hash_match"})
                has_postcondition = True
    if postconditions:
        for pc in postconditions:
            checks.append({**pc, "kind": pc.get("kind", "postcondition")})
            has_postcondition = True

    all_passed = all(c["passed"] for c in checks)

    # demo_verification: did the control-flow / audit chain demonstrate correctly?
    demo_verification = "PASSED" if all_passed else "FAILED"

    # closure decision
    if (not is_demo_like) and all_passed and has_postcondition:
        incident_state = CLOSED
        underlying_issue_resolved = True
    elif is_demo_like and all_passed:
        incident_state = DEMO_PASSED_NOT_RESOLVED
        underlying_issue_resolved = False
    else:
        incident_state = BLOCKED
        underlying_issue_resolved = False

    # 'status' retained for backward compat: verification of the checks themselves
    vstatus = "PASSED" if all_passed else (
        "NOT_VERIFIED" if status in ("TIMEOUT", "FORBIDDEN", "SKIPPED") else "FAILED"
    )

    result = {
        "incident_id": "incident-001",
        "checks": checks,
        "status": vstatus,
        "demo_verification": demo_verification,
        "incident_state": incident_state,
        "underlying_issue_resolved": underlying_issue_resolved,
        "is_demo_like": is_demo_like,
        "has_postcondition": has_postcondition,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (workspace / "verification_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if trace:
        trace.append("incident", "incident-001", "verification",
                     from_state="IN_PROGRESS", to_state=incident_state,
                     extra={"verification_status": vstatus,
                            "demo_verification": demo_verification,
                            "underlying_issue_resolved": underlying_issue_resolved,
                            "is_demo_like": is_demo_like,
                            "has_postcondition": has_postcondition})
    return result
