---
name: pack-lab-evidence
description: Package allowlisted LabOps Guard registry, evidence, diagnosis, approval, action, verification, summary, and trace artifacts into a hash-manifested audit bundle. Use after independent verification or when preparing an AgentTeams handoff, competition demo, review package, or reproducibility record without including source datasets or secrets.
---

# Pack Lab Evidence

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

## Safety gates

- Never package source snapshots, datasets, archives, private labels, keys, certificates,
  environment files, checkpoints, or arbitrary workspace files.
- Keep the bundle inside the designated workspace.
- Packaging proves integrity and completeness of included evidence; it does not prove the
  underlying experiment issue is resolved.

## Output requirement

Return the evidence bundle, bundle hash, manifest, missing optional artifacts, trace status,
incident state, and explicit exclusions.
