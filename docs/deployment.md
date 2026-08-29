# Offline deployment and reproduction

## Requirements

- Windows 10/11 with Docker Desktop and PowerShell 5.1+;
- Python 3.9+ for the control plane; PyTorch remains pinned inside Runner images;
- at least 4 GB free memory and 3 GB free disk.

Run from the repository root:

```powershell
./scripts/check_environment.ps1
./scripts/verify_evidence.ps1
```

## External runtime version record

The source package pins Python, Runner and the historically verified AgentTeams legacy deployment
contract in `config/reviewer-runtime-lock.json`. AgentTeams is fixed to `v1.1.2`; Matrix/Element,
MinIO and the gateway are bundled by that release, while their observed image IDs must be recorded
during a new live preflight rather than guessed in source. Run
`python -B -m labops reviewer pack-check --mode quick|live` and use
[`toolchain-compatibility-matrix.md`](toolchain-compatibility-matrix.md) for component roles,
permissions and migration boundaries, and [`final-demo-guide.md`](final-demo-guide.md) for the
recording-time readiness checks. Record only product/version/model identifiers; never copy Tokens,
private room IDs or host credentials into evidence.

The clean-host sequence, checksum-pinned official installer helper, sanitized environment template,
sample outputs and diagnosis table are in
[`reviewer-reproducibility-pack.md`](reviewer-reproducibility-pack.md). The helper does not vendor or
silently execute AgentTeams; execution requires an explicit human version confirmation.

## Main and fallback runners

- Main AT-004 image: `labops/pytorch-cpu-runner:0.2.0`.
- Fallback AT-003 image: `labops/pytorch-cpu-runner:0.1.0`.
- Every experiment run is CPU-only and network-disabled. Image building or loading is a separate
  preparation step and may require access to official registries.

For a future offline Release, first verify its checksum manifest, then load both Runner archives
and the dashboard archive with `scripts/load_runner_image.ps1`. Do not generate or publish a
Release until the repository is clean and the user has confirmed version, remote, and tag timing.

Start the read-only dashboard with `scripts/start_dashboard.ps1`; stop it with
`scripts/stop_labops.ps1`. The dashboard should show AT-004 as the main `PASS / RESOLVED` case,
AT-003 as fallback, AT-002 as `BLOCKED`, and the illegal metric case as
`POLICY_VIOLATION / ROLLED_BACK`.

## Failure behavior

| Failure | Expected behavior |
|---|---|
| Docker or Runner missing | RuntimeCapabilityCheck fails and the case stays BLOCKED |
| Evidence ZIP changed | Verification fails; never skip hashes |
| Trace duplicate/broken | Auditor preserves ISSUE and refuses closure |
| Human rejects approval | Runner never starts |
| Matrix wake-up fails | Explicitly start the same Worker and retain real audit output; never invent an event |
