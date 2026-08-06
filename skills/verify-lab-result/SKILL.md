---
name: verify-lab-result
description: Independently verify LabOps Guard action results, concrete postconditions, artifacts, hashes, and trace-chain integrity. Use for AgentTeams verification-auditor assignments after any controlled action, especially when simulated or dry-run success must not be mistaken for an actually resolved experiment incident.
---

# Verify Lab Result

Verify independently from raw action records. Read `references/io-schema.json` first.

## Workflow

1. Require the action result, expected postcondition, workspace, and trace path. Do not accept
   the Executor's prose conclusion as proof.
2. Verify action status and the explicit artifact/hash postcondition:

   ```text
   python -B -m labops verify --workspace <output> \
     --action-result-json <result.json> --expected-artifact <artifact> --expected-hash <hash>
   ```

3. Verify the append-only chain:

   ```text
   python -B -m labops trace --workspace <output> --verify
   ```

4. Set `CLOSED` only when execution was real, status succeeded, a concrete postcondition exists
   and passes, and the trace is valid.
5. For a safe demo with simulated action and no postcondition, return
   `DEMO_PASSED_NOT_RESOLVED`. For any failed check, return `BLOCKED`.
6. Hand the decision, checks, raw evidence paths, and remaining limitations to the Manager.

## Safety gates

- Do not modify, repair, or regenerate the artifact under verification.
- Refuse postconditions outside the workspace.
- Never convert `PARTIAL`, `NOT_VERIFIED`, dry-run, or simulated status into closure.

## Version, reuse, and lifecycle

- Skill version: `0.2.0`; I/O schema version: `1.0`.
- Reuse it by supplying project-specific postconditions and protected-file manifests; the
  independence, trace, and hash requirements remain unchanged.
- Input lifecycle: `VERIFYING`. Output lifecycle: `RESOLVED`, `ROLLED_BACK`, `BLOCKED`, or the
  explicitly non-production `DEMO_PASSED_NOT_RESOLVED` compatibility state.
- In a multi-agent run, consume Planner and Executor raw artifacts independently, then hand the
  signed-off decision to the Incident Commander. Do not reuse the Executor's claimed metric as
  verification evidence.
- On missing artifacts, absent postconditions, path escape, hash mismatch, trace failure, or
  inconclusive recomputation, emit an `errors` array using `references/io-schema.json` and fail
  closed.

## Output requirement

Return verification checks, trace result, incident state, `underlying_issue_resolved`, and the
facts that prevented or allowed closure.
