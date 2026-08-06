param(
    [string]$Archive = (Join-Path (Split-Path -Parent $PSScriptRoot) 'release\v0.2.0-rc1\labops-pytorch-runner-0.1.0.tar'),
    [string]$Checksums,
    [string]$DashboardArchive,
    [string]$At004Archive
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$docker = Get-LabOpsDocker
$archivePath = (Resolve-Path -LiteralPath $Archive -ErrorAction Stop).Path
if (-not $Checksums) { $Checksums = Join-Path (Split-Path -Parent $archivePath) 'checksums.sha256' }
if (-not (Test-Path -LiteralPath $Checksums -PathType Leaf)) { throw "checksums.sha256 missing" }

function Assert-ReleaseArchiveChecksum([string]$Path, [string]$ChecksumFile) {
    $name = [IO.Path]::GetFileName($Path)
    $line = Get-Content -LiteralPath $ChecksumFile | Where-Object { $_ -match "  $([regex]::Escape($name))$" } | Select-Object -First 1
    if (-not $line) { throw "No checksum entry for $name" }
    $expected = ($line -split '\s+', 2)[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Release archive checksum mismatch: $name" }
}
Assert-ReleaseArchiveChecksum $archivePath $Checksums
Invoke-LabOpsChecked $docker @('load', '--input', $archivePath)
$labelsRaw = & $docker image inspect 'labops/pytorch-cpu-runner:0.1.0' --format '{{json .Config.Labels}}'
if ($LASTEXITCODE -ne 0) { throw "Loaded image cannot be inspected" }
$labels = $labelsRaw | ConvertFrom-Json
if ($labels.'io.labops.runner.torch' -ne '2.5.1+cpu' -or $labels.'io.labops.runner.network-runtime' -ne 'none') {
    throw "Loaded Runner labels do not match the frozen contract"
}
Write-Host "Runner image loaded and contract verified." -ForegroundColor Green
if (-not $At004Archive) {
    $candidate = Join-Path (Split-Path -Parent $archivePath) 'labops-pytorch-runner-0.2.0.tar'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $At004Archive = $candidate }
}
if ($At004Archive) {
    $at004Path = (Resolve-Path -LiteralPath $At004Archive -ErrorAction Stop).Path
    Assert-ReleaseArchiveChecksum $at004Path $Checksums
    Invoke-LabOpsChecked $docker @('load', '--input', $at004Path)
    $at004Labels = (& $docker image inspect 'labops/pytorch-cpu-runner:0.2.0' --format '{{json .Config.Labels}}') | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $at004Labels.'io.labops.runner.torch' -ne '2.5.1+cpu' -or $at004Labels.'io.labops.runner.network-runtime' -ne 'none') {
        throw "Loaded AT-004 Runner labels do not match the frozen contract"
    }
    Write-Host "AT-004 Runner image loaded and contract verified." -ForegroundColor Green
}
if (-not $DashboardArchive) {
    $dashboardCandidate = Join-Path (Split-Path -Parent $archivePath) 'labops-guard-dashboard-local.tar'
    if (Test-Path -LiteralPath $dashboardCandidate -PathType Leaf) { $DashboardArchive = $dashboardCandidate }
}
if ($DashboardArchive) {
    $dashboardPath = (Resolve-Path -LiteralPath $DashboardArchive -ErrorAction Stop).Path
    Assert-ReleaseArchiveChecksum $dashboardPath $Checksums
    Invoke-LabOpsChecked $docker @('load', '--input', $dashboardPath)
    & $docker image inspect 'labops-guard:local' *> $null
    if ($LASTEXITCODE -ne 0) { throw "Dashboard archive did not restore labops-guard:local" }
    Write-Host "Dashboard image loaded." -ForegroundColor Green
}
