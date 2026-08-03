---
name: diagnose-lab-incident
description: Convert collected LabOps Guard evidence and explicit evidence gaps into bounded diagnostic hypotheses that cite evidence_id. Use for AgentTeams RCA assignments and experiment-incident analysis where missing evidence must remain UNKNOWN or BLOCKED instead of being guessed as a root cause.
---

# Diagnose Lab Incident

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

## Output requirement

Return task/incident IDs, `diagnosis_candidates.json`, state counts, unresolved gaps, and
`DIAGNOSIS_READY` or `BLOCKED`.
