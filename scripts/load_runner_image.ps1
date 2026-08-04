param(
    [string]$Archive = (Join-Path (Split-Path -Parent $PSScriptRoot) 'release\v0.2.0-rc1\labops-pytorch-runner-0.1.0.tar'),
    [string]$Checksums,
    [string]$DashboardArchive
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$docker = Get-LabOpsDocker
$archivePath = (Resolve-Path -LiteralPath $Archive -ErrorAction Stop).Path
if (-not $Checksums) { $Checksums = Join-Path (Split-Path -Parent $archivePath) 'checksums.sha256' }
if (Test-Path -LiteralPath $Checksums) {
    $name = [IO.Path]::GetFileName($archivePath)
    $line = Get-Content -LiteralPath $Checksums | Where-Object { $_ -match "  $([regex]::Escape($name))$" } | Select-Object -First 1
    if (-not $line) { throw "No checksum entry for $name" }
    $expected = ($line -split '\s+', 2)[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Runner image archive checksum mismatch" }
}
Invoke-LabOpsChecked $docker @('load', '--input', $archivePath)
$labelsRaw = & $docker image inspect 'labops/pytorch-cpu-runner:0.1.0' --format '{{json .Config.Labels}}'
if ($LASTEXITCODE -ne 0) { throw "Loaded image cannot be inspected" }
$labels = $labelsRaw | ConvertFrom-Json
if ($labels.'io.labops.runner.torch' -ne '2.5.1+cpu' -or $labels.'io.labops.runner.network-runtime' -ne 'none') {
    throw "Loaded Runner labels do not match the frozen contract"
}
Write-Host "Runner image loaded and contract verified." -ForegroundColor Green
if (-not $DashboardArchive) {
    $candidate = Join-Path (Split-Path -Parent $archivePath) 'labops-guard-dashboard-local.tar'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $DashboardArchive = $candidate }
}
if ($DashboardArchive) {
    $dashboardPath = (Resolve-Path -LiteralPath $DashboardArchive -ErrorAction Stop).Path
    Invoke-LabOpsChecked $docker @('load', '--input', $dashboardPath)
    & $docker image inspect 'labops-guard:local' *> $null
    if ($LASTEXITCODE -ne 0) { throw "Dashboard archive did not restore labops-guard:local" }
    Write-Host "Dashboard image loaded." -ForegroundColor Green
}
