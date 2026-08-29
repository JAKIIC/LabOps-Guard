# Reviewer Reproducibility Pack Design

## Goal

Make the existing Reviewer Edition reproducible from a clean Windows or Linux host without
claiming that archived replay is a live AgentTeams run. The pack must pin the external
AgentTeams/HiClaw contract used by the project, validate every local prerequisite, keep credentials
outside the repository, and provide deterministic Quick/Live diagnostics.

## Scope

The pack covers installation verification, version locking, sanitized configuration, environment
preflight, Reviewer lifecycle wrappers, sample input/output, and failure diagnosis. It does not
vendor AgentTeams, copy credentials, publish Runner image archives, create Matrix events, approve a
plan, run an Agent, or alter formal AT-002/003/004 Evidence.

## Runtime lock

The historical live environment used AgentTeams under its legacy HiClaw v1.1.2 deployment
contract. The pack pins:

- release: `v1.1.2`;
- repository: `https://github.com/agentscope-ai/AgentTeams`;
- installer path: `install/hiclaw-install.ps1` at tag `v1.1.2`;
- installer SHA-256: `91a616ff80677d2329a6432c2c02c97ab6e397a027922943d8a34c7b53887c09`;
- LabOps package: `1.0.0rc1`;
- Runner: `labops/pytorch-cpu-runner:0.2.0`, Python `3.11.15`, PyTorch `2.5.1+cpu`,
  runtime network `none`.

Tuwunel/Matrix, Element, MinIO and the gateway are bundled by the pinned AgentTeams release. The
pack does not guess their internal image versions. A live preflight records observed container image
IDs locally without committing them.

## Machine-readable contract

`config/reviewer-runtime-lock.json` is the single source of pinned public component identifiers.
`schemas/reviewer_runtime_lock.schema.json` rejects unknown or incomplete locks. The lock contains
no credential fields.

`config/reviewer.env.example` names required variables with non-secret placeholders. A real local
environment file is ignored by Git and must never be included in Evidence or the submission ZIP.

## Verification interface

`python -B -m labops reviewer pack-check --mode quick|live` returns deterministic JSON.

- Quick checks the lock Schema, repository files, package version, formal Evidence, Skill Registry
  and Reviewer Quick prerequisites.
- Live additionally checks Docker, the pinned Runner image and labels, Matrix URL/token/room-map
  presence, six canonical rooms, and the external AgentTeams controller/manager presence.
- Results redact secret values, absolute paths, private room IDs and container environment data.
- Missing Live dependencies return `BLOCKED` with Quick/Public Replay fallback.

## Installation and lifecycle

The Windows installer helper downloads only the official version-tagged PowerShell installer,
verifies the pinned SHA-256, and stops. Executing the downloaded installer requires an explicit
human flag and remains interactive so credentials are never command-line defaults or committed
files.

Reviewer start wrappers run `pack-check` before the existing Reviewer preflight. Stop wrappers call
the exact local Reviewer lifecycle owner. They do not stop AgentTeams or delete its data. External
AgentTeams stop/uninstall remains an explicit operator action documented from the official runtime.

## Failure semantics

| Condition | Result |
|---|---|
| Runtime lock or Schema invalid | `BLOCKED / RUNTIME_LOCK_INVALID` |
| Installer hash mismatch | stop before execution |
| Quick repository or Evidence failure | `BLOCKED`, no mode advertised |
| AgentTeams/Matrix/Runner absent | Live `BLOCKED`, Quick fallback |
| Credential missing | Live `BLOCKED`, credential value never emitted |
| Room map malformed | Live `BLOCKED`, room IDs never emitted |
| Formal Evidence path selected for runtime output | refused by existing lifecycle boundary |

## Non-goals

- self-developed Agent runtime;
- public live execution service;
- automatic secret provisioning;
- automatic worker creation;
- Skill Invocation Ledger or Dynamic Reviewer Incident (next P0 task);
- modification or regeneration of formal Evidence.

## Acceptance

1. A clean host can identify exact public dependencies and run Quick Mode without credentials.
2. Live Mode fails closed with actionable missing requirements until real AgentTeams prerequisites
   exist.
3. The official installer cannot run through the helper unless its downloaded bytes match the
   pinned checksum and a human explicitly opts in.
4. No committed file contains a real Token, password, private room ID or host-specific absolute
   path.
5. Existing tests, Evidence hashes and Public Demo remain unchanged.
