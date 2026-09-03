---
name: control-lab-action
description: Classify, dry-run, request approval for, and safely execute LabOps Guard experiment actions under workspace and command policies. Use for AgentTeams controlled-executor assignments; mandatory when an action may write files, install, download, train, access protected data, or otherwise requires human approval or refusal.
---

# Control Lab Action

Runtime registry binding: `skills/registry.json#control-lab-action`. Registry authorization and
I/O validation fail closed before this Skill is invoked.

Treat approval as a gate, never as a descriptive field. Read `references/io-schema.json`.

## Workflow

1. Require a diagnosis artifact, action ID, command intent, workspace, expected policy class,
   timeout, and explicit postcondition.
2. Classify the action using the LabOps policy. Refuse any attempted policy downgrade.
3. For `forbidden`, record refusal and stop even if a human asks to approve it.
4. For `manual_approval`, create an approval request and return `AWAITING_APPROVAL`. Do not
   decide on behalf of the human. Rejection and timeout are terminal for that action.
5. For an approved or read-only action, run the CLI with dry-run enabled first:

   ```text
   python -B -m labops run --workspace <output> --action-id <id> --command <intent>
   ```

6. Execute only when policy permits. In the competition demo, install, download, network, and
   training intents remain simulated even after approval.
7. Hand the complete action result to the Verification Auditor; never claim closure.

## Atomic AgentTeams completion

When a live assignment supplies the five session bindings, a valid Approval Binding, and an
exact emitter command:

1. Re-read the immutable Runner result and its manifest after Gateway execution completes.
2. Run the supplied `scripts/emit_handoff.py` command exactly once with the
   `executor_to_auditor` event and the assigned plan/result paths.
3. Treat only `EMITTED` or `ALREADY_EMITTED` as a completed handoff, then stop and let the
   Manager dispatch Verification Auditor. Any other result is a safe `BLOCKED` outcome.

## Safety gates

- Restrict working directories and writes to the designated workspace.
- Refuse private labels, competition data, secrets, destructive commands, path escape, and
  policy downgrades.
- Preserve stdout/stderr truncation, redaction, timeout, dry-run, and simulation markers.

## Version, reuse, and lifecycle

- Skill version: `0.2.1`; I/O schema version: `1.0`.
- Reuse it with any runner that accepts a validated structured plan and returns immutable
  manifests; bind repository-specific command and path allowlists outside the skill.
- Input lifecycle: `PLAN_READY` or `AWAITING_APPROVAL`. Output lifecycle:
  `AWAITING_APPROVAL`, `VERIFYING`, `REJECTED`, or `BLOCKED`; only an independent auditor may
  close the incident.
- In a multi-agent run, consume the Planner artifact and human decision routed by the Incident
  Commander, then hand raw runner outputs to the Verification Auditor. Never substitute an
  Executor summary for files, hashes, timestamps, and status.
- On policy, approval, capability, path, timeout, or runtime failure, emit an `errors` array
  using `references/io-schema.json`, preserve the sandbox for audit, and do not retry with a
  broader policy.

## Output requirement

Return the policy class, approval ID/status, dry-run result, execution result, simulation flag,
postcondition, artifact paths, and next state.
