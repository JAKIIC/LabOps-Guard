# Skill changelog

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
