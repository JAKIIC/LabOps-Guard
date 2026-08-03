# LabOps Guard Docker one-click launcher (Windows).
param([switch]$Rebuild)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker command not found. Please start Docker Desktop and retry."
}

docker image inspect labops-guard:local *> $null
$ImageExists = ($LASTEXITCODE -eq 0)

if ($Rebuild -or -not $ImageExists) {
    docker compose up --build --detach
} else {
    docker compose up --detach --no-build
}
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "LabOps Guard is starting: http://127.0.0.1:8787"
Write-Host "Stop it later with: docker compose down"
Write-Host "Rebuild after code changes with: .\docker-start.ps1 -Rebuild"
