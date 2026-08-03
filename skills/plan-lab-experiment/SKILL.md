---
name: plan-lab-experiment
description: Create a minimal, evidence-grounded experiment plan for LabOps Guard incidents. Use after RCA produces a hypothesis and before any sandbox execution, especially for checkpoint regressions, one-variable repairs, budget/risk classification, success criteria, forbidden-change boundaries, and rollback design.
---

# Plan Lab Experiment

Convert one evidence-backed hypothesis into one bounded experiment plan. Never execute the plan or claim that it worked.

## Workflow

1. Require `hypothesis_id` and at least one resolvable `evidence_id`. Return `BLOCKED` if either is absent.
2. Select the smallest change that can falsify or support the hypothesis. Permit one changed variable per plan.
3. State the exact file, field, before value, and after value. Keep source data and metric implementations immutable.
4. Define a deterministic command, measurable success threshold, repeat count, CPU/runtime/network budget, and rollback action.
5. Classify risk:
   - `L0`: read-only inspection.
   - `L1`: reversible sandbox-only configuration change.
   - `L2`: workspace mutation requiring human approval.
   - `L3`: external, destructive, secret-bearing, or forbidden action; reject.
6. Validate the output against `references/io-schema.json` and the project `schemas/plan.schema.json`.
7. Hand the validated plan to the controlled executor. Do not bypass approval or verification.

## Checkpoint Regression Guardrails

- Allow only `eval_config.json: checkpoint`, from `checkpoints/last.pt` to `checkpoints/best.pt`.
- Require offline CPU execution, three repeats, accuracy at least `0.88`, and improvement at least `0.15`.
- Forbid changes to `metric.py`, datasets, labels, target thresholds, and checkpoint contents.
- Use a fresh sandbox and restore its snapshot on any policy or verification failure.

## Output

Return a JSON object containing `plan_id`, `hypothesis_id`, `objective`, exactly one item in `changes`, `command`, `success_criteria`, `budget`, `risk_level`, `approval_required`, `rollback`, and `forbidden_changes`.

Treat a rejected or blocked plan as a valid safety outcome. Never convert it into an executable suggestion.
