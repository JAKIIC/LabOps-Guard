"""Role-restricted incident state machine for the legacy compatibility flow.

New AgentTeams runs use ``agentteams/state_machine_v3.json``.  This module
remains stable so archived deterministic checkpoint workflows can be replayed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from labops.contracts import validate_document


TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("RECEIVED", "TRIAGED"): {"incident-commander"},
    ("TRIAGED", "EVIDENCE_COLLECTING"): {"incident-commander"},
    ("EVIDENCE_COLLECTING", "EVIDENCE_READY"): {"evidence-collector"},
    ("EVIDENCE_READY", "DIAGNOSING"): {"incident-commander"},
    ("DIAGNOSING", "HYPOTHESES_READY"): {"rca-analyst"},
    ("HYPOTHESES_READY", "PLAN_READY"): {"experiment-planner"},
    ("PLAN_READY", "POLICY_CHECKING"): {"incident-commander"},
    ("POLICY_CHECKING", "APPROVAL_PENDING"): {"incident-commander"},
    ("POLICY_CHECKING", "EXECUTING"): {"incident-commander"},
    ("POLICY_CHECKING", "VERIFYING"): {"incident-commander"},
    ("APPROVAL_PENDING", "EXECUTING"): {"incident-commander"},
    ("EXECUTING", "VERIFYING"): {"safe-executor"},
    ("VERIFYING", "RESOLVED"): {"verification-auditor"},
    ("VERIFYING", "FAILED"): {"verification-auditor"},
    ("FAILED", "ROLLED_BACK"): {"safe-executor"},
    ("ROLLED_BACK", "ARCHIVED"): {"incident-commander"},
    ("RESOLVED", "ARCHIVED"): {"incident-commander"},
}


class StateTransitionError(PermissionError):
    pass


class IncidentStateMachine:
    def __init__(self, incident_id: str, state_path: str | Path, trace):
        self.incident_id = incident_id
        self.state_path = Path(state_path)
        self.trace = trace

    def initialize(self) -> dict:
        record = self._write("RECEIVED", "incident-commander")
        self.trace.append(
            "incident",
            self.incident_id,
            "received",
            from_state=None,
            to_state="RECEIVED",
            actor="incident-commander",
            status="success",
        )
        return record

    def read(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def transition(self, to_state: str, actor: str) -> dict:
        current = self.read()["state"]
        allowed = TRANSITIONS.get((current, to_state), set())
        if actor not in allowed:
            raise StateTransitionError(f"{actor} cannot transition {current} -> {to_state}")
        record = self._write(to_state, actor)
        self.trace.append(
            "incident",
            self.incident_id,
            "state_transition",
            from_state=current,
            to_state=to_state,
            actor=actor,
            status="success",
        )
        return record

    def _write(self, state: str, actor: str) -> dict:
        record = {
            "schema_version": "1.0",
            "incident_id": self.incident_id,
            "state": state,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_by": actor,
        }
        validate_document(record, "state.schema.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record
