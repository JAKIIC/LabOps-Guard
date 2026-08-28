# Tool and context equivalence

This document states what is implemented today and where optional ecosystem adapters fit.

## MCP-equivalent tool contract

The current Runner Gateway is a local HTTP/JSON adapter, not an MCP Server. Every accepted request
is normalized into `schemas/tool_contract.schema.json` while legacy `/v1/run` callers remain
compatible. The contract records tool/caller/Skill/task/incident/run identity, approval reference,
allowed side effects, protected resources, resource budget, idempotency, postconditions and audit
context.

| Concern | Current contract | Future adapter boundary |
|---|---|---|
| Input | Schema-validated ExperimentPlan + Approval; fixed size and IDs | Map the same schema to an MCP tool invocation |
| Authorization | Image, command, path, task, incident and run allowlists | Add workload identity, mTLS/OIDC and scoped tool grants |
| Failure | Structured 4xx/5xx and fail-closed capability/policy errors | Preserve error codes through MCP transport |
| Audit | Request/response, approval time, Runner manifest and Trace | Emit read-only telemetry without changing evidence |

Adding MCP would change transport, not the approval, execution, verification or evidence semantics.

Stable failure codes are `INVALID_SCHEMA`, `UNAUTHORIZED_AGENT`, `APPROVAL_REQUIRED`,
`POLICY_DENIED`, `TASK_NOT_ALLOWLISTED`, `RUN_ID_CONFLICT`, `RUNNER_TIMEOUT`,
`EVIDENCE_INCOMPLETE` and `VERIFICATION_FAILED`. The Gateway fails closed and archives the
normalized contract with its response.

### Official MCP-equivalent contract checklist

| Official concern | Current implementation |
|---|---|
| Protocol / entry | Local HTTP/JSON: `POST /v1/run`; readiness: `GET /healthz` |
| Authentication / authorization | Trusted-network boundary plus fixed caller, task, image, command and path allowlists; this is policy identity, not mTLS/OIDC |
| Input Schema | `schemas/tool_contract.schema.json`, ExperimentPlan and ApprovalGrant v1 |
| Return Schema | Gateway response plus Runner result, metrics, manifest, bounded stdout/stderr and structured error |
| Tool permission | `safe-executor` only; side effects, protected resources and resource budget are explicit |
| Retry | No hidden retry; Recovery permits one retry only when the operation is idempotent and `safe_to_retry` |
| Idempotency | `run_id`, `idempotency_key` and approval nonce; conflicts and replay fail closed |
| Audit | Normalized request/response, approval identity/time, Runner manifest and hash-chained Trace |
| Degradation | Missing Gateway/Runner or incomplete evidence remains `BLOCKED`; archived replay is never presented as a live call |
| MCP migration | Add one transport adapter and preserve current Schema, error codes, approval and audit semantics; production authentication remains separate work |

## Context without RAG

LabOps Guard does not claim a vector database or RAG pipeline. Under the official non-RAG path it
implements two qualifying context mechanisms:

1. **Shared State:** Matrix events and MinIO artifacts carry schema-valid handoffs, identifiers,
   relative paths and hashes between roles.
2. **Trace Observability:** the append-only role/action chain records ordering, actor, state, hash,
   tool execution and terminal authority.

The local Case Memory is a supplemental exact-match/postmortem index. It has no vector semantic
retrieval and therefore is **not** counted toward the official two-of-three alternative gate. It
also never substitutes historical facts for Evidence in a new incident.

Effectiveness is verified by handoff/Trace contract tests, archived Evidence replay, hash-chain
verification and the Trust Evaluation Suite's false-resolution and evidence-completeness cases.
RAG is intentionally omitted because the fixed laboratory fixture does not require external
knowledge retrieval; adding it would introduce retrieval authorization, provenance and data
boundary risks without improving this governed execution chain.

## Observability boundary

Trace, Log, Metrics, Artifact and Approval are implemented as files plus Matrix/MinIO records. A
future OpenTelemetry adapter is read-only: it may export signals, but cannot change incident state,
approval, hashes or the authoritative evidence bundle.
