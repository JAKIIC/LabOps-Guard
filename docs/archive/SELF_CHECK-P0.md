> Historical development record from the P0 vertical slice. It does not describe the current
> AT-004 release candidate, test count or six-role AgentTeams workflow.

# SELF_CHECK.md — LabOps Guard P0 Vertical Slice

Self-check for task **LABOPS-P0-IMPL-001** (incl. REV-1 + REV-2). Completed in
`shared/tasks/LABOPS-P0-IMPL-001/labops-guard/` and pushed to MinIO. The Manager
stages the final result to `/host-share/labops-guard`.

---

## 1. File inventory

```
labops-guard/
├── labops/
│   ├── __init__.py
│   ├── __main__.py          # python -m labops
│   ├── cli.py               # CLI entry (init/evidence/diagnose/approve/run/verify/trace/demo)
│   ├── registry.py          # snapshot registry + SHA-256 + VERIFIED cross-check  (REAL)
│   ├── evidence.py          # evidence collection; excluded-data guard             (REAL)
│   ├── diagnosis.py         # hypothesis engine; mandatory evidence_id            (REAL)
│   ├── approval.py          # approval gate; approve/reject/timeout              (REAL)
│   ├── action.py            # controlled executor; dry-run/allowlist/boundary/    (REAL+SIMULATED)
│   │                        #   timeout/truncate/redact; risky ops SIMULATED
│   ├── verify.py            # verification closer; only PASSED closes            (REAL)
│   ├── trace.py             # append-only JSONL trace with SHA-256 chain         (REAL)
│   └── demo.py              # polar-baseline demo (10 real gaps)                 (REAL+SIMULATED)
├── docs/planning/           # 6 approved planning spec copies
│   ├── mvp_scope.md
│   ├── architecture.json
│   ├── incident_contract.json
│   ├── approval_policy.json
│   ├── implementation_backlog.json
│   └── demo_runbook.md
├── tests/
│   └── test_labops.py       # standard-library unittest (30 tests)
├── demo/
│   ├── run_demo.sh          # Linux demo runbook (repo-relative fixtures)
│   ├── run_demo.ps1         # Windows PowerShell demo runbook
│   ├── allowed_files.json   # 13 allowed files
│   ├── fixtures/            # self-contained verified fixtures (REV-2)
│   │   ├── project_snapshot_lite/   # 13 verified snapshot files (no manifest.json)
│   │   ├── audit/                   # 5 accepted audit files
│   │   └── snapshot_verification.json
│   └── output/              # generated demo artifacts (see below)
├── README.md
└── SELF_CHECK.md
```

---

## 2. Test results (standard-library unittest)

Command: `python3 -B -m unittest discover -s tests -p "test_*.py" -v`

**Result: 31 tests, all OK (0 failures, 0 errors).** (REV-1 added 11; REV-2 added 4 portability; REV-2.1 added 1 separator test.)

| # | Test | Scenario covered | Status |
|---|------|------------------|--------|
| 1 | `test_hypothesis_without_evidence_rejected` | no evidence_id → refuse diagnosis | ✅ OK |
| 2 | `test_unknown_hypothesis_is_explicit` | no evidence → UNKNOWN (not guessed) | ✅ OK |
| 3 | `test_reject_is_first_class_and_blocks_execution` | approval rejected is first-class | ✅ OK |
| 4 | `test_approval_timeout_is_first_class` | approval timeout is first-class | ✅ OK |
| 5 | `test_forbidden_action_refused_even_if_approved` | forbidden action refused | ✅ OK |
| 6 | `test_forbidden_classification` | forbidden classification | ✅ OK |
| 7 | `test_out_of_boundary_workdir_rejected` | out-of-boundary path rejected | ✅ OK |
| 8 | `test_out_of_boundary_write_rejected` | out-of-boundary write rejected | ✅ OK |
| 9 | `test_risky_action_simulated_not_executed` | simulated action (no real exec) | ✅ OK |
| 10 | `test_dry_run_default` | default dry-run | ✅ OK |
| 11 | `test_failed_action_does_not_close` | verification failure → no closure | ✅ OK |
| 12 | `test_missing_artifact_fails` | missing artifact → verification FAILED | ✅ OK |
| 13 | `test_dry_run_simulated_never_closes` | **REV-1**: dry-run/simulated never CLOSED | ✅ OK |
| 14 | `test_no_postcondition_never_closes` | **REV-1**: no postcondition never CLOSED | ✅ OK |
| 15 | `test_real_action_with_postcondition_closes` | **REV-1**: real + postcondition → CLOSED | ✅ OK |
| 16 | `test_expected_artifact_outside_workspace_rejected` | **REV-1**: verify expected_artifact in-workspace | ✅ OK |
| 17 | `test_path_traversal_rejected` | **REV-1**: registry `../` escape fail-closed | ✅ OK |
| 18 | `test_excluded_marker_rejected` | **REV-1**: excluded file refused in registry | ✅ OK |
| 19 | `test_registry_absolute_path_escape_rejected` | **REV-1**: absolute path escape rejected | ✅ OK |
| 20 | `test_downgrade_forbidden_to_readonly_rejected` | **REV-1**: approval downgrade refused | ✅ OK |
| 21 | `test_downgrade_manual_to_readonly_rejected` | **REV-1**: manual→readonly downgrade refused | ✅ OK |
| 22 | `test_same_or_stricter_allowed` | **REV-1**: same/stricter class allowed | ✅ OK |
| 23 | `test_gap007_has_evidence_id` | **REV-1**: GAP-007 carries evidence_id=GAP-007 | ✅ OK |
| 24 | `test_chain_verifies` | trace hash chain verifies | ✅ OK |
| 25 | `test_tamper_breaks_chain` | tamper detected → chain breaks | ✅ OK |
| 26 | `test_polar_demo_end_to_end` | full polar-baseline demo + REV-1 closure | ✅ OK |
| 27 | `test_no_root_hardcoded` | **REV-2**: no `/root/hiclaw-fs` in code/scripts | ✅ OK |
| 28 | `test_fixture_13_verified` | **REV-2**: fixture 13/13 VERIFIED (SHA-256) | ✅ OK |
| 29 | `test_fixture_zero_excluded` | **REV-2**: fixture 0 excluded files | ✅ OK |
| 30 | `test_allowed_files_match_fixture` | **REV-2**: allowed_files.json == fixture files | ✅ OK |
| 31 | `test_windows_separator_semantics` | **REV-2.1**: backslash path normalises to `/` | ✅ OK |

---

## 2b. REV-2 portability / self-contained demo

- **Fixtures** in `demo/fixtures/`: `project_snapshot_lite/` (exactly the 13
  verified allowed files, `manifest.json` excluded), `audit/` (5 accepted audit
  files), `snapshot_verification.json` (VERIFIED). No CSV / labels / models / keys.
- **No `/root/hiclaw-fs` hardcoding** anywhere in code/scripts/tests (enforced by
  `test_no_root_hardcoded`, which builds the forbidden string dynamically).
- **Portable scripts**: `demo/run_demo.sh` (Linux) + `demo/run_demo.ps1` (Windows)
  both default to repo-relative `demo/fixtures`, overridable via `LABOPS_FIXTURES` /
  `LABOPS_OUTPUT`, output to `demo/output/`.
- **README** gives real copy-paste commands for both platforms:
  - Windows: `python -B -m unittest discover -s tests -p "test_*.py" -v`
    and `powershell -ExecutionPolicy Bypass -File .\demo\run_demo.ps1`
  - Linux: `bash demo/run_demo.sh`
  - No MinIO paths required.

## 2c. REV-2.1 — Windows path separator normalisation

- Fixed `TestPortability.test_allowed_files_match_fixture` (and all same-kind path
  comparisons) to use `Path.relative_to(...).as_posix()` — normalises to forward
  slashes on every platform — before comparing against the forward-slash entries
  in `allowed_files.json`.
- Added `test_windows_separator_semantics`: a relative path expressed with
  backslashes normalises to `/` and matches the allowed list (covers Windows
  separator semantics on any host).
- Source boundary checks (`registry`/`action`/`verify`) use `resolve().relative_to()`
  which is separator-independent and platform-correct.

- **Fixtures** in `demo/fixtures/`: `project_snapshot_lite/` (exactly the 13
  verified allowed files, `manifest.json` excluded), `audit/` (5 accepted audit
  files), `snapshot_verification.json` (VERIFIED). No CSV / labels / models / keys.
- **No `/root/hiclaw-fs` hardcoding** anywhere in code/scripts/tests (enforced by
  `test_no_root_hardcoded`, which builds the forbidden string dynamically).
- **Portable scripts**: `demo/run_demo.sh` (Linux) + `demo/run_demo.ps1` (Windows)
  both default to repo-relative `demo/fixtures`, overridable via `LABOPS_FIXTURES` /
  `LABOPS_OUTPUT`, output to `demo/output/`.
- **README** gives real copy-paste commands for both platforms:
  - Windows: `python -B -m unittest discover -s tests -p "test_*.py" -v`
    and `powershell -ExecutionPolicy Bypass -File .\demo\run_demo.ps1`
  - Linux: `bash demo/run_demo.sh`
  - No MinIO paths required.

## 3. Demo output (polar-baseline, 10 real evidence gaps)

Generated by `bash demo/run_demo.sh` → `demo/output/`.

- **Registry**: 13 allowed files, `verification_status=VERIFIED`, `missing=[]`,
  `hash_mismatches_vs_verification=[]`.
- **Evidence**: 22 items (17 strong / 2 weak / 3 missing) + 10 gaps.
- **Diagnosis**: 10 hypotheses → `{BLOCKED: 8, UNKNOWN: 1, FORBIDDEN: 1}`.
  - GAP-001 (requirements), GAP-003 (test input), GAP-004 (zips), GAP-005
    (channel_calibration.npz) all **BLOCKED** — surfaced, not guessed.
  - GAP-007 (documented BER not verifiable) → **UNKNOWN** (not asserted as fact).
  - GAP-009 (private test labels) → **FORBIDDEN** (never read/request).
- **Approval**: A-GAP-001 **APPROVED**, A-GAP-004 **REJECTED**, A-GAP-005 **TIMEOUT**
  — all first-class states present in `approval_requests.json`.
- **Action**: dry-run first; `pip install` executed as **SIMULATED** (intent recorded,
  not run); rejected action skipped; forbidden action refused.
- **Verification**: `demo_verification=PASSED` but `incident_state=DEMO_PASSED_NOT_RESOLVED`
  (NOT CLOSED), `underlying_issue_resolved=false` — demo actions are SIMULATED and only
  demonstrate the audit chain; they do not fix the Polar root cause.
- **Trace**: `chain ok, 19 entries` (verified via `trace --verify`). Trace shows the
  incident ending in `DEMO_PASSED_NOT_RESOLVED` / `BLOCKED`, **not** `CLOSED`.

Artifacts in `demo/output/`:
`registry_record.json`, `collected_evidence.json`, `diagnosis_candidates.json`,
`approval_requests.json`, `verification_result.json`, `trace.jsonl`,
`demo/demo_transcript.txt`, `demo/demo_summary.json`.

**demo_summary.json** confirms: `excluded_data_not_read=true`, `no_fabricated_faults=true`,
`no_polar_root_cause_claim=true`, `no_model_optimization=true`, and REV-1 closure fields
`demo_verification=PASSED`, `incident_state=DEMO_PASSED_NOT_RESOLVED`,
`underlying_issue_resolved=false`.

## 4b. Incident closure semantics (REV-1)

- **CLOSED** requires ALL of: action is **REAL non-simulated** (not dry-run, not simulated)
  AND **≥1 concrete postcondition** (expected_artifact / hash / postcondition list) present
  AND all checks PASS.
- **DRY_RUN / SIMULATED** actions only demonstrate the control flow / audit chain
  (`demo_verification=PASSED`); they **never** mean the underlying issue is resolved.
- With **no postcondition**, the incident **never closes** (`incident_state=BLOCKED`).
- The Polar demo ends in `DEMO_PASSED_NOT_RESOLVED` (equivalently `BLOCKED`) with
  `underlying_issue_resolved=false`; its trace does **not** contain `CLOSED`.
- `verify.py` also rejects `expected_artifact` paths outside the workspace boundary.

---

## 4. Polar-baseline "not modified" declaration

- This implementation **does not touch, modify, or write any polar-baseline project
  file**. It only **reads** the already-verified snapshot
  (`POLAR-AUDIT-001/attempt-R1/project_snapshot_lite/`, 13 allowed files) for hashing.
- Excluded data (train/test CSV, private test labels, checkpoints, keys) is **never read**.
- The container cannot access `/host-share`; no writes attempted there.
- LabOps Guard **does not claim to fix the Polar root cause or resolve missing evidence**;
  it only surfaces the 10 real evidence gaps and enforces the guard loop.

---

## 5. Constraints verification

| Constraint | Status |
|------------|--------|
| Standard-library Python only, no installs | ✅ |
| Default dry-run | ✅ |
| Command allowlist | ✅ |
| Workspace boundary | ✅ |
| Timeout | ✅ |
| Output truncation + redaction | ✅ |
| Excluded data not read | ✅ |
| Risky actions SIMULATED only | ✅ |
| No claim of fixing Polar root cause | ✅ |
| No model-optimization suggestions | ✅ |
| No network / no training / no testing of model | ✅ |
| Approval rejected / action failed / verification failed first-class | ✅ |
| Append-only JSONL trace with hash chain | ✅ |
