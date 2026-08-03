# AgentTeams integration mapping

`LABOPS-AT-001` maps the local LabOps Guard pipeline to five distinct AgentTeams identities.
AgentTeams owns orchestration, assignment, handoff messages, and shared task state. The
LabOps CLI and Skills own deterministic evidence operations and policy enforcement.

| Pipeline stage | Agent | Skill | Required handoff artifact |
|---|---|---|---|
| Receive and route | LabOps Manager | `pack-lab-evidence` at completion | task/state contract |
| Snapshot and evidence | Evidence Collector | `collect-lab-evidence` | registry + evidence JSON |
| Evidence-bound diagnosis | RCA Analyst | `diagnose-lab-incident` | hypothesis JSON |
| Approval and action | Controlled Executor | `control-lab-action` | approval + action JSON |
| Independent verification | Verification Auditor | `verify-lab-result` | verification + trace result |

## Context handoff contract

Every AgentTeams handoff must include:

- `task_id`, `incident_id`, current state, and proposed next state;
- input artifact paths and SHA-256 where available;
- output artifact paths and validation status;
- policy class and human decision when an action is involved;
- unresolved evidence gaps and an explicit `blocked_reason` when work cannot continue.

Natural-language conclusions never replace the structured artifacts. The Manager may route
work but may not execute or self-verify it. The Verifier must derive its decision from action
records and postconditions rather than from the Executor's summary.

## Demo sequence

1. Post `agentteams/prompts/manager_task.md` in the Manager room.
2. Observe at least four cross-role assignments and record their Matrix event links.
3. Confirm final state is `DEMO_PASSED_NOT_RESOLVED`, not `CLOSED`.
4. Preserve the final response, screenshots, generated artifacts, and trace verification for
   the competition evidence package.
