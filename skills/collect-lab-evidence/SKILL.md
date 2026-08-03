---
name: collect-lab-evidence
description: Register an approved AI experiment snapshot and collect allowlisted evidence into traceable LabOps Guard artifacts. Use for experiment reproducibility audits, incident intake, or AgentTeams evidence-collector assignments where excluded datasets, private labels, secrets, checkpoints, and unapproved files must never be read.
---

# Collect Lab Evidence

Produce evidence, not a diagnosis. Read `references/io-schema.json` before accepting a task.

## Workflow

1. Require an incident ID, snapshot directory, allowed-files manifest, audit directory,
   verification record, and output workspace.
2. Resolve all paths. Refuse traversal, symlink escape, missing manifests, and output outside
   the designated workspace.
3. Register only the manifest entries:

   ```text
   python -B -m labops init --workspace <output> --snapshot <snapshot> \
     --allowed-list <allowed.json> --verification <verification.json>
   ```

4. Collect the approved audit evidence:

   ```text
   python -B -m labops evidence --workspace <output> --audit-dir <audit>
   ```

5. Verify `registry_record.json` and `collected_evidence.json` exist. Report counts,
   mismatches, refused paths, gaps, and `excluded_data_not_read`.
6. Hand off artifact paths and current state to the Manager. Do not infer a root cause.

## Safety gates

- Never enumerate or read files outside the allowed manifest.
- Never read training/test CSV, private labels, archives, keys, certificates, checkpoints,
  calibration artifacts, or environment secret files.
- Never install, download, train, or change the snapshot.
- If evidence is absent or invalid, return `BLOCKED` with the exact gap.

## Output requirement

Return a structured handoff containing task/incident IDs, registry status, counts, output
paths, refused items, remaining gaps, and the next allowed state.
