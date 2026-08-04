param([switch]$OfflineRefresh)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$docker = Get-LabOpsDocker
Push-Location $root
try {
    if ($OfflineRefresh) {
        Invoke-LabOpsChecked $docker @('build', '--pull=false', '-f', 'Dockerfile.dashboard-refresh', '-t', 'labops-guard:local', '.')
    }
    Invoke-LabOpsChecked $docker @('compose', '-f', 'compose.yaml', 'up', '-d', '--no-build')
    $healthy = $false
    foreach ($attempt in 1..20) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/healthz' -TimeoutSec 2
            if ($health.ok) { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $healthy) { throw "Dashboard did not become healthy at http://127.0.0.1:8787/" }
    Write-Host "Dashboard ready: http://127.0.0.1:8787/" -ForegroundColor Green
} finally { Pop-Location }
