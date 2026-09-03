---
name: pack-lab-evidence
description: Package allowlisted LabOps Guard registry, evidence, diagnosis, approval, action, verification, summary, and trace artifacts into a hash-manifested audit bundle. Use after independent verification or when preparing an AgentTeams handoff, competition demo, review package, or reproducibility record without including source datasets or secrets.
---

# Pack Lab Evidence

Runtime registry binding: `skills/registry.json#pack-lab-evidence`. Registry authorization and I/O
validation fail closed before this Skill is invoked.

Package existing evidence without changing its meaning. Read `references/io-schema.json`.

## Workflow

1. Require a verified LabOps output workspace and final incident state.
2. Confirm trace verification has already passed. Refuse a bundle presented as final when the
   chain is invalid or verification is missing.
3. Run the bundled deterministic packer:

   ```text
   python -B skills/pack-lab-evidence/scripts/build_bundle.py \
     --workspace <output> --output <output>/evidence_bundle.zip
   ```

4. Inspect the returned manifest. It may include only generated registry, evidence, diagnosis,
   approvals, action result, verification, demo summary/transcript, and trace artifacts.
5. Return bundle path, SHA-256, included artifact hashes, missing optional items, final incident
   state, and unresolved limitations.

## Atomic AgentTeams completion

When a live assignment supplies the five session bindings and an exact emitter command:

1. Invoke this Skill only after the Verification Auditor's `verification_completed` artifact
   has been independently validated.
2. Re-read the evidence bundle and hash manifest after packaging.
3. Run the supplied `scripts/emit_handoff.py` command exactly once with the
   `commander_published` event and the assigned verification/bundle paths.
4. Treat only `EMITTED` or `ALREADY_EMITTED` as a completed publication. Any other result is a
   safe `BLOCKED` outcome and must not be presented as final.

## Safety gates

- Never package source snapshots, datasets, archives, private labels, keys, certificates,
  environment files, checkpoints, or arbitrary workspace files.
- Keep the bundle inside the designated workspace.
- Packaging proves integrity and completeness of included evidence; it does not prove the
  underlying experiment issue is resolved.

## Version, reuse, and lifecycle

- Skill version: `0.2.1`; I/O schema version: `1.0`.
- Reuse it with repository-specific artifact allowlists. The bundle format is independent of
  the demo incident and must not assume checkpoint or evaluation-drift filenames.
- Input lifecycle: verified terminal or reviewable non-terminal state. Output lifecycle:
  `PACKAGED` or `BLOCKED`; packaging never changes the incident decision.
- In a multi-agent run, the Incident Commander invokes this skill only after receiving the
  Verification Auditor's raw decision and trace result. Preserve producer identity for every
  included artifact.
- On missing, disallowed, out-of-workspace, or hash-invalid content, emit an `errors` array
  using `references/io-schema.json`, produce no final bundle, and retain the source workspace.

## Output requirement

Return the evidence bundle, bundle hash, manifest, missing optional artifacts, trace status,
incident state, and explicit exclusions.
