---
name: publish-case-memory
description: Publish an independently verified LabOps Guard incident closure as a lightweight, searchable case-memory record and separate closure bundle. Use only by the Incident Commander after terminal verification; never use case memory as evidence for a new incident or as a substitute for approval.
---

# Publish Case Memory

Runtime registry binding: `skills/registry.json#publish-case-memory`. Registry authorization and
I/O validation fail closed before this Skill is invoked.

Skill version: `0.1.0`; I/O schema version: `1.0`.

## Workflow

1. Read `references/io-schema.json` and require a terminal Verification Auditor artifact,
   valid trace result, immutable source evidence bundle, and Incident Commander assignment.
2. Extract only reusable facts: failure signature, evidence-linked diagnosis, approved bounded
   change, safety controls, measured outcome, limitations, and source bundle hash.
3. Write `postmortem.json`, `case_memory.json`, and `postmortem.md` to a new closure workspace.
4. Build a separate deterministic closure v2 package. Never replace or append to the original
   evidence bundle.
5. Publish the compact case record under `memory/cases/` and confirm it is returned by
   `python -m labops.case_memory search`.

## Multi-agent and lifecycle boundary

- This is an Incident Commander capability, not a seventh Agent or a new state-machine actor.
- Input lifecycle: terminal `RESOLVED`, `ROLLED_BACK`, or documented `BLOCKED`. Output lifecycle:
  `MEMORY_PUBLISHED` or `BLOCKED`; it does not alter the incident's terminal decision.
- Agent messages and prompt output are not execution evidence. Every conclusion must point to
  the independent auditor artifact and immutable source bundle.

## Safety gates

- Exclude credentials, worker configuration, private data, checkpoints, local absolute paths,
  and raw chat transcripts.
- Do not generalize a single case into a guaranteed diagnosis. Record limitations and require
  fresh evidence for reuse.
- On invalid trace, missing terminal verification, hash mismatch, path escape, or source-bundle
  mutation, emit the structured `errors` array and stop without publishing.
