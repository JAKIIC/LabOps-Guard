# Reviewer Reproducibility Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a version-pinned, credential-safe and machine-verifiable Reviewer Edition reproduction pack.

**Architecture:** Add a strict JSON runtime lock and a focused Python verifier beside the existing Reviewer lifecycle. Thin PowerShell/shell wrappers call the verifier and existing lifecycle; the external AgentTeams installer is downloaded from a version-tagged official URL and checksum-verified before any optional human-approved execution.

**Tech Stack:** Python 3.9+ standard library, JSON/JSON Schema, PowerShell 7+, POSIX shell, Docker CLI, existing Reviewer Edition.

**Spec:** `docs/superpowers/specs/2026-08-29-reviewer-reproducibility-pack-design.md`

## Global Constraints

- Six Agents and seven Skills remain unchanged.
- Trust Contract v1 and Trust State Machine v1 remain unchanged.
- Formal AT-002/003/004 Evidence is read-only and must retain its SHA-256.
- Quick Mode is archived replay; Live Mode requires external AgentTeams facts.
- No real credential, private room ID, host absolute path or Runner image archive is committed.
- Every production behavior is implemented RED -> GREEN.

---

### Task 1: Runtime lock and deterministic pack verifier

**Files:**
- Create: `schemas/reviewer_runtime_lock.schema.json`
- Create: `config/reviewer-runtime-lock.json`
- Create: `config/reviewer.env.example`
- Create: `labops/reproducibility.py`
- Create: `tests/test_reproducibility.py`
- Modify: `labops/cli.py`

**Interfaces:**
- Consumes: project root, mode, runtime lock, optional environment and injected Docker probe.
- Produces: `build_pack_report(project_root, mode, runtime_lock, *, environment=None, docker_probe=None) -> dict` and `reviewer pack-check` JSON.

- [ ] Write tests proving Quick validates the repository and lock without credentials.
- [ ] Run the tests and confirm failure because `labops.reproducibility` is absent.
- [ ] Implement strict lock loading, schema validation and Quick report.
- [ ] Run the Quick tests until green.
- [ ] Write tests proving Live redacts credentials, validates six roles, requires pinned Runner labels and reports missing AgentTeams services.
- [ ] Confirm the new Live tests fail for the missing behavior.
- [ ] Implement the injected Docker/service probe and fail-closed Live report.
- [ ] Add `reviewer pack-check --mode --runtime-lock` to the CLI.
- [ ] Run `tests/test_reproducibility.py` and existing Reviewer tests.

### Task 2: Checksum-pinned installer and lifecycle wrappers

**Files:**
- Create: `scripts/install_agentteams_reviewer.ps1`
- Create: `scripts/stop_reviewer_demo.ps1`
- Create: `scripts/stop_reviewer_demo.sh`
- Modify: `scripts/start_reviewer_demo.ps1`
- Modify: `scripts/start_reviewer_demo.sh`
- Modify: `tests/test_reproducibility.py`

**Interfaces:**
- Consumes: the runtime lock and existing Reviewer CLI.
- Produces: checksum-verified installer download, pack-check-before-start, exact Reviewer stop request.

- [ ] Add integration tests that run wrappers with controlled executables and prove start refuses a failed pack check.
- [ ] Confirm wrapper tests fail before script changes.
- [ ] Implement the Windows checksum-verified download helper with an explicit execution switch.
- [ ] Modify start wrappers to run pack-check before existing preflight.
- [ ] Add stop wrappers that call only `labops reviewer stop`.
- [ ] Run wrapper and CLI tests until green.

### Task 3: Operator documentation and sample I/O

**Files:**
- Create: `docs/reviewer-reproducibility-pack.md`
- Create: `docs/samples/reviewer-pack-check-quick.json`
- Create: `docs/samples/reviewer-pack-check-live-blocked.json`
- Modify: `docs/reviewer-edition.md`
- Modify: `docs/deployment.md`
- Modify: `README.md`
- Modify: `THIRD_PARTY_NOTICES.md`

**Interfaces:**
- Consumes: verified commands and report fields from Tasks 1-2.
- Produces: clean-host Quick/Live runbook, exact fallback behavior, troubleshooting and dependency/license disclosure.

- [ ] Run the real Quick command and capture its sanitized output.
- [ ] Run Live pack-check without credentials and capture truthful `BLOCKED` output.
- [ ] Document install, configure, start, status, stop, verification and diagnosis in order.
- [ ] Document the AgentTeams Apache-2.0 dependency and the no-vendoring boundary.
- [ ] Scan samples and docs for credentials, private rooms and absolute host paths.

### Task 4: Phase verification and commit

**Files:**
- Modify only if verification exposes a defect in Task 1-3 files.

**Interfaces:**
- Consumes: the complete P0-1 patch.
- Produces: fresh verification evidence and one isolated commit.

- [ ] Run the focused Reproducibility and Reviewer tests.
- [ ] Run the complete test suite.
- [ ] Verify formal AT-002/003/004 Evidence hashes.
- [ ] Run Public Demo stale check and sensitive-information scan.
- [ ] Confirm no diff in Trust Contract, State Machine, Skill Registry or formal Evidence.
- [ ] Review the complete Git diff for scope and secret safety.
- [ ] Commit as `feat: add reviewer reproducibility pack`.
- [ ] Stop and report; do not enter Skill Ledger implementation.
