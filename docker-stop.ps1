# Stop the local LabOps Guard dashboard container.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
docker compose down
