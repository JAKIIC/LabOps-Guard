# Archived demo evidence

`demo/` stores immutable evidence archives and compatibility fixtures from completed LabOps Guard
runs. The dashboard reads these files in read-only mode.

- `output-agentteams-at004/` is the authoritative AT-004 AgentTeams evidence package.
- `output-agentteams-at003/` and `output-agentteams-at002/` retain the checkpoint repair and safe
  dependency-blocking cases.
- `output-agentteams-at004-closure/` contains the derived postmortem and case-memory package. It does
  not replace the original AT-004 evidence.
- `fixtures/project_snapshot_synthetic/` supports the active AT-001 compatibility tests with
  project-authored Apache-2.0 inputs.
- `output-agentteams/` and the legacy audit records retain the original AT-001 event without editing
  its archived evidence.

Do not edit a signed evidence bundle or regenerate its manifest in place. New runs must use a new
task, incident and run identifier. Reproducible experiment source lives in [`../demos/`](../demos/).
The fixture migration and provenance boundary are recorded in
[`../docs/public-repository-hygiene-audit.md`](../docs/public-repository-hygiene-audit.md).
