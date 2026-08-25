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

## Context without RAG

LabOps Guard does not claim a vector database or RAG pipeline. It implements three allowed context
mechanisms instead:

1. **Shared state:** Matrix events and MinIO artifacts carry schema-valid handoffs.
2. **Trace:** the append-only role/action chain records ordering, actor, hash and status.
3. **Case memory:** terminal postmortems are locally searchable, but never count as evidence for a
   new incident.

## Observability boundary

Trace, Log, Metrics, Artifact and Approval are implemented as files plus Matrix/MinIO records. A
future OpenTelemetry adapter is read-only: it may export signals, but cannot change incident state,
approval, hashes or the authoritative evidence bundle.
