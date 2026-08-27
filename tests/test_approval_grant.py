"""ApprovalGrant v1 strong-binding and replay-protection contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from labops.approval_grant import (
    ApprovalBindingError,
    canonical_plan_sha256,
    consume_approval_nonce,
    validate_approval_grant,
)


NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def plan() -> dict:
    return {
        "task_id": "LABOPS-AT-004-EVAL-DRIFT",
        "incident_id": "DEMO-EVAL-DRIFT-004",
        "plan_id": "PLAN-LABOPS-AT-004-001",
        "run_id": "RUN-LABOPS-AT-004-AGENTTEAMS-101",
        "changes": [
            {
                "file": "eval_config.json",
                "field": "evaluation.preprocessing_profile",
                "before": "train_augmented",
                "after": "eval_standard",
            }
        ],
        "budget": {"max_runtime_seconds": 30, "device": "cpu", "network": False},
        "forbidden_changes": ["metric.py", "validation_data.pt", "checkpoint"],
    }


def tool_contract(p: dict) -> dict:
    return {
        "task_id": p["task_id"],
        "incident_id": p["incident_id"],
        "run_id": p["run_id"],
        "approval_reference": "APR-LIVE-101",
        "allowed_side_effects": ["write sandbox output"],
        "protected_resources": list(p["forbidden_changes"]),
        "resource_budget": dict(p["budget"]),
    }


def grant(p: dict) -> dict:
    return {
        "schema_version": "1.0",
        "approval_id": "APR-LIVE-101",
        "task_id": p["task_id"],
        "incident_id": p["incident_id"],
        "plan_id": p["plan_id"],
        "canonical_plan_sha256": canonical_plan_sha256(p),
        "run_id": p["run_id"],
        "decision": "APPROVED",
        "approved_scope": ["eval_config.json:evaluation.preprocessing_profile"],
        "allowed_side_effects": ["write sandbox output"],
        "protected_resources": list(p["forbidden_changes"]),
        "resource_budget": dict(p["budget"]),
        "decided_by": "human-operator",
        "approved_at": "2026-08-29T11:55:00Z",
        "expires_at": "2026-08-29T12:05:00Z",
        "nonce": "nonce-live-101",
    }


class TestApprovalGrant(unittest.TestCase):
    def assert_reason(self, expected: str, p: dict, g: dict, contract: dict) -> None:
        with self.assertRaises(ApprovalBindingError) as caught:
            validate_approval_grant(p, g, contract, now=NOW)
        self.assertEqual(caught.exception.reason, expected)

    def test_canonical_hash_is_stable_across_key_order(self) -> None:
        p = plan()
        reordered = json.loads(json.dumps(p, sort_keys=True))
        self.assertEqual(
            canonical_plan_sha256(p),
            canonical_plan_sha256(reordered),
        )

    def test_valid_grant_binds_plan_scope_budget_and_human(self) -> None:
        p = plan()
        result = validate_approval_grant(p, grant(p), tool_contract(p), now=NOW)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["approval_id"], "APR-LIVE-101")
        self.assertEqual(result["canonical_plan_sha256"], canonical_plan_sha256(p))

    def test_modified_plan_fails_closed(self) -> None:
        p = plan()
        g = grant(p)
        p["changes"][0]["after"] = "another-profile"
        self.assert_reason("PLAN_HASH_MISMATCH", p, g, tool_contract(p))

    def test_expanded_scope_fails_closed(self) -> None:
        p = plan()
        g = grant(p)
        g["approved_scope"].append("metric.py:target")
        self.assert_reason("SCOPE_MISMATCH", p, g, tool_contract(p))

    def test_increased_budget_fails_closed(self) -> None:
        p = plan()
        g = grant(p)
        g["resource_budget"]["max_runtime_seconds"] = 60
        self.assert_reason("BUDGET_MISMATCH", p, g, tool_contract(p))

    def test_expired_grant_fails_closed(self) -> None:
        p = plan()
        g = grant(p)
        g["expires_at"] = "2026-08-29T11:59:59Z"
        self.assert_reason("APPROVAL_EXPIRED", p, g, tool_contract(p))

    def test_agent_cannot_approve_its_own_execution(self) -> None:
        p = plan()
        g = grant(p)
        g["decided_by"] = "safe-executor"
        self.assert_reason("SCOPE_MISMATCH", p, g, tool_contract(p))

    def test_wrong_contract_version_fails_closed(self) -> None:
        p = plan()
        g = grant(p)
        g["schema_version"] = "2.0"
        self.assert_reason("SCOPE_MISMATCH", p, g, tool_contract(p))

    def test_nonce_is_single_use_and_persisted(self) -> None:
        p = plan()
        g = grant(p)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "approval_nonce_ledger.json"
            first = consume_approval_nonce(g, ledger)
            self.assertEqual(first["status"], "CONSUMED")
            with self.assertRaises(ApprovalBindingError) as caught:
                consume_approval_nonce(g, ledger)
            self.assertEqual(caught.exception.reason, "APPROVAL_REPLAYED")
            persisted = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(persisted[0]["nonce"], "nonce-live-101")


if __name__ == "__main__":
    unittest.main(verbosity=2)
