---
name: diagnose-lab-incident
description: Convert collected LabOps Guard evidence and explicit evidence gaps into bounded diagnostic hypotheses that cite evidence_id. Use for AgentTeams RCA assignments and experiment-incident analysis where missing evidence must remain UNKNOWN or BLOCKED instead of being guessed as a root cause.
---

# Diagnose Lab Incident

Runtime registry binding: `skills/registry.json#diagnose-lab-incident`. Registry authorization and
I/O validation fail closed before this Skill is invoked.

Create hypotheses only from registered evidence. Read `references/io-schema.json` first.

## Workflow

1. Require validated `registry_record.json` and `collected_evidence.json` from the Evidence
   Collector. Stop if the snapshot is not verified or evidence safety flags are false.
2. Run:

   ```text
   python -B -m labops diagnose --workspace <output>
   ```

3. Validate every non-UNKNOWN hypothesis has at least one `evidence_id` that resolves to an
   input evidence item or gap. Preserve `UNKNOWN`, `BLOCKED`, and `FORBIDDEN` semantics.
4. Separate observed facts, hypotheses, and missing prerequisites. Never phrase a missing
   artifact as a confirmed cause.
5. Hand off the artifact path, state counts, evidence links, suggested actions, and unresolved
   gaps to the Manager.

## Safety gates

- Do not open the source snapshot or excluded data; diagnose from collected artifacts only.
- Do not execute commands, request downloads, propose model optimization, or lower policy.
- If any asserted hypothesis lacks evidence, reject the whole handoff as `BLOCKED`.

## Version, reuse, and lifecycle

- Skill version: `0.2.0`; I/O schema version: `1.0`.
- Reuse it for any experiment incident whose collected evidence has stable IDs; project-specific
  hypothesis types belong in the assignment, not in this skill.
- Input lifecycle: `EVIDENCE_READY` -> `DIAGNOSING`. Output lifecycle: `DIAGNOSIS_READY` or
  `BLOCKED`; the skill neither chooses an experiment nor executes one.
- In a multi-agent run, consume only Evidence Collector artifacts routed by the Incident
  Commander and hand bounded hypotheses to the Experiment Planner through the Manager.
- On missing preconditions, dangling evidence IDs, or unsupported assertions, emit an `errors`
  array using `references/io-schema.json` and keep uncertain claims explicitly `UNKNOWN`.

## Output requirement

Return task/incident IDs, `diagnosis_candidates.json`, state counts, unresolved gaps, and
`DIAGNOSIS_READY` or `BLOCKED`.
