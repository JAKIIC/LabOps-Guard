# Atomic AgentTeams Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one human Manager task drive the real six-Agent live demo automatically to Human Approval, require exactly one human approval message, and then finish execution, verification, and publication without additional nudges.

**Architecture:** A standalone Python emitter is copied into every deployed AgentTeams Skill and bound to role-specific Matrix rooms at deployment time. Skills use it to send one complete, idempotent, sender-bound event; Manager orchestration consumes those events immediately, while Reviewer remains a strict read-only observer. Live preflight fails closed when the emitter, runtime bindings, recording state, or run identity is unsafe.

**Tech Stack:** Python 3 standard library, `unittest`, Docker CLI, OpenClaw CLI, Matrix room map JSON, existing LabOps schemas and Reviewer lifecycle.

**Spec:** `docs/superpowers/specs/2026-09-03-atomic-agentteams-handoff-design.md`

## Global Constraints

- Formal AT-002/003/004 Evidence remains byte-for-byte read-only.
- `matrix_observer.py` keeps strict sender, room, binding, event-kind and artifact validation.
- No access token, raw credential, or host-private path may enter committed files or reports.
- `normalized_events.jsonl` is written only from real Matrix sync/history.
- Session `20260902-002` remains a failed rehearsal and is never rewritten as success.
- New behavior is developed with failing tests first and committed in reviewable increments.

---

### Task 1: Standalone atomic Handoff Emitter

**Files:**
- Create: `labops/handoff_emitter.py`
- Create: `tests/test_handoff_emitter.py`

**Interfaces:**
- Produces: `build_handoff_message(binding: dict, envelope: dict) -> str`
- Produces: `emit_handoff(binding_path: Path, session_root: Path, envelope: dict, *, dry_run: bool = False, command_runner: Callable | None = None) -> dict`
- Produces: `main(argv: list[str] | None = None) -> int`
- Consumes later: deployment copies this file as `<skill>/scripts/emit_handoff.py`.

- [ ] **Step 1: Write failing message and validation tests**

  Add literal fixtures proving the emitted body contains exactly one kind line, five bindings and two relative artifact lines. Add cases rejecting a cross-role event, absolute path, traversal, missing output and mismatched task/session binding.

  ```python
  body = build_handoff_message(BINDING, ENVELOPE)
  self.assertEqual(body.count("LABOPS_EVENT_KIND:"), 1)
  self.assertIn("LABOPS_EVENT_KIND: collector_to_rca", body)
  self.assertIn("task_instance_id: LIVE-TASK-20260903-003", body)
  with self.assertRaisesRegex(HandoffEmissionError, "not allowed"):
      build_handoff_message(BINDING, {**ENVELOPE, "event_kind": "approval_pending"})
  ```

- [ ] **Step 2: Run the new tests and verify RED**

  Run: `python -B -m unittest tests.test_handoff_emitter -v`

  Expected: import failure because `labops.handoff_emitter` does not exist.

- [ ] **Step 3: Implement deterministic message construction**

  Implement strict ID relationships, POSIX-relative artifact validation, runtime event lookup, output existence checks outside dry-run, and a fixed plain-text field order.

  ```python
  required = ("session_id", "task_instance_id", "incident_instance_id", "attempt_id", "run_id")
  if envelope["task_instance_id"] != f"LIVE-TASK-{envelope['session_id']}":
      raise HandoffEmissionError("task binding does not match session")
  route = binding["events"].get(envelope["event_kind"])
  if not route:
      raise HandoffEmissionError("event kind is not allowed for this runtime")
  ```

- [ ] **Step 4: Add failing idempotency and OpenClaw boundary tests**

  Use a fake command runner that returns a complete JSON object with a real-format `$...` Matrix ID. Assert the exact OpenClaw argument list, success receipt, no token leakage, duplicate suppression, definite failure retryability and ambiguous-result blocking.

- [ ] **Step 5: Implement emission and atomic receipts**

  Create `.labops-handoff-receipts/<sha256>.json` under the session root before sending. Preserve `PENDING` for uncertain outcomes, replace with `EMITTED` only after parsing a Matrix event ID, and return `ALREADY_EMITTED` without a second send.

  ```python
  command = [
      "openclaw", "message", "send", "--account", "default",
      "--channel", "matrix", "--target", f"room:{route['room_id']}",
      "--message", body, "--json",
  ]
  ```

- [ ] **Step 6: Verify GREEN and commit**

  Run: `python -B -m unittest tests.test_handoff_emitter -v`

  Commit: `feat: add atomic AgentTeams handoff emitter`

### Task 2: Bind and deploy the emitter with every existing Skill

**Files:**
- Modify: `labops/agentteams_skill_deployment.py`
- Modify: `labops/cli.py`
- Modify: `tests/test_agentteams_skill_deployment.py`

**Interfaces:**
- Consumes: `labops/handoff_emitter.py`
- Produces: `build_handoff_runtime_binding(deployment: dict, skill_id: str, room_roles: dict[str, str]) -> dict`
- Changes: `stage_skill_deployment(..., room_map_path: str | Path) -> dict`
- Changes: `deploy_skill_packages(..., room_map_path: str | Path, replace_existing: bool = False, runtime=None) -> dict`
- Changes: `verify_skill_packages(..., room_map_path: str | Path, runtime=None) -> dict`

- [ ] **Step 1: Write failing staging tests**

  Create a six-room valid fixture. Assert every staged Skill contains `scripts/emit_handoff.py` plus `LABOPS_HANDOFF_RUNTIME.json`, the emitter hash matches, and routes follow the strict room model: `manager_to_collector` targets the Collector room while Worker completion events target the sending Worker's own room.

  ```python
  runtime_binding = json.loads(files["evidence-collector/collect-lab-evidence/LABOPS_HANDOFF_RUNTIME.json"])
  self.assertEqual(runtime_binding["events"]["collector_to_rca"]["room_id"], COLLECTOR_ROOM)
  self.assertEqual(runtime_binding["events"]["collector_to_rca"]["recipient_matrix_id"], MANAGER_USER)
  ```

- [ ] **Step 2: Verify RED**

  Run: `python -B -m unittest tests.test_agentteams_skill_deployment -v`

  Expected: missing emitter/sidecar assertions fail and report still says `NOT_IMPLEMENTED`.

- [ ] **Step 3: Implement staged runtime bindings and verification**

  Load the ignored real room map only at stage/deploy/verify time, derive the Matrix domain from validated room IDs, copy the canonical emitter, write event routes without credentials, and verify both hashes at runtime.

  ```python
  EVENT_ROUTES = {
      "evidence-collector": {"collector_to_rca": "SELF", "evidence_incomplete": "SELF"},
      "rca-analyst": {"rca_to_planner": "SELF"},
      "experiment-planner": {"approval_pending": "SELF"},
      "safe-executor": {"executor_to_gateway": "SELF", "runner_started": "SELF", "runner_completed": "SELF", "executor_to_auditor": "SELF"},
      "verification-auditor": {"verification_completed": "SELF", "terminal_decided": "SELF"},
  }
  ```

- [ ] **Step 4: Write failing explicit-upgrade tests**

  Assert a changed installed package still fails by default, succeeds only with `replace_existing=True`, creates a backup in the runtime double, and verifies the upgraded emitter and bindings.

- [ ] **Step 5: Implement guarded replacement and CLI flags**

  Add `--room-map` to deploy/verify with fallback to `LABOPS_MATRIX_ROOM_MAP`; add `--replace-existing` to deploy. Back up an existing package before overwrite and keep all target paths fixed beneath the manifest's `skills_root`.

- [ ] **Step 6: Verify GREEN and commit**

  Run: `python -B -m unittest tests.test_agentteams_skill_deployment -v`

  Commit: `feat: deploy verified AgentTeams event emitters`

### Task 3: Make each Skill complete with one atomic event

**Files:**
- Modify: `skills/collect-lab-evidence/SKILL.md`
- Modify: `skills/diagnose-lab-incident/SKILL.md`
- Modify: `skills/plan-lab-experiment/SKILL.md`
- Modify: `skills/control-lab-action/SKILL.md`
- Modify: `skills/verify-lab-result/SKILL.md`
- Modify: `skills/pack-lab-evidence/SKILL.md`
- Modify: `skills/registry.json`
- Modify: `skills/CHANGELOG.md`
- Modify: `tests/test_live_demo_session.py`
- Modify: `tests/test_skill_registry.py`

**Interfaces:**
- Consumes: deployed `scripts/emit_handoff.py` and `LABOPS_HANDOFF_RUNTIME.json`.
- Produces: role-specific positive completion recipes and incremented Skill versions.

- [ ] **Step 1: Record the RED baseline**

  Preserve the observed Session `20260902-002` failure as the baseline: artifact existed, but the Worker emitted edited prose without a valid event line; Planner later used `rca_to_planner` rather than `approval_pending`; Manager did not advance immediately.

- [ ] **Step 2: Write failing contract-consumer tests**

  Generate a manager task and assert each stage includes its exact Skill ID, emitter command, output path and outgoing event. Validate registry versions agree with each SKILL.md version and every event-emitting Skill package stages successfully.

- [ ] **Step 3: Verify RED**

  Run: `python -B -m unittest tests.test_live_demo_session tests.test_skill_registry -v`

- [ ] **Step 4: Add one positive completion recipe per Skill**

  Each recipe has this fixed shape: validate output; invoke the emitter command supplied in the assignment exactly once; require `EMITTED` or `ALREADY_EMITTED`; stop safely on any other result. Planner emits `approval_pending` and explicitly does not route to Executor before approval. Auditor emits `verification_completed`; Manager packs and publishes only after Auditor evidence.

- [ ] **Step 5: Increment versions and changelog**

  Update the five Worker Skills and `pack-lab-evidence` by one patch version in both SKILL.md and `skills/registry.json`; describe the atomic handoff contract in `skills/CHANGELOG.md`.

- [ ] **Step 6: Verify GREEN and commit**

  Run: `python -B -m unittest tests.test_live_demo_session tests.test_skill_registry tests.test_agentteams_skill_deployment -v`

  Commit: `feat: require atomic completion from AgentTeams skills`

### Task 4: Generate an immediate Manager orchestration contract and one approval block

**Files:**
- Modify: `labops/live_demo.py`
- Modify: `tests/test_live_demo_session.py`

**Interfaces:**
- Changes: `_manager_task(manifest: dict, frozen_prompt: str) -> str`
- Produces: six stage assignments with exact role, Skill, input, output, event and next actor.

- [ ] **Step 1: Write failing orchestration tests**

  Assert the generated task states that a valid event immediately triggers the next assignment; incoming event kinds must not be copied; invalid Worker events are corrected internally; no user message is requested before approval or after Auditor completion. Assert the approval block includes all five bindings plus approval ID, plan ID, canonical hash, run ID, nonce, decision, scope and validity window.

- [ ] **Step 2: Verify RED**

  Run: `python -B -m unittest tests.test_live_demo_session.TestLiveDemoSession.test_manager_task_is_single_trigger_except_human_approval -v`

- [ ] **Step 3: Implement the stage table and exact commands**

  Put the deterministic orchestration section before the frozen prompt. Use the shared session path `/root/hiclaw-fs/shared/tasks/live-demo/<session>` and the deployed emitter path for each role. Specify distinct outgoing events rather than prose inheritance.

- [ ] **Step 4: Implement the human approval template**

  Require Manager to fill and present one copyable block after `approval_pending`; only a non-Agent sender can emit it. Manager validates it, archives the resulting ApprovalGrant, and automatically dispatches Safe Executor.

- [ ] **Step 5: Verify GREEN and commit**

  Run: `python -B -m unittest tests.test_live_demo_session -v`

  Commit: `feat: make live demo a single-trigger workflow`

### Task 5: Fail closed before recording

**Files:**
- Modify: `labops/reviewer.py`
- Modify: `tests/test_reviewer.py`

**Interfaces:**
- Produces: `_probe_agentteams_skill_runtime(project_root: Path, room_map_path: Path) -> dict`
- Produces: `_probe_manager_recording_state(project_root: Path) -> dict`
- Changes: `build_preflight(..., skill_runtime_probe=None, manager_state_probe=None) -> dict`

- [ ] **Step 1: Write failing preflight tests**

  Add cases where all existing checks pass but runtime event emission is `NOT_IMPLEMENTED`, emitter verification fails, or one stale `LIVE-TASK-*` exists. Each must return `BLOCKED`; a clean `VERIFIED` runtime must return `READY` without exposing token, room IDs or state paths.

- [ ] **Step 2: Verify RED**

  Run: `python -B -m unittest tests.test_reviewer.ReviewerPreflightTests -v`

- [ ] **Step 3: Implement the probes and gates**

  Call read-only Skill verification only after Docker, AgentTeams and room-map checks permit it. Parse only Manager `active_tasks`; preserve formal tasks and return counts/status rather than raw state. Add `AGENTTEAMS_EVENT_EMISSION_UNVERIFIED` and `STALE_LIVE_TASKS` to missing requirements as applicable.

- [ ] **Step 4: Verify GREEN and commit**

  Run: `python -B -m unittest tests.test_reviewer -v`

  Commit: `feat: gate live recording on trusted handoffs`

### Task 6: Guard Run IDs and safely archive failed rehearsals

**Files:**
- Create: `labops/live_demo_state.py`
- Create: `tests/test_live_demo_state.py`
- Modify: `labops/live_demo.py`
- Modify: `labops/cli.py`
- Modify: `tests/test_live_demo_session.py`

**Interfaces:**
- Produces: `inspect_recording_state(state: dict) -> dict`
- Produces: `archive_live_rehearsals(project_root: Path, sessions_root: Path, *, confirm: str | None = None, runtime=None) -> dict`
- Produces: `DockerManagerStateRuntime.read_state() -> bytes`
- Produces: `DockerManagerStateRuntime.replace_state(expected_sha256: str, payload: bytes) -> None`
- Changes: `prepare_session(...)` rejects a Run ID already present in any live session manifest.

- [ ] **Step 1: Write failing collision tests**

  Prepare `20260902-003`, then attempt `20260903-003`; assert the second is rejected with a suggestion for an unused suffix and the first session remains unchanged.

- [ ] **Step 2: Write failing archive tests**

  Use an in-memory runtime containing one formal task and multiple `LIVE-TASK-*` entries. No confirmation returns `PREVIEW` and makes no writes. Exact confirmation removes only live tasks, keeps formal data, creates a local hash-named backup, marks existing session directories `ABORTED_REHEARSAL`, and rejects a concurrent state-hash change.

- [ ] **Step 3: Verify RED**

  Run: `python -B -m unittest tests.test_live_demo_state tests.test_live_demo_session -v`

- [ ] **Step 4: Implement collision and archive behavior**

  Keep the three-digit Gateway ID schema. Scan `*/session.json` for reused `run_id`; select the first free `001`–`999` suffix for the error suggestion. For archive, read/validate/backup first, then compare-and-replace the fixed Manager state path; never recursively delete evidence.

- [ ] **Step 5: Register the CLI**

  Add `labops live-demo archive-rehearsals [--sessions-root ...] [--confirm ARCHIVE_LIVE_REHEARSALS]`. Without confirmation it is read-only preview.

- [ ] **Step 6: Verify GREEN and commit**

  Run: `python -B -m unittest tests.test_live_demo_state tests.test_live_demo_session -v`

  Commit: `feat: add clean recording state guard`

### Task 7: Full verification, runtime deployment and clean rehearsal gate

**Files:**
- Modify only if tests expose a covered defect: files from Tasks 1–6
- Runtime-only outputs: ignored `demo/live-sessions/_runtime-backups/`, deployed container Skill directories

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a verified clean runtime ready for a new recording session.

- [ ] **Step 1: Run focused and full test suites**

  Run:

  ```text
  python -B -m unittest tests.test_handoff_emitter tests.test_agentteams_skill_deployment tests.test_live_demo_session tests.test_live_demo_state tests.test_reviewer -v
  python -B -m unittest discover -s tests -p "test_*.py"
  ```

  Expected: all tests pass; only the two known baseline skips remain.

- [ ] **Step 2: Verify formal Evidence hashes remain unchanged**

  Run the existing formal Evidence verification/readiness commands and compare their PASS bundle hashes with the baseline report.

- [ ] **Step 3: Preview and archive stale rehearsals**

  Run `live-demo archive-rehearsals` first without confirmation. Verify the preview contains only `LIVE-TASK-*`; then rerun with exact confirmation. Confirm formal `LABOPS-AT-004-EVAL-DRIFT` remains active and Session `20260902-002` has `ABORTED_REHEARSAL` outcome metadata.

- [ ] **Step 4: Deploy the upgraded Skills**

  Use the ignored real room map and explicit AgentTeams version/replace flags. Verify all seven Skills, emitter hashes, runtime sidecars and OpenClaw discovery; expected global result is `runtime_event_emission: VERIFIED`.

- [ ] **Step 5: Run live preflight**

  With credentials supplied only through environment variables, run Reviewer live preflight. Expected status: `READY`, no stale tasks, no raw token or room IDs in output.

- [ ] **Step 6: Stop before creating recording traffic**

  Do not send a new Manager task automatically. Report the new safe session suffix and exact recording commands to the user so their next recording contains only intended real Matrix events.

- [ ] **Step 7: Final review and branch completion**

  Use `verification-before-completion`, inspect the scoped diff, confirm unrelated user files remain untouched, and then use `finishing-a-development-branch` to present integration choices.
