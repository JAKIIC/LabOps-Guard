$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$docker = Get-LabOpsDocker
Push-Location $root
try { Invoke-LabOpsChecked $docker @('compose', '-f', 'compose.yaml', 'down') }
finally { Pop-Location }
