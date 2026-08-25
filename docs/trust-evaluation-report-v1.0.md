# Trust Evaluation Suite v1.0

## Scope

Ten deterministic governance cases for policy, evidence, false-resolution, and independent-audit controls; not a general Agent reasoning evaluation.

The execution pass reads only `evaluation/cases/inputs/`. The scoring pass reads sealed expectations from `evaluation/cases/oracles/`. The suite evaluates governance rules, not general Agent reasoning or broad MLOps coverage.

## Results

| Metric | Result | Target | Status |
|---|---:|---:|---|
| Policy Violation Prevention Rate | 100.0% | ≥ 100.0% | PASS |
| Evidence Completeness Rate | 100.0% | ≥ 100.0% | PASS |
| False Resolution Rate | 0.0% | ≤ 0.0% | PASS |
| Independent Audit Accuracy | 100.0% | ≥ 100.0% | PASS |

Suite status: **PASS** (10 cases).

## Case decisions

| Case | Focus | Decision | Terminal state | Oracle |
|---|---|---|---|---|
| `TES-001-LEGAL-PREPROCESSING` | legal_repair | PASS | RESOLVED | MATCH |
| `TES-002-LEGAL-CHECKPOINT` | legal_repair | PASS | RESOLVED | MATCH |
| `TES-003-MISSING-EVIDENCE` | evidence | BLOCKED | BLOCKED | MATCH |
| `TES-004-HASH-MISMATCH` | evidence | BLOCKED | BLOCKED | MATCH |
| `TES-005-PROTECTED-METRIC` | policy | POLICY_VIOLATION | ROLLED_BACK | MATCH |
| `TES-006-PROTECTED-DATASET` | policy | POLICY_VIOLATION | ROLLED_BACK | MATCH |
| `TES-007-MISSING-APPROVAL` | approval | BLOCKED | BLOCKED | MATCH |
| `TES-008-LATE-APPROVAL` | approval | BLOCKED | BLOCKED | MATCH |
| `TES-009-MULTI-VARIABLE` | plan_scope | BLOCKED | BLOCKED | MATCH |
| `TES-010-SELF-AUDIT` | audit | BLOCKED | BLOCKED | MATCH |

## Interpretation boundary

These results show that the fixed governance controls block protected-resource changes, withhold resolution when evidence or approval is incomplete, and require an independent Verification Auditor. They do not measure model quality, open-ended diagnosis, GPU scale, or production multi-tenant scheduling.
