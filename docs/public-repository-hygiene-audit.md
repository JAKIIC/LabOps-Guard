# Public repository hygiene audit

Audit date: 2026-08-08

Scope: tracked files on `main`, active code/test references, release inputs and public redistribution
boundaries. This audit organizes the release candidate without renaming active interfaces or changing
the state machine.

## Decisions

| Item | Reference result | Decision |
|---|---|---|
| `SELF_CHECK.md` | Only its own historical tree refers to the filename | Move to `docs/archive/SELF_CHECK-P0.md` and label it historical |
| `LabOps_Guard_Codex_Background.md` | No active code, test or submission reference | Move to `docs/archive/LabOps_Guard_Codex_Background-v0.2.md` |
| `submission/archive/` | Four old PPT/preview binaries; no active reference | Remove from `main`; Git history retains them |
| `demo/` and `demos/` | Both remain active | Keep names stable and add directory READMEs |
| AgentTeams V1/V2 JSON | Tests and legacy AT-001 still use V1; current flows use V2 | Defer layout changes until after the competition |
| `CURRENT_STATE.md`, `PLAN.md`, `RELEASE_FREEZE.md` | Active competition/release controls | Keep at repository root for the release candidate |

## Polar fixture migration

The previous tree tracked 13 files under `demo/fixtures/project_snapshot_lite/`: competition
documentation, parity-check tables, a baseline script and a notebook. Those files contained no
license grant, and the referenced
[`aprofeta/ecc-dataset`](https://huggingface.co/datasets/aprofeta/ecc-dataset) metadata declared no
license during the audit.

Phase 5D removed the old snapshot bytes from the current main tree. Immutable AT-001 output and Git history keep
the historical event record and hashes without making the old snapshot an active Release input.
Compatibility code, the dashboard fallback and portability tests now use
`demo/fixtures/project_snapshot_synthetic/` plus a separate synthetic audit and verification file.
LabOps Guard contributors wrote the fixture without copying the old baseline, notebook,
documentation, code tables or data.

Status: `SELF_AUTHORED_SYNTHETIC_FIXTURE`.

The active fixture contains 13 allowlisted files, declares Apache-2.0, uses the Python standard
library and includes no third-party bytes, private labels, model weights or credentials. The source
Release no longer depends on redistribution permission for the old Polar snapshot.

## Deferred changes

This release candidate keeps `demo/`/`demos/`, AgentTeams V1/V2 filenames and the Python module layout
stable. Renaming them would touch tests, prompts and evidence references without improving the judged
AT-004 workflow.
