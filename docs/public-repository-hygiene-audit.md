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

## Polar fixture provenance

The repository tracks 13 files under `demo/fixtures/project_snapshot_lite/`: competition READMEs,
seven BCH/POLAR parity-check tables, `baseline.py`, a participant notebook and two format READMEs.
The files contain no copyright or license notice. The snapshot README points to
[`aprofeta/ecc-dataset`](https://huggingface.co/datasets/aprofeta/ecc-dataset); its public API metadata
returned no dataset card or license field during this audit.

The fixture remains active in:

- legacy Polar demo and dashboard fallback code;
- AT-001 compatibility contracts;
- the 13-file byte-hash portability tests;
- archived Polar evidence records.

Status: `REDISTRIBUTION_PERMISSION_UNVERIFIED`.

The Apache-2.0 license for LabOps Guard does not cover this snapshot. The project owner must obtain a
written redistribution grant or replace/remove the snapshot and update the compatibility tests before
creating a formal source Release. This pass leaves the bytes and their historical hashes unchanged.

## Deferred changes

This release candidate keeps `demo/`/`demos/`, AgentTeams V1/V2 filenames and the Python module layout
stable. Renaming them would touch tests, prompts and evidence references without improving the judged
AT-004 workflow.
