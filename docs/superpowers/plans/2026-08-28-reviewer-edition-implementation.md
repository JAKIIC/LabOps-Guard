# Reviewer Edition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally deployable, read-only Reviewer Edition that truthfully projects Quick/Replay and genuine AgentTeams Live sessions from Matrix, Gateway, Runner, Recovery and Auditor sources.

**Architecture:** Add a deterministic reviewer-state projector and an optional read-only Matrix observer beside the existing live-session verifier. Extend the standard-library web server with GET-only Reviewer APIs and a frozen v2 Workbench page, then provide a foreground lifecycle CLI and reviewer deployment wrappers. The browser remains an observation surface; Element retains task submission and Human Approval, while the existing Gateway, Runner and Verification Auditor remain the execution and terminal authorities.

**Tech Stack:** Python 3.9+ standard library, JSON/JSONL and JSON Schema contracts, Matrix Client-Server HTTP API, existing `ThreadingHTTPServer`, Docker/Compose for optional packaging, HTML/CSS/JavaScript with one-second polling, `unittest`-style tests run through pytest/unittest.

**Spec:** `docs/superpowers/specs/2026-08-28-reviewer-edition-design.md`

## Global Constraints

- Keep the six Agent identities and seven Skill Registry entries unchanged.
- Do not modify Trust Contract v1 or Trust State Machine v1.
- Do not modify, regenerate or backfill formal AT-002/003/004 Evidence.
- Do not synthesize Matrix events, Agent handoffs, Skill invocation events, Approval, Runner results or Auditor decisions.
- The Workbench is fully read-only; `POST`, `PUT`, `PATCH` and `DELETE` return HTTP 405.
- Human Approval remains a real human action outside the Workbench and is not counted as a seventh Agent.
- Green is reserved for `VERIFIED` and `RESOLVED`; observed/active is blue/cyan, waiting is yellow, unverified/not-started is grey, and blocked/rejected is red.
- `LIVE`, `STALE`, `REPLAY` and `DISCONNECTED` must be computed from source health and mode, never hard-coded page claims.
- Quick Mode must be useful without Matrix credentials but must be labelled `REPLAY`, not live execution.
- Matrix credentials, model credentials, private room IDs, absolute host paths and unrestricted message bodies never reach browser JSON or committed files.
- Use Python standard library only for the new control-plane code; do not add MCP, RAG, OTel, a frontend framework or a new service dependency.
- Every task ends with focused tests, the relevant regression subset and a separate commit; report results before starting the next task.

---

## File and Responsibility Map

| File | Responsibility |
|---|---|
| `labops/reviewer_state.py` | Deterministic source freshness, Workflow/Evidence dual state, timeline, Tool, Recovery and audit projection |
| `schemas/reviewer_status.schema.json` | Public read-only Reviewer status response contract |
| `schemas/reviewer_config.schema.json` | Local Live Mode Matrix room-map/config contract without secrets |
| `labops/matrix_observer.py` | Allowlisted Matrix `/sync`, bounded normalization, token/error redaction and non-authoritative cache |
| `labops/reviewer.py` | Preflight, foreground lifecycle, session preparation, service status and safe shutdown orchestration |
| `labops/reviewer.html` | Frozen v2 Workbench layout and one-second GET polling |
| `labops/web.py` | Backward-compatible `/reviewer` and `/api/reviewer/*` GET routes; all writes stay 405 |
| `labops/cli.py` | `labops reviewer` command surface |
| `compose.reviewer.yaml` | Optional read-only local packaging profile |
| `config/reviewer-room-map.example.json` | Credential-free canonical role-to-room configuration example |
| `scripts/start_reviewer_demo.ps1` | Windows convenience wrapper around the Python CLI |
| `scripts/start_reviewer_demo.sh` | Linux/macOS convenience wrapper around the Python CLI |
| `docs/reviewer-edition.md` | Third-party Quick/Live setup, truth labels, prerequisites and fallback |
| `tests/test_reviewer_state.py` | State projection, source freshness, timeline, Recovery and Tool truth tests |
| `tests/test_matrix_observer.py` | Matrix allowlist, normalization, encryption and redaction tests |
| `tests/test_reviewer_web.py` | GET APIs, path containment, sanitization and write-method tests |
| `tests/test_reviewer.py` | CLI preflight/lifecycle and mode-degradation tests |

---

### Task 1: Reviewer State Contract and Truth Projector

**Files:**
- Create: `labops/reviewer_state.py`
- Create: `schemas/reviewer_status.schema.json`
- Create: `tests/test_reviewer_state.py`

**Interfaces:**
- Consumes: `labops.live_demo.ROLE_ORDER`, `labops.live_demo.verify_session`, `labops.recovery.load_recovery_overlay`, existing live-session directory layout.
- Produces:
  - `classify_source_status(mode: str, connected: bool, last_success_at: str | None, now: datetime, live_threshold_seconds: int = 15, disconnect_threshold_seconds: int = 60) -> str`
  - `configured_recovery_policy() -> dict`
  - `build_reviewer_state(project_root: Path, sessions_root: Path, session_id: str | None, mode: str, matrix_snapshot: dict | None = None, now: datetime | None = None) -> dict`

- [ ] **Step 1: Write failing source-status and dual-state tests**

```python
def test_source_status_is_data_driven(self):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    self.assertEqual(classify_source_status("quick", False, None, now), "REPLAY")
    self.assertEqual(classify_source_status("live", True, "2026-08-28T11:59:55Z", now), "LIVE")
    self.assertEqual(classify_source_status("live", True, "2026-08-28T11:59:30Z", now), "STALE")
    self.assertEqual(classify_source_status("live", False, None, now), "DISCONNECTED")

def test_agent_nodes_separate_workflow_and_evidence_state(self):
    state = build_reviewer_state(repo_root(), sessions, session_id, "live", matrix_snapshot)
    planner = next(item for item in state["agents"] if item["agent_id"] == "experiment-planner")
    self.assertEqual(planner["workflow_state"], "PLAN_READY")
    self.assertEqual(planner["evidence_state"], "OBSERVED")
```

Add a Quick Mode fixture that points only at the existing archived formal Evidence and assert it is
labelled `REPLAY`, never `LIVE`, while still exposing verifier-backed Evidence and Audit results.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
python -B -m pytest tests/test_reviewer_state.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'labops.reviewer_state'`.

- [ ] **Step 3: Implement source status and the response skeleton**

Implement strict mode validation and UTC parsing. The returned skeleton must contain:

```python
{
    "schema_version": "1.0",
    "mode": mode.upper(),
    "read_only": True,
    "source_summary": "REPLAY" | "LIVE" | "LIVE_PARTIAL" | "STALE" | "DISCONNECTED",
    "sources": {},
    "session": {},
    "incident": {},
    "agents": [],
    "approval": {},
    "timeline": [],
    "tool_contract": {},
    "recovery": {},
    "runner": {},
    "audit": {},
    "limitations": [],
    "updated_at": "...Z",
}
```

- [ ] **Step 4: Add failing timeline and Human Approval ownership tests**

Create a temporary session and sanitized Matrix snapshot containing real-looking but test-only event
IDs for Manager -> Collector, Collector -> RCA, RCA -> Planner and policy-pass. Assert:

```python
self.assertEqual(state["incident"]["current_owner"], "Human Approver")
self.assertEqual(state["incident"]["last_active_agent"], "Experiment Planner")
self.assertEqual(state["incident"]["workflow_state"], "APPROVAL_PENDING")
self.assertIn("rca_to_planner", [event["kind"] for event in state["timeline"]])
self.assertIn("policy_passed", [event["kind"] for event in state["timeline"]])
self.assertIn("approval_pending", [event["kind"] for event in state["timeline"]])
```

Remove the RCA -> Planner event and assert it remains a configured gap rather than being synthesized
from the later plan.

- [ ] **Step 5: Implement deterministic timeline projection**

Use exact event kinds:

```text
task_dispatched
manager_to_collector
evidence_collected
collector_to_rca
hypotheses_ranked
rca_to_planner
policy_passed
approval_pending
approval_granted
executor_to_gateway
runner_started
runner_completed
executor_to_auditor
verification_completed
terminal_decided
commander_published
```

Every event includes `workflow_from`, `workflow_to`, `evidence_state`, `source`, `event_id`, bounded
`artifact_refs` and bounded `hash_refs`. Expected-but-missing events use `CONFIGURED` and no fabricated
event ID.

- [ ] **Step 6: Add failing Recovery fact/policy separation tests**

```python
self.assertEqual(state["recovery"]["current_directive"], "NONE")
self.assertIn("WORKER_TIMEOUT", state["recovery"]["configured_policy"])
self.assertNotEqual(state["recovery"]["current_directive"], "RETRY")
```

Append a real test Recovery event with the existing helper and assert `current_directive` reflects the
reconstructed overlay. Assert explanatory `STOP / NO RETRY` maps to `ROLLBACK_REQUIRED` and is not a
new state.

- [ ] **Step 7: Add Tool Contract summary/detail tests and implementation**

Use a temporary Gateway request with `control-lab-action@0.2.0`. The summary exposes short values while
`details` contains the complete plan SHA-256 and protected resources. Assert only existing live verifier
success can set runtime binding to `VERIFIED`; configured data alone remains `CONFIGURED`.

- [ ] **Step 8: Add and validate `reviewer_status.schema.json`**

Require the top-level keys above, separate `workflow_state` and `evidence_state` on every Agent, and
enums for source/evidence status. Validate generated Quick and Live fixtures with the repository's
existing JSON Schema test pattern.

- [ ] **Step 9: Run Task 1 tests and regression subset**

```powershell
python -B -m pytest tests/test_reviewer_state.py tests/test_live_demo_session.py tests/test_recovery.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

```powershell
git add labops/reviewer_state.py schemas/reviewer_status.schema.json tests/test_reviewer_state.py
git commit -m "feat: project truthful reviewer session state"
```

Stop and report Task 1 files, architecture impact, tests and formal Evidence hashes before Task 2.

---

### Task 2: Read-only Matrix Observer

**Files:**
- Create: `labops/matrix_observer.py`
- Create: `schemas/reviewer_config.schema.json`
- Create: `config/reviewer-room-map.example.json`
- Create: `tests/test_matrix_observer.py`

**Interfaces:**
- Consumes: a local Matrix homeserver URL, access token and canonical role room map.
- Produces:
  - `load_room_map(path: Path) -> dict[str, str]`
  - `normalize_sync_response(payload: dict, room_roles: dict[str, str], session: dict) -> list[dict]`
  - `sync_once(homeserver: str, token: str, room_roles: dict[str, str], since: str | None = None, opener=urlopen, timeout: float = 5.0) -> dict`
  - `write_observer_projection(session_root: Path, snapshot: dict) -> None`

- [ ] **Step 1: Write failing allowlist and normalization tests**

Use a synthetic `/sync` response with one allowlisted room and one excluded room. Assert only the
allowlisted event appears and is normalized to the canonical Agent ID. Assert messages without the
session task/incident/run identifiers are not attributed to the session.

- [ ] **Step 2: Run tests and confirm RED**

```powershell
python -B -m pytest tests/test_matrix_observer.py -q
```

Expected: missing module failure.

- [ ] **Step 3: Implement config validation and bounded normalization**

The room-map file contains:

```json
{
  "schema_version": "1.0",
  "rooms": {
    "!manager-room:example.invalid": "labops-manager",
    "!collector-room:example.invalid": "evidence-collector"
  }
}
```

Reject unknown Agent IDs, duplicate role mappings and non-Matrix room identifiers. Commit only the
`.example.json`; actual room IDs remain local and ignored.

- [ ] **Step 4: Write failing token-redaction and encrypted-room tests**

Provide an opener that raises an HTTP error containing a fake token. Assert returned errors contain
`MATRIX_AUTH_FAILED` or `MATRIX_UNAVAILABLE` but not the token. Provide an encrypted event and assert
the source status is `UNSUPPORTED_ENCRYPTED_ROOM`, with no invented body.

- [ ] **Step 5: Implement one bounded `/sync` call**

Use `Authorization: Bearer <token>`, percent-safe query parameters, a five-second default timeout and a
bounded response size. Return sanitized `connected`, `checked_at`, `last_success_at`, `next_batch`,
`events` and `errors`. Do not log request headers.

- [ ] **Step 6: Implement atomic non-authoritative cache writes**

Write `observer/source_status.json` atomically and append deduplicated normalized events to
`observer/normalized_events.jsonl`. Add `classification=NON_AUTHORITATIVE_UI_PROJECTION` to every
record. Never write beneath `evidence/` or formal demo directories.

- [ ] **Step 7: Validate config Schema and run tests**

```powershell
python -B -m pytest tests/test_matrix_observer.py tests/test_reviewer_state.py -q
```

Expected: PASS, including redaction and allowlist cases.

- [ ] **Step 8: Commit Task 2**

```powershell
git add labops/matrix_observer.py schemas/reviewer_config.schema.json config/reviewer-room-map.example.json tests/test_matrix_observer.py
git commit -m "feat: observe allowlisted Matrix demo events"
```

Stop and report Task 2 before Task 3.

---

### Task 3: Read-only Reviewer APIs

**Files:**
- Modify: `labops/web.py`
- Create: `tests/test_reviewer_web.py`

**Interfaces:**
- Consumes: `build_reviewer_state(...)` and a configured `sessions_root`.
- Produces:
  - extended `make_handler(..., reviewer_context: dict | None = None)`
  - GET `/api/reviewer/preflight`
  - GET `/api/reviewer/status?session=...`
  - GET `/api/reviewer/events?session=...&after=<integer>`

- [ ] **Step 1: Write failing route and backward-compatibility tests**

Start `ThreadingHTTPServer` with a temporary sessions root. Assert existing `/`, `/api/status` and
`/healthz` remain unchanged. Assert the Reviewer JSON endpoints return UTF-8 JSON with
`read_only=true`. The `/reviewer` HTML route is deliberately added in Task 4, after the page exists.

- [ ] **Step 2: Write failing containment and method tests**

Request an invalid session such as `../output-agentteams-at004` and assert rejection without path
contents. For each Reviewer API, assert `POST`, `PUT`, `PATCH` and `DELETE` return 405.

- [ ] **Step 3: Run focused tests and confirm RED**

```powershell
python -B -m pytest tests/test_reviewer_web.py -q
```

Expected: missing routes or incompatible handler signature.

- [ ] **Step 4: Implement query parsing and allowlisted route handling**

Use `urllib.parse.urlsplit` and `parse_qs`; validate the existing session ID regex before resolving a
path. A missing session returns 404. A malformed source returns structured `BLOCKED`, never archived
success. Events are sliced by integer sequence and bounded to a fixed maximum page size.

- [ ] **Step 5: Add redaction tests and sanitization**

Place fake tokens, absolute host paths and private room IDs in excluded local files. Assert none appear
in any Reviewer API response. Full event IDs and hashes are allowed only when they came from the
allowlisted session projection and are returned under `details`, not summary text.

- [ ] **Step 6: Run web tests and existing Dashboard tests**

```powershell
python -B -m pytest tests/test_reviewer_web.py tests/test_web.py -q
```

Expected: PASS and existing write-method behavior unchanged.

- [ ] **Step 7: Commit Task 3**

```powershell
git add labops/web.py tests/test_reviewer_web.py
git commit -m "feat: expose read-only reviewer session APIs"
```

Stop and report Task 3 before Task 4.

---

### Task 4: Dynamic Reviewer Workbench

**Files:**
- Create: `labops/reviewer.html`
- Modify: `labops/web.py`
- Modify: `tests/test_reviewer_web.py`

**Interfaces:**
- Consumes: the Task 3 Reviewer GET APIs.
- Produces: GET `/reviewer` and the frozen v2 Workbench, polling once per second.

- [ ] **Step 1: Write failing static semantic tests**

Assert the HTML contains:

```text
Human Approval Gate
Current Directive
Configured Policy
Workflow State
Evidence State
Last Active Agent
Last Event
Protected Resources
```

Assert it contains no approval, execute, retry, reassign, takeover or state-mutation button/form and no
hard-coded `LIVE MODE` success claim.

Also assert GET `/reviewer` serves this exact packaged page and that `POST`, `PUT`, `PATCH` and
`DELETE` to `/reviewer` return 405.

- [ ] **Step 2: Run focused test and confirm RED**

```powershell
python -B -m pytest tests/test_reviewer_web.py -q
```

Expected: missing `reviewer.html` or missing semantic markers.

- [ ] **Step 3: Implement the frozen v2 layout**

Keep the approved information architecture:

1. Incident summary, Current Owner, Last Active Agent, Last Event/Updated;
2. Incident/Task/Attempt/Run IDs;
3. six Agent nodes plus a separate Human Approval Gate;
4. Timeline and Approval;
5. Tool Contract and Recovery/Escalation;
6. Runner and Independent Audit.

Use product role names in summaries and runtime IDs only in `<details>`.

- [ ] **Step 4: Implement one-second polling and state rendering**

Fetch `/api/reviewer/status` and incremental events. Render source-derived status, separate Workflow and
Evidence badges, `Current Directive=NONE` without Recovery facts, and configured policy separately.
Never infer `RESOLVED` in JavaScript; render only the server projection.

- [ ] **Step 5: Implement summary/drill-down readability**

Use truncated human-readable summaries. Put complete event IDs, hashes, artifact paths, state
transitions and protected-resource lists inside keyboard-accessible `<details>`. Use `overflow-wrap`
inside detail blocks and prevent page-level horizontal overflow.

- [ ] **Step 6: Apply exact color semantics**

Define semantic CSS classes rather than inline colors:

```text
.is-verified / .is-resolved -> green
.is-active / .is-observed -> blue/cyan
.is-waiting -> yellow
.is-configured / .is-unverified / .is-not-started -> grey
.is-blocked / .is-rejected -> red
```

Add a test that green classes are never used for `ACTIVE`, `OBSERVED`, `UNVERIFIED`, `WAITING` or
`NOT_STARTED` labels.

- [ ] **Step 7: Run Reviewer and Dashboard web tests**

```powershell
python -B -m pytest tests/test_reviewer_web.py tests/test_web.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```powershell
git add labops/reviewer.html labops/web.py tests/test_reviewer_web.py
git commit -m "feat: add dynamic read-only reviewer workbench"
```

Stop and report Task 4 before Task 5.

---

### Task 5: Reviewer CLI and Stable Foreground Lifecycle

**Files:**
- Create: `labops/reviewer.py`
- Modify: `labops/cli.py`
- Create: `tests/test_reviewer.py`

**Interfaces:**
- Consumes: existing `prepare_session`, Runner Gateway CLI, web server, Matrix observer and Reviewer state.
- Produces CLI commands `reviewer preflight`, `reviewer start`, `reviewer status`, `reviewer stop`.

- [ ] **Step 1: Write failing Quick/Live preflight tests**

Quick Mode must succeed when repository contracts and Evidence verify even without Matrix. Live Mode
must return nonzero and list exact missing prerequisites when Docker, Runner, room map or Matrix
credentials are absent.

- [ ] **Step 2: Write failing foreground lifecycle tests**

Inject fake process/server factories. Assert `start` keeps the parent process alive, starts required
children once, terminates children on `KeyboardInterrupt`, and writes no formal Evidence. This guards
against the background-process failure observed during prototype review.

- [ ] **Step 3: Run tests and confirm RED**

```powershell
python -B -m pytest tests/test_reviewer.py -q
```

Expected: missing module/subcommand failure.

- [ ] **Step 4: Implement `preflight` and deterministic JSON output**

Report component checks, available mode, missing requirements, fallback and safety limitations. Never
print access tokens or raw environment values. Return 0 for available requested mode and 2 when the
requested mode is blocked.

- [ ] **Step 5: Implement stable foreground `start`**

Quick Mode starts the read-only server against archived Evidence and Evaluation results. Live Mode
creates or validates the isolated session, starts the short-lived Gateway, starts the Matrix observer,
and serves the Workbench. The parent remains foreground and owns child cleanup. Opening browser URLs is
best-effort and never determines correctness.

The Live observer loop calls `sync_once(...)`, writes only the non-authoritative projection with
`write_observer_projection(...)`, and records the last successful sync timestamp used by the
data-driven `LIVE / STALE / DISCONNECTED` classifier. Observer errors degrade the source status and
must not stop the read-only web server or synthesize Matrix events.

- [ ] **Step 6: Implement `status` and `stop`**

`status` reads the local lifecycle record and health endpoints. `stop` targets only the recorded
Reviewer Edition process group; it refuses broad or unresolved PIDs. A missing process returns a clean
`NOT_RUNNING` result. Do not use recursive filesystem deletion for cleanup.

- [ ] **Step 7: Register CLI parsers**

Add:

```text
labops reviewer preflight --mode quick|live
labops reviewer start --mode quick|live --session ... --sessions-root ...
labops reviewer status --session ... --sessions-root ...
labops reviewer stop --sessions-root ...
```

- [ ] **Step 8: Run CLI and existing live-session tests**

```powershell
python -B -m pytest tests/test_reviewer.py tests/test_live_demo_session.py tests/test_approval_grant.py tests/test_recovery.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 5**

```powershell
git add labops/reviewer.py labops/cli.py tests/test_reviewer.py
git commit -m "feat: add reviewer edition lifecycle CLI"
```

Stop and report Task 5 before Task 6.

---

### Task 6: Reviewer Deployment Package and Runbook

**Files:**
- Create: `compose.reviewer.yaml`
- Create: `scripts/start_reviewer_demo.ps1`
- Create: `scripts/start_reviewer_demo.sh`
- Create: `docs/reviewer-edition.md`
- Modify: `README.md`
- Modify: `docs/final-demo-guide.md`
- Modify: `tests/test_release.py`

**Interfaces:**
- Consumes: Task 5 CLI.
- Produces: third-party Quick/Live commands and optional Compose packaging.

- [ ] **Step 1: Write failing release/package tests**

Assert the reviewer compose file mounts formal Evidence read-only, mounts live sessions separately,
binds the Workbench to localhost by default, references no secrets and does not modify `compose.yaml`.
Assert wrappers call `python -B -m labops reviewer` rather than duplicating logic.

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
python -B -m pytest tests/test_release.py -q
```

Expected: missing Reviewer files.

- [ ] **Step 3: Add the optional Compose profile**

Use a separate file so the stable archived Dashboard remains unchanged. Mount:

```text
formal AT-002/003/004 Evidence -> read-only
demo/live-sessions -> read-only in the web container
local reviewer room map -> read-only only in Live Mode
```

Do not bake tokens into image layers or Compose YAML.

- [ ] **Step 4: Add thin platform wrappers**

PowerShell:

```powershell
python -B -m labops reviewer preflight --mode $Mode
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -B -m labops reviewer start --mode $Mode @RemainingArgs
```

Shell uses `exec python -B -m labops reviewer ...` and preserves the exit code.

- [ ] **Step 5: Write the Reviewer Edition runbook**

Document Quick Mode first, then Live prerequisites, local credential file, exact commands, Element human
actions, truth labels, expected output, source-status interpretation, fallback and shutdown. State that
Quick Mode is replay and that Live Mode cannot succeed without real six-Agent evidence.

- [ ] **Step 6: Link README and final Demo guide**

Add one clear Reviewer Edition entry. Do not replace Public Demo or describe the static page as live.

- [ ] **Step 7: Run release and documentation tests**

```powershell
python -B -m pytest tests/test_release.py tests/test_public_demo.py -q
```

Expected: PASS and Public Demo stale check remains clean.

- [ ] **Step 8: Commit Task 6**

```powershell
git add compose.reviewer.yaml scripts/start_reviewer_demo.ps1 scripts/start_reviewer_demo.sh docs/reviewer-edition.md README.md docs/final-demo-guide.md tests/test_release.py
git commit -m "docs: package reviewer edition deployment"
```

Stop and report Task 6 before Task 7.

---

### Task 7: Responsive, Security and Full Freeze Verification

**Files:**
- Modify if required: `labops/reviewer.html`
- Modify if required: `labops/reviewer_state.py`
- Modify if required: `labops/web.py`
- Modify: `CURRENT_STATE.md`
- Modify: `RELEASE_NOTES.md`
- Modify: `FINAL_COMPETITION_READINESS_REPORT.md` if present; otherwise document status in existing final readiness artifact
- Test: all `tests/test_*.py`

**Interfaces:**
- Consumes: completed Reviewer Edition.
- Produces: frozen competition candidate verification record.

- [ ] **Step 1: Run full automated test baseline before visual changes**

```powershell
python -B -m pytest -q
```

Record the exact passed/skipped count. Any failure blocks the freeze.

- [ ] **Step 2: Verify formal Evidence and Public Demo**

```powershell
python -B scripts/verify_evidence.py
python -B scripts/run_semifinal_eval.py
python -B scripts/build_public_demo.py --check
```

Expected: AT-002/003/004 pass, Evaluation Suite report remains accurate, Public Demo is fresh, and no
formal Evidence file changes.

- [ ] **Step 3: Perform desktop visual check**

Start Quick Mode, inspect the Workbench at 1440x900 or larger and verify the approved information
architecture, color semantics, no horizontal overflow, Timeline drill-down and read-only labeling.

- [ ] **Step 4: Perform 1024px visual check**

Verify the summary becomes two columns, Agent pipeline wraps without implying a false order, main and
bottom panels stack, and complete IDs remain in drill-down.

- [ ] **Step 5: Perform mobile visual check**

At approximately 390px, verify a single-column layout, no page-level horizontal overflow,
keyboard-accessible details, readable status labels and no clipped IDs/hashes.

- [ ] **Step 6: Verify source-state transitions with controlled fixtures**

Demonstrate `REPLAY`, `LIVE`, `STALE` and `DISCONNECTED` by changing only the test/local source-health
fixture and injected timestamps. Verify no fixed label remains in HTML.

- [ ] **Step 7: Run sensitive-data and absolute-path scans**

Use repository release verification plus focused searches for token/key patterns, private room IDs and
the current user profile path. Inspect any match; do not blanket-delete legitimate documentation.

- [ ] **Step 8: Update candidate status documents**

State exactly what is implemented, what requires external AgentTeams, and which mode was validated on
the current machine. Do not claim a live run unless one actually occurred and passed `live-demo verify`.

- [ ] **Step 9: Run final full verification**

```powershell
python -B -m pytest -q
python -B scripts/verify_evidence.py
python -B scripts/run_semifinal_eval.py
python -B scripts/build_public_demo.py --check
git diff --check
git status --short
```

Expected: all tests pass, formal Evidence hashes are unchanged, Public Demo is unchanged/fresh, and only
the intended Reviewer Edition/documentation files are modified before commit.

- [ ] **Step 10: Commit the freeze**

```powershell
git add labops/reviewer.html labops/reviewer_state.py labops/web.py CURRENT_STATE.md RELEASE_NOTES.md FINAL_COMPETITION_READINESS_REPORT.md
git commit -m "build: freeze reviewer edition candidate"
```

If an optional file does not exist or did not change, omit it from the explicit `git add`; never use
`git add -A` in a dirty workspace.

- [ ] **Step 11: Report final readiness and stop**

Report exact commits, changed files, test counts, Evidence verifier output, Public Demo status, source
mode actually exercised, remaining external prerequisites and whether the branch is ready to merge.
Do not push or merge without the user's explicit instruction.
