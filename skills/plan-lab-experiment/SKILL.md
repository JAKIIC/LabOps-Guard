---
name: plan-lab-experiment
description: Create a minimal, evidence-grounded experiment plan for LabOps Guard incidents. Use after RCA produces a hypothesis and before any sandbox execution, especially for checkpoint regressions, one-variable repairs, budget/risk classification, success criteria, forbidden-change boundaries, and rollback design.
---

# Plan Lab Experiment

Runtime registry binding: `skills/registry.json#plan-lab-experiment`. Registry authorization and
I/O validation fail closed before this Skill is invoked.

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

## Supported bounded patterns

- Checkpoint repair: allow only `eval_config.json: checkpoint`, from the evidenced current
  checkpoint to the evidenced reference checkpoint.
- Evaluation-profile repair: allow only the evidenced preprocessing field, from the observed
  drifted value to the registered historical value.
- Other repositories may define another one-variable pattern, but it must be expressed in the
  assignment and policy allowlist, cite evidence, remain reversible, and pass the same schema.
- Require offline CPU execution, finite runtime and repeat budgets, measurable thresholds, and
  a fresh sandbox. Forbid changes to metric implementations such as `metric.py`, datasets,
  labels, checkpoints, evaluation
  protocols, target thresholds, and the original workspace unless the policy explicitly marks
  a different protected set.

## Version, reuse, and lifecycle

- Skill version: `0.2.0`; I/O schema version: `1.0`.
- Input lifecycle: `DIAGNOSIS_READY` -> `PLANNING`. Output lifecycle: `PLAN_READY`, `REJECTED`,
  or `BLOCKED`; planning never implies approval or execution.
- In a multi-agent run, consume one RCA hypothesis routed by the Incident Commander and hand a
  schema-valid plan to the Safe Executor through the Manager and approval gate.
- On missing evidence, unsupported change patterns, invalid budgets, absent rollback, or schema
  failure, return the structured error object defined in `references/io-schema.json`. Do not
  convert a rejected plan into natural-language execution advice.

## Output

Return a JSON object containing `plan_id`, `hypothesis_id`, `objective`, exactly one item in `changes`, `command`, `success_criteria`, `budget`, `risk_level`, `approval_required`, `rollback`, and `forbidden_changes`.

Treat a rejected or blocked plan as a valid safety outcome. Never convert it into an executable suggestion.
