# Observability model

LabOps Guard uses five correlated evidence signals. The current implementation is local-first
and file-backed; it does **not** claim that an OpenTelemetry Collector, backend, or automatic
instrumentation is deployed.

## Signal model and storage boundaries

| Signal | What it proves | Current authoritative storage | Correlation keys |
|---|---|---|---|
| Trace | Role order, state transitions, handoffs, approval/run ordering, final audit | Matrix event metadata plus hash-chained `agentteams_trace.jsonl` in the evidence bundle | `task_id`, `incident_id`, `run_id`, `handoff`, `actor`, `event_id` |
| Log | What the isolated runtime wrote to stdout/stderr | Runner `stdout.log` and `stderr.log`, then allowlisted into MinIO and the evidence bundle | `run_id`, `task_id`, timestamps, return code |
| Metrics | Baseline/candidate values, repeats, spread, postcondition | Runner `metrics.json`; Verification Auditor independently recomputes from raw output | `run_id`, metric name, repeat index, value |
| Artifact | Immutable inputs/outputs and provenance | MinIO shared task path during AgentTeams execution; ZIP plus SHA-256 manifests for review | artifact path, SHA-256, producer role, `run_id` |
| Approval | The human decision and its ordering before mutation | Matrix approval event and `approval.json` inside the bundle | `approval_id`, `plan_id`, approver, decision, decision time |

Matrix is the coordination/event source, MinIO is the shared artifact exchange, the dedicated
Runner is the execution source, and the final evidence bundle is the portable review source.
The dashboard is a read-only projection: it recomputes integrity checks and must never become
an authority that can change incident state.

## Current custom trace contract

Each durable trace entry is a JSON object whose canonical serialization participates in the
hash chain. Required correlation fields are:

- `seq`, `timestamp`, `event`, `actor`, `task_id`, `incident_id`, and where applicable `run_id`;
- `input_artifacts` and `output_artifacts` as repository-relative or bundle-relative paths;
- `status`, `prev_hash`, and `hash`;
- Matrix `event_id` only when it is part of the real AgentTeams handoff evidence.

Stable event names use low-cardinality verbs such as `evidence_collected`,
`hypotheses_ranked`, `plan_approved_policy`, `approval_granted`, `run_executed`, and
`verification_completed`. Incident IDs, run IDs, paths, and hashes remain attributes rather
than being embedded in event names.

## Future OpenTelemetry mapping

OpenTelemetry currently treats traces, metrics, and logs as core telemetry signals, and models
point-in-time named events as log records. Its GenAI semantic conventions are still evolving and
have moved to a dedicated specification. Therefore the table below is a planned adapter contract,
not a statement of present instrumentation.

| LabOps field/event | Proposed OTel representation |
|---|---|
| One six-role incident workflow | Root span `labops.incident` with `gen_ai.operation.name=invoke_workflow` and `gen_ai.workflow.name=labops_guard_incident` |
| One role assignment | Child span `labops.agent.invoke` with `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name`, and a low-cardinality role attribute |
| Runner execution | Child span `labops.runner.execute` (or CLI execution span) with `run_id`, image, network policy, duration, and exit code |
| Approval/state transition | Named event such as `labops.approval.decided` or `labops.incident.state_changed` with timestamps and low-cardinality status |
| Runner stdout/stderr | Log records correlated with TraceId/SpanId; content redacted and bounded before export |
| Accuracy/repeat/duration | Metrics with metric name and low-cardinality result labels; incident/run IDs belong in trace/artifact correlation, not unbounded metric dimensions |
| Artifact/manifest | Span events containing relative path, SHA-256, size, and producer; file bodies stay in artifact storage |

Do not export prompts, model messages, tool arguments, secrets, private data, absolute host paths,
or entire artifacts as span attributes. The GenAI specification warns that message and tool
content may contain sensitive data. Prefer hashes, IDs, bounded summaries, and opt-in capture.

## Adapter boundary

A future `labops-otel-adapter` should consume the existing immutable JSON/JSONL artifacts after
they are written. It may translate them into OTLP spans, events, logs, and metrics, but it must
not sit on the approval path, mutate trace hashes, or become required for local verification.
If export fails, the incident evidence remains valid locally and the adapter reports its own
failure separately.

Compatibility work should pin a semantic-convention version, map fields in tests, and provide a
migration table before changing emitted names. This prevents a moving external convention from
silently changing the evidence contract.

## References

- [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/)
- [OpenTelemetry log model](https://opentelemetry.io/docs/concepts/signals/logs/)
- [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
- [OpenTelemetry GenAI attribute registry and migration notice](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [OpenTelemetry event conventions](https://opentelemetry.io/docs/specs/semconv/general/events/)
