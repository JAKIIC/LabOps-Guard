# AT-004 main demo runbook

This runbook presents the already verified AgentTeams evidence. It does not rerun or mutate the
formal incident unless the presenter explicitly chooses a fresh rehearsal workspace.

## Preflight

```powershell
./scripts/check_environment.ps1
./scripts/verify_evidence.ps1
./scripts/start_dashboard.ps1
```

Confirm AT-004 is `AGENTTEAMS_RUN`, `PASS / RESOLVED`, 27 ZIP entries, 26 allowlisted artifacts,
7 trace entries and `CHAIN_OK / ACCEPTED`. Confirm AT-002 and AT-003 remain separate.

## Story

1. Show `71.875% × 3` versus historical `97.8125% × 3`.
2. Show 10 hashed facts and four hypotheses; explain why unchanged checkpoint/data/metric and
   zero spread reject the alternatives.
3. Show the one-variable plan, finite CPU/30-second/three-repeat budget, forbidden changes and
   rollback.
4. Show human approval timestamp before execution.
5. Show Runner `0.2.0`, `network=none`, 8/8 capability checks and five raw outputs.
6. Show independent recomputation to `97.8124976% × 3`, protected hashes and only one changed path.
7. Show preserved first ISSUE, corrected 7-entry trace and final `PASS / RESOLVED`.
8. Close with AT-002 `BLOCKED`, AT-003 fallback and illegal metric rollback as safety evidence.

## Rules

- Do not call archived dashboard data a new live run.
- Do not use prompts or role descriptions as proof that an Agent ran.
- Do not say the Worker Auditor reran PyTorch.
- Do not overwrite the formal evidence bundle during rehearsal.
- If any integrity check fails, stop and report BLOCKED.
