# LabOps Guard demo runbook — Windows PowerShell (REV-2).
# Self-contained: uses repo-relative demo/fixtures by default; overridable via env:
#   LABOPS_FIXTURES   -> dir containing the synthetic compatibility fixture and audit
#   LABOPS_OUTPUT     -> output workspace dir (default: <repo>\demo\output)
# Safe: dry-run first, risky SIMULATED, no network/install/train, no excluded-data reads.
$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FIXTURES = if ($env:LABOPS_FIXTURES) { $env:LABOPS_FIXTURES } else { Join-Path $ROOT "demo\fixtures" }
$SNAPSHOT = Join-Path $FIXTURES "project_snapshot_synthetic"
$AUDIT    = Join-Path $FIXTURES "synthetic_audit"
$VERIF    = Join-Path $FIXTURES "synthetic_snapshot_verification.json"
$ALLOWED  = Join-Path $ROOT "demo\synthetic_allowed_files.json"

$WS = if ($env:LABOPS_OUTPUT) { $env:LABOPS_OUTPUT } else { Join-Path $ROOT "demo\output" }
if (Test-Path $WS) { Remove-Item -Recurse -Force $WS }
New-Item -ItemType Directory -Force -Path $WS | Out-Null

Set-Location $ROOT

Write-Host "############ LabOps Guard Demo (synthetic compatibility) ############"
Write-Host "fixtures=$FIXTURES"
Write-Host "workspace=$WS"
Write-Host ""

Write-Host "### Full chain: init -> evidence -> diagnosis -> approval -> action -> verification -> trace"
python -B -m labops demo `
  --workspace $WS `
  --snapshot $SNAPSHOT `
  --audit-dir $AUDIT `
  --verification $VERIF `
  --allowed-list $ALLOWED
Write-Host ""

Write-Host "### Approval request log"
python -B -m labops approve list --workspace $WS
Write-Host ""

Write-Host "### Trace chain verification"
python -B -m labops trace --workspace $WS --verify
Write-Host ""

Write-Host "Demo artifacts written under $WS"
Get-ChildItem -Recurse -File $WS | ForEach-Object { $_.FullName }
