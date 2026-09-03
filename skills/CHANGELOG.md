# Skill changelog

## Atomic AgentTeams handoffs - 2026-09-03

- Upgraded the six event-emitting Skills with one positive completion recipe: validate the
  canonical output, invoke the deployed atomic emitter once, and accept only `EMITTED` or
  `ALREADY_EMITTED` as a completed Handoff.
- Bound Planner completion to `approval_pending`, Executor completion to
  `executor_to_auditor`, Auditor completion to `verification_completed`, and final Manager
  publication to `commander_published`.
- This patch changes orchestration reliability only; it does not change incident facts,
  approval authority, Runner behavior, or formal AT-002/003/004 Evidence.

## plan-lab-experiment 0.2.1 - 2026-08-26

- Classified planning itself as `read_only_auto`; a generated plan still carries its own
  `approval_required` flag and must pass the separate Policy and Human Approval gates before
  Safe Executor may invoke a tool.

## 0.2.0 - 2026-08-06

- Added explicit skill and I/O schema versions to all six supported skills.
- Documented cross-project reuse, multi-agent handoffs, lifecycle boundaries, and fail-closed
  structured errors.
- Generalized experiment planning from a checkpoint-only recipe to evidence-backed,
  one-variable patterns, including the AT-004 evaluation-profile repair.
- Removed the unused `execute-controlled-action` scaffold. `control-lab-action` remains the
  supported Safe Executor skill.
- Added `publish-case-memory` as an Incident Commander capability; it does not create a seventh
  Agent or alter the core state machine.

## 0.1.0

- Initial six-skill LabOps Guard workflow.
