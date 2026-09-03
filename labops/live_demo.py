"""Prepare and verify isolated, non-formal real AgentTeams demo sessions.

The helper never sends Matrix messages, approves a plan, invokes a Skill, or
starts the Runner.  It creates an operator envelope and validates evidence that
the external HiClaw/AgentTeams runtime produced.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from labops.approval_grant import ApprovalBindingError, validate_approval_grant
from labops.recovery import RecoveryError, load_recovery_overlay
from labops.runner_gateway import normalize_tool_contract
from labops.trace import TraceLog

CLASSIFICATION = "NON_FORMAL_LIVE_DEMO"
SESSION_ID = re.compile(r"^(?P<date>[0-9]{8})-(?P<sequence>[0-9]{3})$")
RUN_ID = re.compile(r"^RUN-LABOPS-AT-004-AGENTTEAMS-(?P<sequence>[0-9]{3})$")
RUN_ID_FIELD = re.compile(
    r'"run_id"\s*:\s*"(RUN-LABOPS-AT-004-AGENTTEAMS-[0-9]{3})"'
)
ROLE_ORDER = [
    "labops-manager",
    "evidence-collector",
    "rca-analyst",
    "experiment-planner",
    "safe-executor",
    "verification-auditor",
]
HANDOFFS = list(zip(ROLE_ORDER, ROLE_ORDER[1:])) + [
    ("verification-auditor", "labops-manager")
]
EVIDENCE_FILES = [
    "handoff_manifest.json",
    "matrix_events.json",
    "approval_grant.json",
    "gateway_request.json",
    "gateway_response.json",
    "runner/run_result.json",
    "runner/metrics.json",
    "runner/artifact_manifest.json",
    "runner/stdout.log",
    "runner/stderr.log",
    "verification.json",
    "trace.jsonl",
]
FORMAL_ROOTS = [
    Path("demo/output-agentteams-at002"),
    Path("demo/output-agentteams-at003"),
    Path("demo/output-agentteams-at004"),
]


def _inside(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _session_manifest(session_id: str) -> dict:
    match = SESSION_ID.fullmatch(session_id)
    if match is None:
        raise ValueError("session must use YYYYMMDD-NNN")
    sequence = match.group("sequence")
    return {
        "schema_version": "1.0",
        "classification": CLASSIFICATION,
        "session_id": session_id,
        "scenario_contract": "LABOPS-AT-004-EVAL-DRIFT",
        "scenario_incident": "DEMO-EVAL-DRIFT-004",
        "task_instance_id": f"LIVE-TASK-{session_id}",
        "incident_instance_id": f"LIVE-INCIDENT-{session_id}",
        "attempt_id": f"LIVE-ATTEMPT-{session_id}-01",
        "run_id": f"RUN-LABOPS-AT-004-AGENTTEAMS-{sequence}",
        "storage_namespace": f"live-demo/{session_id}/",
        "agent_order": ROLE_ORDER,
        "required_handoffs": [
            {"from_agent": source, "to_agent": target} for source, target in HANDOFFS
        ],
        "expected_evidence": EVIDENCE_FILES,
        "helper_boundaries": {
            "sends_matrix_messages": False,
            "approves_plans": False,
            "executes_runner": False,
            "creates_agent_evidence": False,
        },
    }


def _guard_run_id_collision(sessions_root: Path, manifest: dict) -> None:
    if not sessions_root.exists():
        return
    bindings: dict[str, str] = {}
    used_sequences: set[str] = set()

    def register(run_id: str, session_id: str) -> None:
        owner = bindings.get(run_id)
        if owner is not None and owner != session_id:
            raise ValueError(f"Run ID {run_id} is already bound to session {owner}")
        bindings[run_id] = session_id
        run_match = RUN_ID.fullmatch(run_id)
        if run_match is not None:
            used_sequences.add(run_match.group("sequence"))

    for manifest_path in sorted(sessions_root.glob("*/session.json")):
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"cannot inspect existing session manifest: {manifest_path.parent.name}"
            ) from exc
        if not isinstance(existing, dict):
            raise ValueError(
                f"existing session manifest is not an object: {manifest_path.parent.name}"
            )
        run_id = existing.get("run_id")
        session_id = existing.get("session_id")
        if not isinstance(run_id, str) or not isinstance(session_id, str):
            continue
        register(run_id, session_id)

    inspected = 0
    for session_dir in sorted(sessions_root.iterdir()):
        if not session_dir.is_dir() or SESSION_ID.fullmatch(session_dir.name) is None:
            continue
        if session_dir.is_symlink():
            raise ValueError(f"cannot inspect symlinked live session: {session_dir.name}")
        for artifact in sorted(session_dir.rglob("*")):
            if artifact.suffix not in {".json", ".jsonl"} or not artifact.is_file():
                continue
            inspected += 1
            if inspected > 4096:
                raise ValueError("cannot inspect more than 4096 live-session binding files")
            if artifact.is_symlink() or artifact.stat().st_size > 4 * 1024 * 1024:
                raise ValueError(f"cannot safely inspect live binding file: {artifact.name}")
            try:
                text = artifact.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"cannot inspect live binding file: {artifact.name}") from exc
            for match in RUN_ID_FIELD.finditer(text):
                register(match.group(1), session_dir.name)

    owner = bindings.get(manifest["run_id"])
    if owner is None or owner == manifest["session_id"]:
        return
    date = SESSION_ID.fullmatch(manifest["session_id"]).group("date")
    suggestion = next(
        (
            f"{date}-{sequence:03d}"
            for sequence in range(1, 1000)
            if f"{sequence:03d}" not in used_sequences
        ),
        None,
    )
    message = f"Run ID {manifest['run_id']} is already bound to session {owner}"
    if suggestion is not None:
        message += f"; use session {suggestion}"
    raise ValueError(message)


def _emitter_command(
    manifest: dict,
    session_root: str,
    emitter_path: str,
    event_kind: str,
    input_artifact: str,
    output_artifact: str,
) -> str:
    return " ".join(
        (
            "python3",
            emitter_path,
            "--session-root",
            session_root,
            "--session-id",
            manifest["session_id"],
            "--task-instance-id",
            manifest["task_instance_id"],
            "--incident-instance-id",
            manifest["incident_instance_id"],
            "--attempt-id",
            manifest["attempt_id"],
            "--run-id",
            manifest["run_id"],
            "--event-kind",
            event_kind,
            "--input-artifact",
            input_artifact,
            "--output-artifact",
            output_artifact,
        )
    )


def _runtime_contract(project_root: Path, manifest: dict) -> dict:
    # Imported lazily because the deployment verifier reads Matrix event
    # definitions, which in turn import this module's role constants.
    from labops.agentteams_skill_deployment import load_deployment_manifest

    deployment = load_deployment_manifest(project_root)
    emitters: dict[str, str] = {}
    for runtime in deployment["deployments"]:
        skills_root = runtime["skills_root"]
        for skill_id in runtime["skill_ids"]:
            emitters[skill_id] = str(
                PurePosixPath(skills_root) / skill_id / "scripts" / "emit_handoff.py"
            )
    required = {
        "pack-lab-evidence",
        "collect-lab-evidence",
        "diagnose-lab-incident",
        "plan-lab-experiment",
        "control-lab-action",
        "verify-lab-result",
    }
    if set(emitters) < required:
        raise ValueError("AgentTeams deployment lacks a required live-demo Skill")
    try:
        evidence_source = json.loads(
            (project_root / "config" / "reviewer-evidence-source.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("live Evidence source is not configured") from exc
    source_root = (
        evidence_source.get("root") if isinstance(evidence_source, dict) else None
    )
    if not isinstance(source_root, str) or not source_root.startswith("/"):
        raise ValueError("live Evidence source root must be an absolute container path")
    return {
        "session_root": str(PurePosixPath(source_root) / manifest["session_id"]),
        "emitters": emitters,
    }


def _manager_task(manifest: dict, frozen_prompt: str, runtime_contract: dict) -> str:
    session_root = runtime_contract["session_root"]
    emitters = runtime_contract["emitters"]
    run_result = f"runs/{manifest['run_id']}/run_result.json"
    gateway_request = f"runs/{manifest['run_id']}/gateway_request.json"
    gateway_response = f"runs/{manifest['run_id']}/gateway_response.json"
    stage_commands = {
        "manager_to_collector": _emitter_command(
            manifest,
            session_root,
            emitters["pack-lab-evidence"],
            "manager_to_collector",
            "incident_packet.json",
            "incident_packet.json",
        ),
        "collector_to_rca": _emitter_command(
            manifest,
            session_root,
            emitters["collect-lab-evidence"],
            "collector_to_rca",
            "incident_packet.json",
            "collector-report.json",
        ),
        "evidence_incomplete": _emitter_command(
            manifest,
            session_root,
            emitters["collect-lab-evidence"],
            "evidence_incomplete",
            "incident_packet.json",
            "collector-report.json",
        ),
        "rca_to_planner": _emitter_command(
            manifest,
            session_root,
            emitters["diagnose-lab-incident"],
            "rca_to_planner",
            "collector-report.json",
            "diagnosis/diagnosis_candidates.json",
        ),
        "approval_pending": _emitter_command(
            manifest,
            session_root,
            emitters["plan-lab-experiment"],
            "approval_pending",
            "diagnosis/diagnosis_candidates.json",
            "plan/plan.json",
        ),
        "executor_to_gateway": _emitter_command(
            manifest,
            session_root,
            emitters["control-lab-action"],
            "executor_to_gateway",
            "plan/plan.json",
            gateway_request,
        ),
        "runner_started": _emitter_command(
            manifest,
            session_root,
            emitters["control-lab-action"],
            "runner_started",
            gateway_request,
            gateway_response,
        ),
        "runner_completed": _emitter_command(
            manifest,
            session_root,
            emitters["control-lab-action"],
            "runner_completed",
            gateway_response,
            run_result,
        ),
        "executor_to_auditor": _emitter_command(
            manifest,
            session_root,
            emitters["control-lab-action"],
            "executor_to_auditor",
            "plan/plan.json",
            run_result,
        ),
        "verification_completed": _emitter_command(
            manifest,
            session_root,
            emitters["verify-lab-result"],
            "verification_completed",
            run_result,
            "verification/verification_report.json",
        ),
        "terminal_decided": _emitter_command(
            manifest,
            session_root,
            emitters["verify-lab-result"],
            "terminal_decided",
            "verification/verification_report.json",
            "verification/verification_report.json",
        ),
        "commander_published": _emitter_command(
            manifest,
            session_root,
            emitters["pack-lab-evidence"],
            "commander_published",
            "verification/verification_report.json",
            "evidence_bundle.zip",
        ),
    }
    canonical_session = json.dumps(manifest, ensure_ascii=False, indent=2)
    orchestration = f"""## Deterministic single-trigger orchestration

This deterministic section governs runtime sequencing and overrides any legacy routing ambiguity
in the frozen reference copy retained below for evidence provenance.

The human sends this Manager task once. After every schema-valid atomic event,
immediately dispatch the next stage shown below. Do not wait for a heartbeat,
scheduled history scan, or another human message. Do not copy an incoming event kind
into the next assignment: each role has its own outgoing kind and command.

Create and validate the session namespace `{session_root}`. Before Stage 1,
write `session.json` with the exact five bindings and the fixed
`NON_FORMAL_LIVE_DEMO` classification from this task, then write the canonical
`incident_packet.json`. Every Worker assignment must include the
unchanged five bindings, its named Skill, exact input/output paths, and the exact
emitter command below.

Write `session.json` as this complete canonical object (do not omit fields):

```json
{canonical_session}
```

### Stage 1 — Incident Commander → Evidence Collector

- Skill package: `pack-lab-evidence` (hosts the Manager emitter; packaging occurs only at final publication)
- Input: `incident_packet.json`
- Output: `incident_packet.json`
- Outgoing event: `manager_to_collector`
- On success: immediately assign Stage 2 to Evidence Collector.
- Exact emitter command: `{stage_commands['manager_to_collector']}`

### Stage 2 — Evidence Collector → RCA Analyst

- Skill: `collect-lab-evidence`
- Input: `incident_packet.json`
- Output: `collector-report.json`
- Outgoing event: `collector_to_rca`
- On success: immediately assign Stage 3 to RCA Analyst.
- Exact emitter command: `{stage_commands['collector_to_rca']}`
- Failure branch: if and only if the Collector output has
  `handoff_state: BLOCKED`, first write and validate the complete structured
  failure artifact in `collector-report.json`; only after the structured BLOCKED failure artifact validates,
  emit `evidence_incomplete` with `{stage_commands['evidence_incomplete']}` and stop this attempt.

### Stage 3 — RCA Analyst → Experiment Planner

- Skill: `diagnose-lab-incident`
- Input: `collector-report.json`
- Output: `diagnosis/diagnosis_candidates.json`
- Outgoing event: `rca_to_planner`
- On success: immediately assign Stage 4 to Experiment Planner.
- Exact emitter command: `{stage_commands['rca_to_planner']}`

### Stage 4 — Experiment Planner → Human Approval

- Skill: `plan-lab-experiment`
- Input: `diagnosis/diagnosis_candidates.json`
- Output: `plan/plan.json`
- Outgoing event: `approval_pending`
- On success: validate the canonical Plan Hash and display the single Human Approval block below. Do not dispatch Executor yet.
- Exact emitter command: `{stage_commands['approval_pending']}`

### Stage 5 — Safe Executor → Verification Auditor

- Skill: `control-lab-action`
- Input: `plan/plan.json`
- Output: `{run_result}`
- Outgoing event: `executor_to_auditor`
- Entry condition: one valid human ApprovalGrant bound to this exact plan and run.
- Before calling Gateway, write the bound request and emit `executor_to_gateway`
  with `{stage_commands['executor_to_gateway']}`.
- After Gateway accepts the request, emit `runner_started` with
  `{stage_commands['runner_started']}`.
- After immutable Runner output exists, emit `runner_completed` with
  `{stage_commands['runner_completed']}`.
- On success: immediately assign Stage 6 to Verification Auditor.
- Exact emitter command: `{stage_commands['executor_to_auditor']}`

### Stage 6 — Verification Auditor → Incident Commander

- Skill: `verify-lab-result`
- Input: `{run_result}`
- Output: `verification/verification_report.json`
- Outgoing event: `verification_completed`
- On success: emit `verification_completed`, then emit the Auditor's truthful
  terminal decision with `{stage_commands['terminal_decided']}`.
- Only after `terminal_decided` succeeds, the Manager invokes
  `pack-lab-evidence`, writes `evidence_bundle.zip`, emits `commander_published`
  with `{stage_commands['commander_published']}`, and must publish automatically only after the Auditor terminal decision.
- Exact emitter command: `{stage_commands['verification_completed']}`

If a Worker artifact is valid but its event is missing, malformed, or uses the
wrong kind, correct it internally with the same Worker by having that Worker run
its assigned emitter command. Do not impersonate the Worker and do not ask the
human to repair, continue, check, or resend the stage. Do not ask the human to send continue
before approval or after verification.

## Human Approval — the only mid-run user action

After the valid `approval_pending` event, generate the concrete values, show a
Chinese plan/risk summary, and print exactly one copyable block in this shape.
The human sends the completed block once from a non-Agent Matrix account:

```text
LABOPS_EVENT_KIND: approval_granted
LABOPS_ACTOR: human-approver
session_id: {manifest['session_id']}
task_instance_id: {manifest['task_instance_id']}
incident_instance_id: {manifest['incident_instance_id']}
attempt_id: {manifest['attempt_id']}
run_id: {manifest['run_id']}
approval_id: <generated approval ID>
plan_id: <exact plan ID>
canonical_plan_sha256: <64 lowercase hex characters>
nonce: <new single-use nonce>
decision: APPROVED
approved_scope: eval_config.json:evaluation.preprocessing_profile
approved_at: <UTC timestamp>
expires_at: <later UTC timestamp>
```

Validate every field against `plan/plan.json`; archive the resulting
ApprovalGrant at `artifacts/DEMO-EVAL-DRIFT-004/approval_grant.json`, then
immediately dispatch Stage 5. A bare “可以执行” is not an approval event. A human
rejection must never be labelled `approval_granted`; `decision: REJECTED` stops
safely and is not projected as an approval. No Agent may author this
block. This is the only normal point where the workflow waits for the human.

"""
    envelope = f"""# Real AgentTeams live session: {manifest['session_id']}

Classification: `{CLASSIFICATION}`. This is a new live recording session, not a
formal AT-002/003/004 Evidence Bundle and not an archived replay.

Send this task to the real HiClaw/AgentTeams Manager from a human-operated
Matrix/Element account. Run the existing contract
`agentteams/tasks/LABOPS-AT-004-EVAL-DRIFT.json` with all six configured roles.

Instance bindings:

- task instance: `{manifest['task_instance_id']}`
- incident instance: `{manifest['incident_instance_id']}`
- attempt: `{manifest['attempt_id']}`
- Runner run ID: `{manifest['run_id']}`
- storage namespace: `{manifest['storage_namespace']}`

Canonical live event contract:

Each Worker must emit its own handoff in its assigned Matrix room.
Manager must not impersonate a Worker event. Every handoff message must contain
all five bindings below, exactly one event-kind line, and both artifact lines.
Artifact paths must be session-relative storage paths; never use host-private or
absolute paths:

- `session_id`: `{manifest['session_id']}`
- `task_instance_id`: `{manifest['task_instance_id']}`
- `incident_instance_id`: `{manifest['incident_instance_id']}`
- `attempt_id`: `{manifest['attempt_id']}`
- `run_id`: `{manifest['run_id']}`
- `LABOPS_INPUT_ARTIFACT: <session-relative input path>`
- `LABOPS_OUTPUT_ARTIFACT: <session-relative output path>`
- Incident Commander: `LABOPS_EVENT_KIND: manager_to_collector`
- Evidence Collector: `LABOPS_EVENT_KIND: collector_to_rca`
- RCA Analyst: `LABOPS_EVENT_KIND: rca_to_planner`
- Experiment Planner: `LABOPS_EVENT_KIND: approval_pending`
- Safe Executor: `LABOPS_EVENT_KIND: executor_to_auditor`
- Verification Auditor: `LABOPS_EVENT_KIND: verification_completed`

Stage events are separate from the six Agent handoffs above. They use the same
five bindings, are emitted once by the named real actor, and must never be
invented merely to advance the Reviewer timeline:

- A human-operated, non-Agent Matrix account: `LABOPS_EVENT_KIND: approval_granted`
  and `LABOPS_ACTOR: human-approver`. This approval event is not one of the six Agent handoffs.
  Send it only after inspecting the exact plan. The message and
  ApprovalGrant artifact must bind `approval_id`, `plan_id`,
  `canonical_plan_sha256`, `run_id`, `nonce`, decision `APPROVED`, scope and
  validity window. A Manager or Worker may request approval but cannot author it.
- Safe Executor, before the Gateway call: `LABOPS_EVENT_KIND: executor_to_gateway`
- Safe Executor, after the Gateway accepts the bound request:
  `LABOPS_EVENT_KIND: runner_started`
- Safe Executor, after immutable Runner outputs exist:
  `LABOPS_EVENT_KIND: runner_completed`
- Verification Auditor, after independent recomputation:
  `LABOPS_EVENT_KIND: terminal_decided`
- Incident Commander, only after the Auditor's verified terminal decision:
  `LABOPS_EVENT_KIND: commander_published`. This publication is not one of the
  six Agent handoffs and cannot replace `verification_completed`.

External Evidence publication contract:

The session namespace overrides the frozen prompt's legacy output path. Write
all new session output beneath the shared task namespace
`shared/tasks/{manifest['storage_namespace']}` and never overwrite the fixed
`shared/tasks/LABOPS-AT-004-EVAL-DRIFT/` artifacts. Relative to the session
namespace, publish these exact files; aliases, prose-only reports and renamed
files do not satisfy the contract:

- `artifacts/DEMO-EVAL-DRIFT-004/approval_grant.json`
- `runs/{manifest['run_id']}/gateway_request.json`
- `runs/{manifest['run_id']}/gateway_response.json`
- `runs/{manifest['run_id']}/run_result.json`
- `runs/{manifest['run_id']}/metrics.json`
- `runs/{manifest['run_id']}/artifact_manifest.json`
- `runs/{manifest['run_id']}/stdout.log`
- `runs/{manifest['run_id']}/stderr.log`
- `runs/{manifest['run_id']}/status.json`
- `verification/verification_report.json`
- `trace.jsonl`

The Gateway request must retain the exact ExperimentPlan, ApprovalGrant,
normalized Tool Contract, a `VALID` approval binding and one `CONSUMED` approval
record. The Gateway response and Runner files must bind the exact run ID. The
Runner result must record completed status, `network: none`,
and `sandbox_only: true`. Preserve that raw Runner result byte-for-byte. Put the
scenario classification in the separate status document with the exact run ID,
completed status, and the `simulated` field set to true.
Do not edit the raw Runner result to add this classification. The
artifact manifest must hash the immutable result, metrics, stdout and stderr
files byte-for-byte. Trace must be a non-empty append-only hash chain containing
all six Agent actors, the Runner invocation and the Auditor decision.

`verification/verification_report.json` must contain the five instance
bindings, `decision: PASS`, `verified_by: verification-auditor`, and a `checks`
value that is a non-empty JSON object, never an array. Because this run is a
simulated demo rather than a repaired production incident, its truthful terminal
fields are `resolution_status` = `DEMO_PASSED_NOT_RESOLVED`,
`demo_verification` = `PASSED`, `incident_state` =
`DEMO_PASSED_NOT_RESOLVED`, `underlying_issue_resolved` = false,
`has_postcondition` = true, and `is_demo_like` = true. Do not write `RESOLVED`
or `CLOSED` for this session.

The final structured Verification artifact must retain those same bindings and
must include `decision`, `verified_by`, and `resolution_status` plus its complete
independent checks. Do not replace these fields with prose. Emit each handoff
once; do not reuse an Approval nonce or rerun the Gateway merely to create an
event.

Keep the scenario task/incident identifiers in the ExperimentPlan for the fixed
Gateway allowlist, and record the instance bindings above in the live context,
Matrix handoffs, Trace and artifacts. A separate human must issue ApprovalGrant
v1 after the exact plan is available. The helper does not send this message,
approve the plan, run the Worker chain or invoke the Gateway.
"""
    session_prompt = frozen_prompt.replace(
        "RUN-LABOPS-AT-004-AGENTTEAMS-001",
        manifest["run_id"],
    )
    return (
        envelope
        + "\n"
        + orchestration
        + "\n---\n\n## Session-bound copy of the AT-004 Manager Prompt\n\n"
        + session_prompt
    )


def prepare_session(project_root: str | Path, sessions_root: str | Path, session_id: str) -> dict:
    """Create a new, non-overwritable live session envelope."""

    project_root = Path(project_root).resolve()
    sessions_root = Path(sessions_root).resolve()
    for relative in FORMAL_ROOTS:
        if _inside(sessions_root, project_root / relative):
            raise ValueError("live sessions cannot be stored inside formal Evidence roots")
    manifest = _session_manifest(session_id)
    _guard_run_id_collision(sessions_root, manifest)
    frozen_prompt = (
        project_root / "agentteams" / "prompts" / "eval_drift_task.md"
    ).read_text(encoding="utf-8")
    runtime_contract = _runtime_contract(project_root, manifest)
    session_root = sessions_root / session_id
    session_root.mkdir(parents=True, exist_ok=False)
    (session_root / "evidence").mkdir()
    _write_json(session_root / "session.json", manifest)
    (session_root / "manager_task.md").write_text(
        _manager_task(manifest, frozen_prompt, runtime_contract), encoding="utf-8"
    )
    return {
        "status": "PREPARED",
        "mode": "OPERATOR_PREPARATION_ONLY",
        "session_root": str(session_root),
        "session": manifest,
    }


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _load_evidence_json(root: Path, relative: str, errors: list[str]) -> dict:
    try:
        return _read_json(root / relative)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid live evidence {relative}: {type(exc).__name__}")
        return {}


def _verify_handoffs(evidence_root: Path, errors: list[str]) -> None:
    handoff = _load_evidence_json(evidence_root, "handoff_manifest.json", errors)
    matrix = _load_evidence_json(evidence_root, "matrix_events.json", errors)
    if handoff.get("agent_order") != ROLE_ORDER:
        errors.append("handoff Agent order does not contain the six canonical roles")
    handoffs = handoff.get("handoffs", [])
    if not isinstance(handoffs, list) or len(handoffs) != len(HANDOFFS):
        errors.append("handoff manifest must contain six real AgentTeams handoffs")
        return
    event_ids: list[str] = []
    for index, ((source, target), item) in enumerate(zip(HANDOFFS, handoffs), 1):
        if not isinstance(item, dict):
            errors.append(f"handoff {index} is not an object")
            continue
        if item.get("from_agent") != source or item.get("to_agent") != target:
            errors.append(f"handoff {index} role boundary does not match the six-role contract")
        event_id = item.get("matrix_event_id")
        if not isinstance(event_id, str) or not event_id.startswith("$"):
            errors.append(f"handoff {index} lacks a real Matrix event ID")
        else:
            event_ids.append(event_id)
        if item.get("status") not in {"COMPLETED", "VALID", "PASS"}:
            errors.append(f"handoff {index} is not complete")
        if not item.get("input_artifact_refs") or not item.get("output_artifact_refs"):
            errors.append(f"handoff {index} lacks input/output artifact references")
    if len(set(event_ids)) != len(HANDOFFS):
        errors.append("Matrix handoff event IDs must be six unique events")

    events = matrix.get("events", [])
    if not isinstance(events, list):
        errors.append("matrix_events.json must contain an events array")
        return
    event_map = {
        item.get("event_id"): item for item in events
        if isinstance(item, dict) and isinstance(item.get("event_id"), str)
    }
    for (source, _), event_id in zip(HANDOFFS, event_ids):
        event = event_map.get(event_id)
        if not event or event.get("sender_agent") != source:
            errors.append(f"Matrix event {event_id} is absent or has the wrong sender")
        elif not str(event.get("room_id", "")).startswith("!") or not event.get("timestamp"):
            errors.append(f"Matrix event {event_id} lacks room/time evidence")


def _skill_runtime_evidence(status: str = "BLOCKED") -> dict:
    return {
        "control-lab-action": {
            "status": status,
            "source": "evidence/gateway_request.json#tool_contract",
        },
        "remaining_skills": {
            "status": "CONFIGURED",
            "runtime_visibility": "AGENTTEAMS_HOOK_REQUIRED",
        },
    }


def _verify_execution(evidence_root: Path, manifest: dict, effective_attempt: dict,
                      recovery_active: bool, errors: list[str]) -> dict:
    skill_evidence = _skill_runtime_evidence()
    execution_error_start = len(errors)
    approval = _load_evidence_json(evidence_root, "approval_grant.json", errors)
    request = _load_evidence_json(evidence_root, "gateway_request.json", errors)
    response = _load_evidence_json(evidence_root, "gateway_response.json", errors)
    run_result = _load_evidence_json(evidence_root, "runner/run_result.json", errors)
    runner_manifest = _load_evidence_json(evidence_root, "runner/artifact_manifest.json", errors)
    verification = _load_evidence_json(evidence_root, "verification.json", errors)

    plan = request.get("experiment_plan")
    tool_contract = request.get("tool_contract")
    if not isinstance(plan, dict) or not isinstance(tool_contract, dict):
        errors.append("Gateway request lacks structured plan and Tool Contract")
        return skill_evidence
    try:
        normalized_contract = normalize_tool_contract(request)
    except (PermissionError, ValueError) as exc:
        errors.append(f"Gateway Tool Contract failed closed: {exc}")
        return skill_evidence
    if tool_contract != normalized_contract:
        errors.append("Gateway Tool Contract is not the complete normalized archive")
        return skill_evidence
    if (
        tool_contract.get("tool_id") != "labops.runner.execute"
        or tool_contract.get("caller_agent_id") != "safe-executor"
        or tool_contract.get("skill_id") != "control-lab-action"
    ):
        errors.append("Gateway Tool Contract has the wrong Tool, Agent or Skill binding")
        return skill_evidence
    if request.get("approval") != approval:
        errors.append("Gateway request ApprovalGrant differs from the human approval artifact")
    live_context = plan.get("live_context", {})
    expected_context = {
        "classification": CLASSIFICATION,
        "session_id": manifest["session_id"],
        "task_instance_id": manifest["task_instance_id"],
        "incident_instance_id": manifest["incident_instance_id"],
        "attempt_id": effective_attempt["attempt_id"],
        "storage_namespace": manifest["storage_namespace"],
    }
    if live_context != expected_context:
        errors.append("ExperimentPlan live context is not bound to this session")
    try:
        run_time = datetime.fromisoformat(str(run_result.get("start_time", "")).replace("Z", "+00:00"))
        validate_approval_grant(plan, approval, tool_contract, now=run_time)
    except (ApprovalBindingError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, ApprovalBindingError) else type(exc).__name__
        errors.append(f"ApprovalGrant binding failed: {reason}")
    if request.get("approval_binding", {}).get("status") != "VALID":
        errors.append("Gateway request lacks a VALID approval binding record")
    if request.get("approval_consumption", {}).get("status") != "CONSUMED":
        errors.append("Gateway request lacks a consumed one-time approval record")

    run_id = effective_attempt["run_id"]
    if response.get("ok") is not True or response.get("run_id") != run_id:
        errors.append("Gateway response does not prove a successful bound run")
    if run_result.get("run_id") != run_id or run_result.get("status") != "completed":
        errors.append("Runner result is absent, incomplete or belongs to another run")
    if run_result.get("network") != "none" or run_result.get("sandbox_only") is not True:
        errors.append("Runner result does not prove the sandbox/network boundary")

    artifacts = runner_manifest.get("artifacts", {})
    for name in ("run_result.json", "metrics.json", "stdout.log", "stderr.log"):
        path = evidence_root / "runner" / name
        record = artifacts.get(name, {}) if isinstance(artifacts, dict) else {}
        if not path.is_file() or record.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            errors.append(f"Runner artifact hash mismatch: {name}")

    if len(errors) == execution_error_start:
        skill_evidence["control-lab-action"]["status"] = "VERIFIED"

    checks = verification.get("checks", {})
    checks_complete = (
        isinstance(checks, dict)
        and bool(checks)
        and all(
            value is True
            or (isinstance(value, dict) and value.get("pass") is True)
            for value in checks.values()
        )
    )
    runner_status = {}
    runner_status_path = evidence_root / "runner" / "status.json"
    if runner_status_path.is_file():
        try:
            runner_status = _read_json(runner_status_path)
        except (OSError, ValueError, json.JSONDecodeError):
            runner_status = {}
    simulated = (
        run_result.get("simulated") is True
        or runner_status.get("simulated") is True
    )
    resolved_pass = (
        verification.get("resolution_status") == "RESOLVED"
        and not simulated
    )
    truthful_demo_pass = (
        simulated
        and verification.get("demo_verification") == "PASSED"
        and verification.get("incident_state") == "DEMO_PASSED_NOT_RESOLVED"
        and verification.get("underlying_issue_resolved") is False
        and verification.get("has_postcondition") is True
        and verification.get("is_demo_like") is True
    )
    if recovery_active and verification.get("attempt_id") != effective_attempt["attempt_id"]:
        errors.append("Auditor verification is not bound to the latest recovery attempt")
    if (
        verification.get("verified_by") != "verification-auditor"
        or verification.get("run_id") != run_id
        or verification.get("decision") != "PASS"
        or not checks_complete
        or not (resolved_pass or truthful_demo_pass)
    ):
        errors.append("Independent Verification Auditor did not produce a complete truthful PASS decision")
    return skill_evidence


def _effective_attempt(session_root: Path, manifest: dict, errors: list[str]) -> tuple[dict, str]:
    base = {
        "attempt_id": manifest["attempt_id"],
        "run_id": manifest["run_id"],
        "required_final_actor": "verification-auditor",
    }
    recovery_path = session_root / "recovery" / "recovery_trace.jsonl"
    if not recovery_path.is_file():
        return base, "ABSENT"
    try:
        overlay = load_recovery_overlay(session_root)
    except RecoveryError as exc:
        errors.append(f"Recovery overlay failed closed: {exc}")
        return base, "BLOCKED"
    if overlay.get("pending_takeover") is not None:
        errors.append("Human Takeover is still pending or accepted but not resumed")
        recovery_status = "BLOCKED"
    else:
        recovery_status = "VERIFIED"
    attempts = overlay.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        errors.append("Recovery overlay has no effective attempt")
        return base, "BLOCKED"
    effective = attempts[-1]
    if effective.get("required_final_actor") != "verification-auditor":
        errors.append("Recovery attempt does not preserve Auditor terminal authority")
    return effective, recovery_status


def _verify_trace(evidence_root: Path, errors: list[str]) -> None:
    trace_path = evidence_root / "trace.jsonl"
    try:
        trace = TraceLog(trace_path)
        ok, message = trace.verify_chain()
        records = trace.read()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"live Trace is unreadable: {type(exc).__name__}")
        return
    if not ok or not records:
        errors.append(f"live Trace failed integrity verification: {message}")
        return
    actors = {item.get("actor") for item in records}
    missing = sorted(set(ROLE_ORDER) - actors)
    if missing:
        errors.append("live Trace lacks Agent actors: " + ", ".join(missing))
    if not any(item.get("entity_type") == "runner" for item in records):
        errors.append("live Trace lacks Runner invocation")
    if not any(
        item.get("entity_type") == "verification"
        and item.get("actor") == "verification-auditor"
        and item.get("status") == "PASS"
        for item in records
    ):
        errors.append("live Trace lacks the Auditor PASS event")


def verify_session(project_root: str | Path, sessions_root: str | Path, session_id: str) -> dict:
    """Read and validate externally produced live evidence; never create it."""

    del project_root  # the session uses frozen repository contracts prepared above
    session_root = Path(sessions_root).resolve() / session_id
    errors: list[str] = []
    skill_runtime_evidence = _skill_runtime_evidence()
    try:
        manifest = _read_json(session_root / "session.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "BLOCKED",
            "classification": CLASSIFICATION,
            "executes_agentteams": False,
            "archived_replay_is_live": False,
            "skill_runtime_evidence": skill_runtime_evidence,
            "errors": [f"session.json: {type(exc).__name__}"],
        }
    if manifest != _session_manifest(session_id):
        errors.append("session.json differs from the prepared deterministic envelope")
    effective_attempt, recovery_status = _effective_attempt(session_root, manifest, errors)
    evidence_root = session_root / "evidence"
    for relative in EVIDENCE_FILES:
        if not (evidence_root / relative).is_file():
            errors.append(f"missing live evidence: {relative}")
    if not errors:
        _verify_handoffs(evidence_root, errors)
        skill_runtime_evidence = _verify_execution(
            evidence_root,
            manifest,
            effective_attempt,
            recovery_status == "VERIFIED",
            errors,
        )
        _verify_trace(evidence_root, errors)
    digests = []
    evidence_files = list(EVIDENCE_FILES)
    runner_status_relative = "runner/status.json"
    if (evidence_root / runner_status_relative).is_file():
        evidence_files.append(runner_status_relative)
    recovery_relative = "recovery/recovery_trace.jsonl"
    if (session_root / recovery_relative).is_file():
        evidence_files.append(recovery_relative)
    for relative in evidence_files:
        path = session_root / relative if relative == recovery_relative else evidence_root / relative
        if path.is_file():
            digests.append(f"{relative}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return {
        "status": "VERIFIED" if not errors else "BLOCKED",
        "classification": manifest.get("classification"),
        "session_id": session_id,
        "executes_agentteams": False,
        "archived_replay_is_live": False,
        "effective_attempt_id": effective_attempt.get("attempt_id"),
        "recovery_status": recovery_status,
        "skill_runtime_evidence": skill_runtime_evidence,
        "evidence_files": evidence_files,
        "evidence_digest": hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest(),
        "errors": errors,
    }
