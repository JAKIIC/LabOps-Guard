# Skill integration matrix

LabOps Guard ships seven repository-native Skills. They are executable contracts, not role prompts.
Every Skill contains `SKILL.md`, `references/io-schema.json`, version/lifecycle rules, structured
errors, safety boundaries and a multi-Agent handoff contract.

| Skill | Owner / caller | Structured input | Structured output | Safe failure | Cross-project reuse |
|---|---|---|---|---|---|
| `collect-lab-evidence` 0.2.0 | Evidence Collector | incident, allowlist, snapshot, verification | registered evidence and trace | path/hash/schema gap → `BLOCKED` | swap repository allowlist and workspace |
| `diagnose-lab-incident` 0.2.0 | RCA Analyst | validated evidence and gaps | evidence-linked hypotheses | unsupported claim → `UNKNOWN/BLOCKED` | supply project hypothesis vocabulary |
| `plan-lab-experiment` 0.2.0 | Experiment Planner | one supported hypothesis and policy | one-variable plan, budget, rollback | unsafe scope → `REJECTED/BLOCKED` | add allowlisted bounded change pattern |
| `control-lab-action` 0.2.0 | Safe Executor | plan, approval, runner contract | raw run artifacts and hashes | no approval/capability → stop safely | bind another compatible offline runner |
| `verify-lab-result` 0.2.0 | Verification Auditor | plan, raw run data, hashes, trace | independent decision | inconclusive/hash mismatch → fail closed | provide project postconditions and protected manifest |
| `pack-lab-evidence` 0.2.0 | Incident Commander | terminal artifacts and valid trace | deterministic ZIP and manifest | missing/disallowed artifact → no final bundle | replace artifact allowlist |
| `publish-case-memory` 0.1.0 | Incident Commander | terminal verification and immutable bundle | postmortem and searchable case memory | invalid trace/hash → no publication | preserve memory schema and supply new taxonomy |

The first five Skills implement the execution flow. The last two are Commander capabilities and do
not create another Agent or alter the core state machine.

Trust Evaluation Suite 不新增 Skill，也不通过测试专用 Skill 绕过现有 Registry。评测直接检查
这些合同要求对应的治理结果：保护资源阻断、证据完整、审批时序、单变量范围和独立审计。
