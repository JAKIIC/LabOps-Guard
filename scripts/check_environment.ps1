param([string]$PythonPath)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$docker = Get-LabOpsDocker
$python = Get-LabOpsPython $PythonPath
$image = "labops/pytorch-cpu-runner:0.1.0"

$required = @(
    "compose.yaml",
    "runner\Dockerfile",
    "demos\checkpoint-regression\evaluate.py",
    "demo\output-agentteams-at002\LABOPS-AT-002-evidence-bundle.zip",
    "demo\output-agentteams-at003\artifacts\DEMO-RCA-003\LABOPS-AT-003-evidence-bundle.zip"
)
$fileChecks = @{}
foreach ($item in $required) { $fileChecks[$item] = Test-Path -LiteralPath (Join-Path $root $item) -PathType Leaf }

& $docker version --format '{{.Server.Version}}' *> $null
$daemon = $LASTEXITCODE -eq 0
$labelsRaw = if ($daemon) { & $docker image inspect $image --format '{{json .Config.Labels}}' 2>$null } else { $null }
$imageExists = $LASTEXITCODE -eq 0 -and $labelsRaw
$labels = if ($imageExists) { $labelsRaw | ConvertFrom-Json } else { $null }
$labelChecks = [ordered]@{
    image = $imageExists -and $labels.'io.labops.runner.image' -eq $image
    python = $imageExists -and $labels.'io.labops.runner.python' -eq '3.11.15'
    torch = $imageExists -and $labels.'io.labops.runner.torch' -eq '2.5.1+cpu'
    runtime_network = $imageExists -and $labels.'io.labops.runner.network-runtime' -eq 'none'
}

$envRaw = if ($imageExists) { & $docker image inspect $image --format '{{json .Config.Env}}' } else { '[]' }
$envNames = @($envRaw | ConvertFrom-Json | ForEach-Object { ($_ -split '=', 2)[0] })
$credentialNames = @($envNames | Where-Object { $_ -match '(?i)(API_KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL)' })
$probe = $null
if ($imageExists) {
    $probeRaw = & $docker run --rm --network none --entrypoint python $image -W ignore -B -c "import json,sys,torch;print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__,'cuda':torch.cuda.is_available()}))"
    if ($LASTEXITCODE -eq 0) { $probe = $probeRaw | ConvertFrom-Json }
}
$pythonVersion = & $python -B -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"
$result = [ordered]@{
    status = if ($daemon -and ($fileChecks.Values -notcontains $false) -and ($labelChecks.Values -notcontains $false) -and $credentialNames.Count -eq 0 -and $probe -and $probe.cuda -eq $false) { 'PASS' } else { 'FAIL' }
    docker_daemon = $daemon
    runner_image = $imageExists
    runner_labels = $labelChecks
    runner_probe = $probe
    credential_env_keys_present = $credentialNames.Count -gt 0
    host_python = $pythonVersion
    required_files = $fileChecks
}
$result | ConvertTo-Json -Depth 6
if ($result.status -ne 'PASS') { exit 1 }
