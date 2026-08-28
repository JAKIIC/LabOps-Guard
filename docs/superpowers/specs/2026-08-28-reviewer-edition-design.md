# LabOps-Guard Reviewer Edition Design

Date: 2026-08-28  
Status: Approved architecture and UI semantics; implementation pending  
Target: `v1.0-rc1` competition reviewer package

## 1. Purpose

Reviewer Edition turns the existing evidence-centric competition candidate into a locally deployable,
observable review experience without weakening its trust boundary. A reviewer should be able to:

1. understand the project immediately through the Public Evidence Replay;
2. run deterministic validation without AgentTeams credentials in Quick Mode;
3. run a genuine AgentTeams session when the external prerequisites are present in Live Mode;
4. see exactly which facts are configured, observed, or independently verified;
5. fall back to verified replay, video, and Evidence verification when live prerequisites are absent.

The work is an observation and packaging layer. It does not add an Agent or Skill, change the Trust
Contract, change the Trust State Machine, modify the formal AT-002/003/004 Evidence, or create an
alternative authority for approval, execution, recovery, or terminal decisions.

## 2. Experience modes

| Entry | Preconditions | Behavior | Mandatory label |
|---|---|---|---|
| Public Demo | Browser only | Redacted static replay of frozen formal Evidence | `ARCHIVED VERIFIED RUN` |
| Reviewer Quick Mode | Python 3.9+; Docker optional | Runs contract, Registry, Evidence, Evaluation and read-only Dashboard checks | `QUICK MODE / REPLAY` |
| Reviewer Live Mode | Docker, Runner, AgentTeams, Matrix, six identities, shared storage and model provider | Creates an isolated session, observes real handoffs, Gateway, Runner, Recovery and Auditor evidence | source-driven `LIVE / STALE / DISCONNECTED` |
| Verified fallback | Live prerequisites unavailable | Uses video, archived Evidence and live verifier output without claiming a new AgentTeams run | `REPLAY` |

Quick Mode is runnable but is not a live AgentTeams execution. Live Mode must fail closed when its
prerequisites or evidence are absent. The system must never silently substitute replay data for live
data.

## 3. Architecture

```text
Reviewer Launcher (local CLI)
        |
        +-- preflight / start / status / stop
        +-- creates isolated NON_FORMAL_LIVE_DEMO session
        +-- starts existing Dashboard and Runner Gateway
        +-- opens Element and the Reviewer Workbench
        |
        v
Read-only observation adapters
        +-- Matrix Observer (allowlisted unencrypted demo rooms)
        +-- Live Session / Recovery Trace reader
        +-- Gateway / Runner artifact reader
        +-- Auditor / live-demo verifier reader
        |
        v
Reviewer State Projector
        +-- source health and freshness
        +-- Workflow State and Evidence State
        +-- timeline and drill-down projection
        +-- Recovery current directive and configured policy
        |
        v
Reviewer Workbench (GET only)
```

The browser never receives Matrix tokens, model credentials, Docker access, host absolute paths, raw
private room IDs or unrestricted message bodies. Task submission and Human Approval remain human
actions in Element. The Workbench has no approval, execution, retry, reassignment, takeover or state
mutation control.

## 4. Components

### 4.1 Reviewer Launcher

Public CLI:

```text
python -B -m labops reviewer preflight [--mode quick|live]
python -B -m labops reviewer start --mode quick|live [--session YYYYMMDD-NNN]
python -B -m labops reviewer status [--session YYYYMMDD-NNN]
python -B -m labops reviewer stop
```

The launcher may inspect the environment, run existing verifiers, create a non-formal session, start
local services and open URLs. It must not send a Matrix message, approve a plan, call the Runner as an
Agent, manufacture a handoff, write an Auditor decision or modify formal Evidence. Existing sessions
are never overwritten.

The primary implementation is cross-platform Python. PowerShell and shell wrappers may provide
convenience, but must call the same Python implementation so behavior does not diverge.

### 4.2 Matrix Observer

The optional Live Mode adapter uses the Matrix Client-Server API with a read-only demo account. Its
configuration is supplied at runtime through environment variables and an ignored local room map:

```text
LABOPS_MATRIX_HOMESERVER
LABOPS_MATRIX_ACCESS_TOKEN
LABOPS_MATRIX_ROOM_MAP
```

The room map binds allowlisted room IDs to the six canonical Agent IDs. A committed example contains
logical placeholders only. The observer reads `m.room.message` events from the allowlist, keeps the
Matrix `event_id` and timestamp, and extracts only bounded task/incident/artifact references. It does
not persist or return tokens or unrestricted message content. Encrypted rooms are reported as
`UNSUPPORTED_ENCRYPTED_ROOM`; the adapter does not invent decrypted content.

The observer may append normalized UI events beneath the non-formal live session:

```text
observer/normalized_events.jsonl
classification = NON_AUTHORITATIVE_UI_PROJECTION
```

This cache is not formal Evidence, is excluded from Evidence Bundles, and cannot cause a verified or
terminal state. A real Matrix event remains necessary for an `OBSERVED` handoff.

### 4.3 Reviewer State Projector

The projector is a deterministic, side-effect-free function over allowlisted sources. Every displayed
fact records its source and one of these evidence states:

```text
NOT_OBSERVED
CONFIGURED
OBSERVED
VERIFIED
BLOCKED
```

Every Agent node displays two separate values:

- **Workflow State:** the canonical current workflow/state-machine position, such as
  `EVIDENCE_COLLECTING`, `PLAN_READY`, `APPROVAL_PENDING`, `EXECUTING` or `VERIFYING`;
- **Evidence State:** whether the displayed activity is configured, observed, verified or blocked.

`COMPLETED`, `OBSERVED` and `VERIFIED` are never treated as synonyms. A Worker can have completed a
message exchange while its artifacts remain only observed and not independently verified.

Authority precedence is:

```text
validated Auditor Evidence
> Gateway / Runner original artifacts
> real Matrix event
> configured Task Contract
```

An Agent message that claims success is displayed as a claim. It cannot produce `RESOLVED`.

### 4.4 Reviewer Workbench

The existing Trust Dashboard remains compatible. Reviewer Edition adds a dedicated read-only page and
API projection rather than turning the archived Dashboard into a control console:

```text
GET /reviewer
GET /api/reviewer/preflight
GET /api/reviewer/status?session=...
GET /api/reviewer/events?session=...&after=...
```

The frontend uses one-second short polling. It does not require WebSocket, SSE or a new stateful
service. `POST`, `PUT`, `PATCH` and `DELETE` continue to return HTTP 405.

## 5. Source status

`LIVE`, `STALE`, `REPLAY` and `DISCONNECTED` are derived from data-source state and never hard-coded
page labels.

| Status | Rule |
|---|---|
| `REPLAY` | Quick Mode or an explicitly selected archived Evidence source |
| `LIVE` | Live Mode and the source's most recent health/sync check succeeded within the live threshold |
| `STALE` | Live Mode was connected, but the most recent successful source health/sync is older than the live threshold and within the disconnect threshold |
| `DISCONNECTED` | No successful source connection, an explicit connection error, or freshness beyond the disconnect threshold |

Source connectivity and business-event time are distinct. A quiet Matrix room waiting for Human
Approval stays `LIVE` when `/sync` remains healthy. Thresholds use an injected clock in tests and are
reported in the API response.

The overall header reports each source separately before deriving the page summary. It cannot display
`LIVE` when Matrix is disconnected even if the Gateway is healthy; it reports `LIVE PARTIAL` and the
missing source.

## 6. Workflow and timeline semantics

The expected legal sequence is configured, but the timeline only marks entries observed or verified
when the corresponding source exists:

```text
task received and dispatched
Manager -> Evidence Collector
evidence collected
Evidence Collector -> RCA Analyst
hypotheses ranked
RCA Analyst -> Experiment Planner
plan policy passed
PLAN_READY -> APPROVAL_PENDING
human approval requested
human approval granted or rejected
Safe Executor -> Gateway
Runner started and completed
Safe Executor -> Verification Auditor
verification completed
Auditor terminal decision
Incident Commander publication
```

The implementation must explicitly test and display the RCA Analyst to Experiment Planner handoff,
policy-pass event, and `APPROVAL_PENDING` transition. Missing events remain visible gaps; the projector
must not synthesize them from later artifacts.

At `APPROVAL_PENDING`:

```text
Current Owner = Human Approver
Last Active Agent = Experiment Planner
```

The Human Approval Gate is visually between Planner and Executor but is not counted as a seventh
Agent. Product-facing role names use `Incident Commander`, `Evidence Collector`, `RCA Analyst`,
`Experiment Planner`, `Safe Executor` and `Verification Auditor`. Runtime identities such as
`labops-manager` appear only in details.

## 7. Recovery and escalation

The Recovery panel has two separate sections:

- **Current Directive:** reconstructed only from verified append-only Recovery events; displays `NONE`
  when no recovery has been triggered;
- **Configured Policy:** the available rules for retry, reassignment, Human Takeover and no-retry
  outcomes.

The UI uses existing recovery decisions only. It may display `STOP / NO RETRY` as explanatory text,
but it must map to a real `ROLLBACK_REQUIRED` or terminal `BLOCKED` outcome and must not introduce a
new Trust State or Recovery decision.

Configured policy includes:

- `EVIDENCE_INCOMPLETE -> RETRY_AFTER_EVIDENCE`;
- `WORKER_TIMEOUT -> one same-role RETRY, then HUMAN_TAKEOVER`;
- `CAPABILITY_MISSING -> REASSIGN only with real alternate Worker evidence, otherwise HUMAN_TAKEOVER`;
- safe/idempotent tool failure -> one bounded RETRY;
- `POLICY_VIOLATION -> ROLLBACK_REQUIRED / no retry`;
- `AUDIT_INCONCLUSIVE` or exhausted retry budget -> HUMAN_TAKEOVER.

The panel displays the resume condition and latest attempt. A human cannot directly set `RESOLVED`;
the resumed attempt still requires the Verification Auditor.

## 8. Tool Contract and drill-down

The Tool Contract summary displays:

```text
skill_id and version
caller_agent_id
tool_id
plan hash
approval binding status
protected-resource count/summary
resource budget summary
```

The complete IDs, SHA-256 values, protected-resource list and artifact references are available only
through a read-only drill-down. The Timeline uses the same summary/detail pattern for Matrix event ID,
artifact reference, hash and state transition. Long values never dominate the main projection.

The page shows `control-lab-action` as runtime verified only when the archived/live Gateway Tool
Contract passes the existing binding verifier. It does not extrapolate that proof to the other six
Skills.

## 9. Visual semantics and responsive behavior

- green: only `VERIFIED` and `RESOLVED`;
- blue/cyan: active or observed work;
- yellow: waiting, approval pending or attention required;
- grey: unverified, configured-only and not started;
- red: blocked, rejected, policy violation or integrity failure.

The approved v2 structure is frozen: incident summary, IDs, Agent/Approval pipeline, Timeline and
Approval, Tool Contract and Recovery, Runner and Auditor. Implementation may improve accessibility,
spacing and responsive behavior but must not restructure the information architecture.

Required visual checks:

1. desktop at 1440x900 or larger;
2. 1024px viewport;
3. mobile at approximately 390px;
4. no horizontal page overflow;
5. IDs and hashes wrap only in drill-down;
6. keyboard-accessible `<details>` and visible focus;
7. readable contrast for all status colors.

## 10. Deployment package

Reviewer Edition adds a separate local compose/profile rather than changing the stable Public Demo.
Quick Mode must work without Matrix credentials. Live Mode consumes credentials from a local ignored
environment file and refuses to start when required values are absent.

The package includes:

- cross-platform Python launcher;
- optional PowerShell and shell wrappers;
- `compose.reviewer.yaml` or an equivalent profile with read-only Evidence/session mounts;
- Matrix room-map example without real room IDs;
- Reviewer Edition runbook;
- preflight output that identifies exactly which mode is available;
- explicit shutdown and cleanup that never removes formal Evidence or untracked live sessions.

The launcher does not promise unconditional execution on every reviewer machine. It reports supported
prerequisites and an exact fallback. A service failure never changes evidence validity.

## 11. Error handling

- missing/invalid session: HTTP 404 or structured `BLOCKED`, never archived success;
- path escape or access outside the sessions root: rejected;
- malformed JSON/JSONL: source-specific `BLOCKED`, no partial green state;
- Matrix authentication or room-map error: `DISCONNECTED`, credentials redacted;
- Matrix encrypted room: `UNSUPPORTED_ENCRYPTED_ROOM`;
- stale observer cache: `STALE`, not `LIVE`;
- missing Approval: workflow remains `APPROVAL_PENDING`, Runner remains not started;
- Gateway/Runner inconsistency: execution `BLOCKED`;
- missing Auditor or failed live verifier: overall `UNVERIFIED/BLOCKED`, never `RESOLVED`;
- Public Demo remains build-time static and contains none of the local detailed identifiers.

## 12. Implementation scope

Expected implementation files:

```text
labops/reviewer.py
labops/reviewer_state.py
labops/matrix_observer.py
labops/reviewer.html
schemas/reviewer_status.schema.json
schemas/reviewer_config.schema.json
tests/test_reviewer.py
tests/test_reviewer_state.py
tests/test_matrix_observer.py
tests/test_reviewer_web.py
compose.reviewer.yaml
scripts/start_reviewer_demo.ps1
scripts/start_reviewer_demo.sh
docs/reviewer-edition.md
```

Existing `labops/web.py`, `labops/cli.py`, packaging metadata and documentation may receive small,
backward-compatible changes. The Public Demo generator, formal Evidence, Agent identities, Skill
Registry, Trust Contract and Trust State Machine are not rewritten.

## 13. Test strategy

Development follows RED -> GREEN with deterministic fixtures. Tests cover:

- Quick/Live preflight and exact degradation reason;
- source-driven `LIVE/STALE/REPLAY/DISCONNECTED` using an injected clock;
- Workflow State and Evidence State separation;
- complete legal timeline including RCA -> Planner, policy passed and `APPROVAL_PENDING`;
- no synthesized event when a source is missing;
- Human Approver ownership during approval pending;
- Current Directive `NONE` without Recovery events;
- configured Recovery policy separated from live facts;
- Tool Contract runtime binding and summary/detail redaction;
- Matrix allowlist, token redaction, unsupported encryption and connection failure;
- path traversal and session-root containment;
- every write method remains 405;
- Public Demo contains no new local evidence details;
- existing Trust Dashboard API compatibility;
- desktop, 1024px and mobile visual checks;
- all existing tests, Evaluation Suite, Evidence SHA verification and Public Demo freshness.

No test may mutate or regenerate the formal AT-002/003/004 Evidence.

## 14. Acceptance criteria

Reviewer Edition is complete when:

1. Quick Mode starts locally and produces truthful replay/validation status without AgentTeams;
2. Live Mode starts only when all declared prerequisites are valid;
3. a genuine live session updates the approved Workbench from real Matrix, Gateway, Runner, Recovery
   and Auditor sources;
4. every Agent node shows separate Workflow and Evidence states;
5. source mode is data-driven and stale/disconnected conditions are visible;
6. no Recovery directive is shown unless a real Recovery event exists;
7. only the verified Auditor path can display `RESOLVED`;
8. the UI is fully read-only and all write methods return 405;
9. responsive checks pass at desktop, 1024px and mobile widths;
10. all prior tests pass, new tests pass, Public Demo remains unchanged, and formal Evidence hashes are
    unchanged.

## 15. Risks and boundaries

- Full Live Mode still depends on the externally supplied AgentTeams, Matrix, shared storage and model
  provider. Reviewer Edition makes those requirements observable; it does not vendor or imitate them.
- Matrix observation supports only explicitly allowlisted unencrypted demo rooms in this version.
- Observer cache is a UI projection, not Evidence.
- Quick Mode is guaranteed to be useful offline but is never labeled as a live AgentTeams run.
- Production authentication, HA, multi-tenancy, public execution, OTel backend and Alertmanager remain
  outside this competition implementation.

