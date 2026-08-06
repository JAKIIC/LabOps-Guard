param(
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ProjectRoot "scripts\common.ps1")
$Python = Get-LabOpsPython $PythonPath

Push-Location $ProjectRoot
try {
    Invoke-LabOpsChecked $Python @("demos/checkpoint-regression/run_demo.py", "--output", "artifacts/DEMO-RCA-001/baseline", "--repeats", "3")
    Invoke-LabOpsChecked $Python @("-m", "labops", "run-incident", "--incident", "demos/checkpoint-regression/incident.json")
    Invoke-LabOpsChecked $Python @("-m", "labops", "run-incident", "--incident", "demos/checkpoint-regression/incident-policy-violation.json")
    Write-Host "LabOps Guard checkpoint demo completed: PASS + POLICY_VIOLATION/ROLLED_BACK" -ForegroundColor Green
} finally {
    Pop-Location
}
