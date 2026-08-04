param(
    [string]$PythonPath,
    [string]$FixtureZip,
    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$python = Get-LabOpsPython $PythonPath
if (-not $OutputRoot) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $OutputRoot = Join-Path $root "artifacts\release-validation\$stamp"
}
$arguments = @('-B', (Join-Path $PSScriptRoot 'run_local_demo.py'), '--repo-root', $root, '--output-root', $OutputRoot)
if ($FixtureZip) { $arguments += @('--fixture-zip', $FixtureZip) }
Invoke-LabOpsChecked $python $arguments
Write-Host "AT-003 local validation evidence: $OutputRoot" -ForegroundColor Green
