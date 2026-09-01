# Reviewer Trusted Live Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent Mission Control follow real AgentTeams handoffs and read-only Evidence automatically while preserving the distinction between observed activity and independently verified Evidence.

**Architecture:** Keep Matrix normalization, Evidence synchronization, verification, and UI projection as separate fail-closed units. A new read-only Evidence synchronizer mirrors an allowlisted remote session tree, constructs a canonical candidate only from bound artifacts and accepted Matrix event IDs, and publishes it atomically only after the existing verifier accepts it; Reviewer then projects observed and verified progress independently.

**Tech Stack:** Python 3 standard library, `unittest`, Docker CLI read-only adapter, Matrix Client-Server `/sync`, static HTML/CSS/JavaScript, PowerShell startup wrapper.

**Spec:** `docs/superpowers/specs/2026-09-02-reviewer-trusted-live-sync-design.md`

## Global Constraints

- Preserve `20260902-001` as a rehearsal; never edit its Matrix history or AgentTeams source artifacts.
- Use a new `20260902-002` session for final clean live acceptance.
- Keep Reviewer read-only: no Matrix sends, Approval, retry, reassignment, Gateway invocation, Runner invocation, or source-artifact mutation.
- Matrix activity can produce only `OBSERVED`; only a complete `live-demo verify` result can produce `VERIFIED`.
- Reject missing or conflicting sender, room, session, task, incident, attempt, run, Schema, path, and hash bindings.
- Do not infer workflow transitions from natural-language chat text.
- Do not modify formal AT-002/003/004 Evidence.
- Do not expose access tokens, private room IDs, container paths, or host paths through Reviewer APIs or UI.
- Preserve all existing Mission Control edits in the dirty worktree; the focused baseline is 94 passing tests and one platform skip.
- Use TDD for every behavior change: write one failing test, confirm the expected failure, implement the minimum, then rerun focused and adjacent tests.

---

## File Structure

- Create `labops/live_evidence_sync.py`: source adapters, snapshot limits, allowlisted mapping, canonical candidate builder, atomic mirror/canonical publication, redacted sync status.
- Create `tests/test_live_evidence_sync.py`: real temporary-directory tests for snapshot, mapping, validation, atomicity, and fail-closed behavior.
- Modify `labops/matrix_observer.py`: preserve last success across transient failures and expose accepted canonical handoff events without legacy sender impersonation.
- Modify `tests/test_matrix_observer.py`: connection continuity and exact six-handoff event contract tests.
- Modify `labops/reviewer_state.py`: observed/verified handoff counters, sync health, source grace semantics, and Agent confidence projection.
- Modify `tests/test_reviewer_state.py`: deterministic state-boundary and dual-confidence tests.
- Modify `labops/reviewer.py`: lifecycle for the read-only Evidence sync loop alongside Matrix Observer.
- Modify `tests/test_reviewer.py`: Evidence loop start/stop, failure isolation, and shutdown tests.
- Modify `labops/live_demo.py`: generated Manager task contract for canonical handoffs and final structured Verification.
- Modify `tests/test_live_demo_session.py`: generated task behavioral contract tests.
- Modify `labops/reviewer.html`: separate observed/verified KPIs and sync/validation labels while preserving the current Mission Control layout.
- Modify `tests/test_reviewer_web.py`: safe renderer contract for gradual Agent illumination and explicit block reasons.
- Modify `scripts/start_reviewer_demo.ps1`: live-only default Evidence source configuration without embedding credentials.
- Modify `tests/test_release.py`: startup wrapper behavior and credential-safety checks.
- Modify `docs/final-demo-guide.md`: final `002` recording procedure and truthful acceptance criteria.

---

### Task 1: Preserve Matrix Progress Through Short Connection Failures

**Files:**
- Modify: `tests/test_reviewer_state.py`
- Modify: `tests/test_matrix_observer.py`
- Modify: `labops/reviewer_state.py`
- Modify: `labops/matrix_observer.py`

**Interfaces:**
- Consumes: Matrix snapshot fields `connected`, `last_success_at`, `checked_at`, `events`, and `errors`.
- Produces: `classify_source_status(...) -> LIVE | STALE | DISCONNECTED | REPLAY` and failure snapshots retaining the latest successful cursor/events.

- [ ] **Step 1: Write the failing source-grace tests**

Add literal boundary cases to `ReviewerStateTests`:

```python
def test_recent_success_stays_live_during_one_failed_poll(self) -> None:
    self.assertEqual(
        classify_source_status(
            "live", False, "2026-09-02T00:00:00Z",
            datetime(2026, 9, 2, 0, 0, 10, tzinfo=timezone.utc),
        ),
        "LIVE",
    )

def test_failed_poll_becomes_stale_then_disconnected_by_age(self) -> None:
    cases = ((16, "STALE"), (60, "STALE"), (61, "DISCONNECTED"))
    for seconds, expected in cases:
        with self.subTest(seconds=seconds):
            self.assertEqual(
                classify_source_status(
                    "live", False, "2026-09-02T00:00:00Z",
                    datetime(2026, 9, 2, 0, 0, seconds, tzinfo=timezone.utc),
                ),
                expected,
            )
```

- [ ] **Step 2: Run the source-grace tests and confirm RED**

Run:

```powershell
python -B -m unittest tests.test_reviewer_state.ReviewerStateTests.test_recent_success_stays_live_during_one_failed_poll tests.test_reviewer_state.ReviewerStateTests.test_failed_poll_becomes_stale_then_disconnected_by_age
```

Expected: the recent failed poll returns `DISCONNECTED` instead of `LIVE`, proving the current immediate-disconnect bug.

- [ ] **Step 3: Implement freshness-first classification**

Change `classify_source_status` so live mode parses `last_success_at` before considering `connected`. Use the exact thresholds from the spec: age `<=15` is `LIVE`, `<=60` is `STALE`, otherwise `DISCONNECTED`; missing or invalid success time is `DISCONNECTED`. Keep `quick -> REPLAY` and encrypted-room handling outside this function unchanged.

- [ ] **Step 4: Confirm the state tests GREEN**

Run the two tests from Step 2 and then:

```powershell
python -B -m unittest tests.test_reviewer_state
```

- [ ] **Step 5: Write a failing observer continuity test**

In `tests/test_matrix_observer.py`, first save a successful snapshot containing `$handoff-1`, then apply a `MATRIX_UNAVAILABLE` result and assert the stored snapshot retains the event, cursor, and `last_success_at` while updating `checked_at`, `connected=False`, and the redacted error code.

- [ ] **Step 6: Run the observer continuity test and confirm RED**

```powershell
python -B -m unittest tests.test_matrix_observer.MatrixObserverTests.test_transient_failure_preserves_last_success_and_events
```

Expected: the current failure writer clears at least one successful field.

- [ ] **Step 7: Implement minimal failure merging and confirm GREEN**

Merge a failed poll with the last valid snapshot in the Observer persistence boundary. Never carry a failure-provided event or cursor into the stored snapshot. Rerun `tests.test_matrix_observer` and `tests.test_reviewer_state`.

- [ ] **Step 8: Commit the connection-grace unit**

```powershell
git add labops/matrix_observer.py labops/reviewer_state.py tests/test_matrix_observer.py tests/test_reviewer_state.py
git commit -m "fix: preserve live reviewer progress across matrix jitter"
```

---

### Task 2: Freeze the Six-Handoff Event Contract

**Files:**
- Modify: `tests/test_matrix_observer.py`
- Modify: `tests/test_live_demo_session.py`
- Modify: `labops/matrix_observer.py`
- Modify: `labops/live_demo.py`

**Interfaces:**
- Consumes: exact Matrix `content.labops_event.kind` or `LABOPS_EVENT_KIND: <kind>` plus five session bindings.
- Produces: accepted normalized events for `manager_to_collector`, `collector_to_rca`, `rca_to_planner`, `approval_pending`, `executor_to_auditor`, and `verification_completed` with the real Matrix `event_id`.

- [ ] **Step 1: Write a table-driven six-handoff acceptance test**

Use literal rows in `tests/test_matrix_observer.py`:

```python
rows = (
    ("labops-manager", "manager_to_collector"),
    ("evidence-collector", "collector_to_rca"),
    ("rca-analyst", "rca_to_planner"),
    ("experiment-planner", "approval_pending"),
    ("safe-executor", "executor_to_auditor"),
    ("verification-auditor", "verification_completed"),
)
```

For each row, place the event in that role's allowlisted room with all five literal bindings and assert exactly one normalized event with its original `event_id`, actor, and kind.

- [ ] **Step 2: Write rejection tests for legacy Manager impersonation**

Assert that `manager_to_rca`, `manager_to_executor`, `manager_to_auditor`, `evidence_ready`, `diagnosis_ready`, `plan_ready`, and `execution_complete` do not produce normalized progress. Also assert that Manager cannot send `collector_to_rca`, `rca_to_planner`, `executor_to_auditor`, or `verification_completed` on behalf of a Worker.

- [ ] **Step 3: Run the event-contract tests and confirm their current result**

```powershell
python -B -m unittest tests.test_matrix_observer.MatrixObserverTests.test_accepts_six_sender_bound_handoffs tests.test_matrix_observer.MatrixObserverTests.test_rejects_legacy_or_impersonated_handoffs
```

If the strict observer already passes a row, retain the characterization test. Any failed canonical row must fail because its actor/transition mapping is absent, not because the fixture is malformed.

- [ ] **Step 4: Make the smallest event-map correction**

Keep the parser exact and case-insensitive. Add only missing canonical actor/transition entries; do not add aliases for the rejected legacy kinds and do not parse arbitrary prose.

- [ ] **Step 5: Write a failing generated Manager-task contract test**

Prepare a temporary session and assert `manager_task.md` contains:

```text
manager_to_collector
collector_to_rca
rca_to_planner
approval_pending
executor_to_auditor
verification_completed
session_id
task_instance_id
incident_instance_id
attempt_id
run_id
decision
verified_by
resolution_status
```

Assert the task explicitly says each Worker emits its own handoff and Manager must not impersonate Worker events.

- [ ] **Step 6: Run the generated-task test and confirm RED**

```powershell
python -B -m unittest tests.test_live_demo_session.LiveDemoSessionTests.test_manager_task_requires_sender_bound_handoffs_and_structured_verification
```

- [ ] **Step 7: Update `_manager_task` and confirm GREEN**

Add a compact event table and final Verification field list to the generated task. Preserve the helper boundaries stating that preparation does not send Matrix messages, approve, execute, or create Agent evidence. Rerun `tests.test_live_demo_session` and `tests.test_matrix_observer`.

- [ ] **Step 8: Commit the event-contract unit**

```powershell
git add labops/matrix_observer.py labops/live_demo.py tests/test_matrix_observer.py tests/test_live_demo_session.py
git commit -m "fix: bind live demo handoffs to their real agents"
```

---

### Task 3: Build the Read-Only Evidence Snapshot and Promotion Core

**Files:**
- Create: `tests/test_live_evidence_sync.py`
- Create: `labops/live_evidence_sync.py`

**Interfaces:**
- Produces: `SyncResult(status: str, mirror_digest: str | None, published: bool, errors: tuple[str, ...], checked_at: str)`.
- Produces: `DirectoryEvidenceSource.snapshot(session_id: str, destination: Path) -> Path` for real filesystem tests.
- Produces: `DockerEvidenceSource(container: str, root: str).snapshot(session_id: str, destination: Path) -> Path` as the production read-only adapter.
- Produces: `sync_live_evidence(project_root: Path, sessions_root: Path, session_id: str, source: EvidenceSource, matrix_snapshot: dict, now: datetime) -> dict`.

- [ ] **Step 1: Write the failing mirror test**

Create a temporary remote tree containing `incident_packet.json`, one Runner file, and a nested Verification file. Call `sync_live_evidence` with `DirectoryEvidenceSource` and assert:

```python
self.assertEqual(result["status"], "MIRRORED")
self.assertFalse(result["published"])
self.assertEqual(result["errors"], ["EVIDENCE_INCOMPLETE"])
self.assertTrue((session_root / "observer" / "evidence-mirror" / "manifest.json").is_file())
self.assertFalse((session_root / "evidence" / "verification.json").exists())
```

The mirror manifest must contain only relative path, size, and SHA-256 entries.

- [ ] **Step 2: Run the mirror test and confirm RED**

```powershell
python -B -m unittest tests.test_live_evidence_sync.LiveEvidenceSyncTests.test_partial_snapshot_is_mirrored_but_not_promoted
```

Expected: import failure because `labops.live_evidence_sync` does not exist.

- [ ] **Step 3: Implement bounded snapshot types and mirror publication**

Implement immutable limits of 256 files, 16 MiB per file, and 64 MiB total. Reject absolute paths, `..`, symlinks/reparse points, and files outside the source snapshot. Copy into a temporary directory, compute SHA-256 while reading, then atomically replace only `observer/evidence-mirror`. Write `observer/evidence_sync.json` through a temporary sibling file and `Path.replace`.

- [ ] **Step 4: Confirm the mirror test GREEN**

Run the test from Step 2.

- [ ] **Step 5: Write failing path and size safety tests**

Use real temporary files to assert `EVIDENCE_PATH_REJECTED` for a symlink or traversal entry and `EVIDENCE_SNAPSHOT_TOO_LARGE` when a test-specific `SnapshotLimits(max_file_bytes=4, max_total_bytes=8, max_files=2)` is exceeded. Assert the previous successful mirror remains byte-identical after either failure.

- [ ] **Step 6: Implement fail-closed snapshot validation and confirm GREEN**

Do not catch and relabel programming errors. Convert only expected source, path, size, JSON, binding, Schema, and verifier failures to the redacted codes defined by the spec.

- [ ] **Step 7: Write the failing canonical-promotion test**

Create a complete raw tree with the exact allowlisted paths, a valid six-event Matrix snapshot, and literal session bindings. Patch only the existing `verify_session` boundary to return a complete `{"status": "VERIFIED", "errors": []}` after asserting the candidate files actually exist. Assert all twelve canonical Evidence files are published together and `published=True`.

- [ ] **Step 8: Write the failing invalid-Verification test**

Use a raw `verification/verification_report.json` missing `decision`, `verified_by`, and `resolution_status`. Assert it remains in mirror, canonical `evidence/verification.json` is not created, `published=False`, and the result contains `EVIDENCE_SCHEMA_INVALID` or `EVIDENCE_INCOMPLETE` without a human-readable source path.

- [ ] **Step 9: Implement allowlisted mapping and candidate verification**

Map only the exact paths from the spec. Generate `matrix_events.json` from accepted events while preserving `event_id`. Generate `handoff_manifest.json` only when the six canonical sender-bound handoffs exist in order. Create the candidate under the session root, call the existing verifier against that candidate, and replace `evidence/` only after `VERIFIED` with an empty error list. Never add missing semantic fields.

- [ ] **Step 10: Confirm all Evidence sync tests GREEN**

```powershell
python -B -m unittest tests.test_live_evidence_sync
```

- [ ] **Step 11: Commit the Evidence core**

```powershell
git add labops/live_evidence_sync.py tests/test_live_evidence_sync.py
git commit -m "feat: add fail-closed live evidence synchronization"
```

---

### Task 4: Integrate Evidence Sync Into Live Reviewer Lifecycle

**Files:**
- Modify: `tests/test_reviewer.py`
- Modify: `tests/test_release.py`
- Modify: `labops/reviewer.py`
- Modify: `scripts/start_reviewer_demo.ps1`

**Interfaces:**
- Consumes environment: `LABOPS_LIVE_EVIDENCE_CONTAINER` and optional `LABOPS_LIVE_EVIDENCE_ROOT`.
- Default live source: container `hiclaw-manager`, root `/root/hiclaw-fs/shared/tasks/live-demo`.
- Produces: one `_EvidenceSynchronizer` loop per live Reviewer session, polling every 3 seconds and stopping within five seconds.

- [ ] **Step 1: Write failing lifecycle tests**

In `tests/test_reviewer.py`, inject a fake synchronizer factory and assert:

- live mode starts Matrix Observer and Evidence Synchronizer exactly once;
- quick mode starts neither live synchronizer;
- an Evidence source exception updates redacted sync status but the HTTP Reviewer stays running;
- shutdown calls both `stop()` methods and neither thread remains alive.

- [ ] **Step 2: Run the lifecycle tests and confirm RED**

```powershell
python -B -m unittest tests.test_reviewer.ReviewerTests.test_live_reviewer_starts_and_stops_evidence_synchronizer tests.test_reviewer.ReviewerTests.test_evidence_sync_failure_does_not_stop_dashboard
```

- [ ] **Step 3: Implement `_EvidenceSynchronizer`**

Follow the existing `_MatrixObserver` lifecycle pattern but keep the classes independent. On each cycle read the current persisted Matrix snapshot, call `sync_live_evidence`, and wait three seconds using a stoppable event rather than `sleep`. Catch expected source errors into `evidence_sync.json`; let constructor/configuration validation fail before the HTTP server starts.

- [ ] **Step 4: Confirm lifecycle tests GREEN**

Run `tests.test_reviewer`.

- [ ] **Step 5: Write a failing PowerShell wrapper test**

In `tests/test_release.py`, assert the wrapper supplies default container/root only for `-Mode live`, honors already-set environment values, and contains no access token or private room ID. Assert quick mode remains archived replay and does not require Docker Evidence.

- [ ] **Step 6: Update the wrapper and confirm GREEN**

Use PowerShell environment defaults without printing their values. Keep `pack-check`, `preflight`, and `reviewer start` order unchanged. Rerun `tests.test_release` and `tests.test_reproducibility`.

- [ ] **Step 7: Commit the lifecycle unit**

```powershell
git add labops/reviewer.py scripts/start_reviewer_demo.ps1 tests/test_reviewer.py tests/test_release.py
git commit -m "feat: attach evidence sync to live reviewer lifecycle"
```

---

### Task 5: Project Observed and Verified Progress Separately

**Files:**
- Modify: `tests/test_reviewer_state.py`
- Modify: `tests/test_reviewer_web.py`
- Modify: `labops/reviewer_state.py`
- Modify: `labops/reviewer.html`

**Interfaces:**
- Extends Reviewer state with `handoffs.observed`, `handoffs.verified`, `handoffs.total`, `evidence_sync.status`, `evidence_sync.errors`, and per-Agent `confidence_state`.
- Preserves existing incident, audit, runner, timeline, approval, recovery, and read-only fields.

- [ ] **Step 1: Write failing state-projection tests**

Create three literal scenarios:

1. no Matrix events/no Evidence -> observed `0`, verified `0`;
2. three canonical Matrix handoffs/invalid Evidence -> observed `3`, verified `0`, the three relevant Agents are `OBSERVED`;
3. six canonical Matrix handoffs/verified handoff manifest -> observed `6`, verified `6`, all six Agents are `VERIFIED`.

Assert invalid Evidence never erases observed progress and never upgrades it to verified.

- [ ] **Step 2: Run the projection tests and confirm RED**

```powershell
python -B -m unittest tests.test_reviewer_state.ReviewerStateTests.test_handoff_counts_separate_observed_from_verified tests.test_reviewer_state.ReviewerStateTests.test_invalid_evidence_keeps_observed_agent_progress
```

- [ ] **Step 3: Implement one projection helper and confirm GREEN**

Add a pure helper that consumes accepted timeline events and verified handoff data. Deduplicate by canonical handoff slot and event ID; never count stage events twice. Read `observer/evidence_sync.json` with the existing safe object loader and project only redacted status/error codes.

- [ ] **Step 4: Write failing Mission Control web-contract tests**

Require visible Chinese labels:

```text
已观察 Handoff
已验证 Handoff
Evidence 同步
Evidence 校验
连接波动
已观察
已验证
```

Require rendering from `state.handoffs` and `state.evidence_sync`, and preserve the existing `selectedEvidenceKey`, safe DOM creation, no write APIs, and no `innerHTML`.

- [ ] **Step 5: Run web tests and confirm RED**

```powershell
python -B -m unittest tests.test_reviewer_web.ReviewerWebTests.test_mission_control_separates_observed_and_verified_handoffs tests.test_reviewer_web.ReviewerWebTests.test_mission_control_renders_evidence_sync_health
```

- [ ] **Step 6: Update the current Mission Control renderer**

Keep the current layout and responsive rules. Replace the single Handoff KPI with observed and verified values, display sync and validation separately, and map `STALE` to `连接波动`. Nodes use `OBSERVED` styling until canonical verification upgrades them. Show a redacted blocking reason in Evidence Inspector rather than reverting completed Agents to `未开始`.

- [ ] **Step 7: Confirm state and web suites GREEN**

```powershell
python -B -m unittest tests.test_reviewer_state tests.test_reviewer_web
```

- [ ] **Step 8: Commit the projection/UI unit**

```powershell
git add labops/reviewer_state.py labops/reviewer.html tests/test_reviewer_state.py tests/test_reviewer_web.py
git commit -m "feat: show observed and verified agent progress separately"
```

---

### Task 6: End-to-End Regression and Live Acceptance

**Files:**
- Modify: `docs/final-demo-guide.md`
- Verify: `demo/live-sessions/20260902-001/**`
- Create during operator acceptance: `demo/live-sessions/20260902-002/**`

**Interfaces:**
- Consumes the normal operator workflow: prepare session, start live Reviewer, human sends Manager task, human performs Approval.
- Produces a verified `002` Evidence bundle and a video-ready Mission Control projection without source mutation.

- [ ] **Step 1: Run all focused regression modules**

```powershell
python -B -m unittest tests.test_matrix_observer tests.test_live_evidence_sync tests.test_reviewer_state tests.test_reviewer_web tests.test_live_demo_session tests.test_reviewer tests.test_release tests.test_reproducibility
```

Expected: all tests pass; only explicitly documented platform skips remain.

- [ ] **Step 2: Run the complete suite**

```powershell
python -B -m unittest discover -s tests
```

Record the total pass/skip count. Do not hide warnings or pre-existing failures.

- [ ] **Step 3: Verify rehearsal integrity**

Compute and record source-tree hashes for the current remote `20260902-001` snapshot before and after a Reviewer sync. Assert they are identical. Confirm `001` may become `MIRRORED` but does not become `6/6 VERIFIED` when its structured Verification remains invalid.

- [ ] **Step 4: Update the Demo guide for `002`**

Document the exact operator sequence:

1. prepare `20260902-002`;
2. start live Reviewer and wait for Matrix/Evidence source readiness;
3. send the generated Manager task once;
4. observe Agent nodes progress;
5. perform one human Approval after exact Plan Hash is available;
6. wait for Executor and Auditor;
7. require `6/6 observed`, `6/6 verified`, and `live-demo verify` with empty errors before recording the final close.

State that no access token is copied into documentation or screenshots.

- [ ] **Step 5: Start `002` only after automated verification is green**

Use the existing operator commands. Do not reuse `001` task, incident, attempt, run, Approval nonce, or artifacts. Confirm Reviewer HTTP status/events APIs return 200 before the human sends the task.

- [ ] **Step 6: Complete live behavioral acceptance**

Verify, in order:

- each canonical Matrix handoff adds one observed slot;
- a short Matrix poll failure shows `连接波动` and retains progress;
- remote files appear in mirror within one 3-second cycle;
- incomplete or invalid files show a redacted block reason;
- canonical publication occurs only after the entire bundle passes;
- all six Agents become verified only after publication;
- Reviewer sends no Matrix request with a write method and changes no source hash.

- [ ] **Step 7: Capture three viewport screenshots**

Inspect 1920×1080, 1366×768, and 390×844. Confirm no horizontal page scroll, clipped status, misleading `0/6`, or English-only error message. Keep tokens and private room IDs out of all screenshots.

- [ ] **Step 8: Review the final diff and commit the acceptance guide**

```powershell
git diff --check
git status --short
git add docs/final-demo-guide.md
git commit -m "docs: add trusted live sync demo procedure"
```

- [ ] **Step 9: Final evidence statement**

Report separately:

- automated test totals;
- `001` rehearsal status and why it was not promoted;
- `002` observed/verified handoff totals;
- Evidence sync and verifier results;
- source immutability result;
- remaining P0-3 recording/package work.
