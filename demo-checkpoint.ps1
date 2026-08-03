$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "D:\APP\Anaconda\envs\d2l\python.exe"

Push-Location $ProjectRoot
try {
    & $Python demos\checkpoint-regression\run_demo.py --output artifacts\DEMO-RCA-001\baseline --repeats 3
    if ($LASTEXITCODE -ne 0) { throw "checkpoint baseline demo failed" }
    & $Python -m labops run-incident --incident demos\checkpoint-regression\incident.json
    if ($LASTEXITCODE -ne 0) { throw "valid repair incident failed" }
    & $Python -m labops run-incident --incident demos\checkpoint-regression\incident-policy-violation.json
    if ($LASTEXITCODE -ne 0) { throw "policy violation incident failed" }
    Write-Host "LabOps Guard checkpoint demo completed: PASS + POLICY_VIOLATION/ROLLED_BACK" -ForegroundColor Green
} finally {
    Pop-Location
}
