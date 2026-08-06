param(
    [string]$Version = 'v0.3.0-rc1',
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$python = Get-LabOpsPython $PythonPath
$docker = Get-LabOpsDocker
if ($Version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+-(?:rc[0-9]+|preliminary)$') { throw "Invalid release version" }
$releaseRoot = Join-Path $root "release\$Version"
if (Test-Path -LiteralPath $releaseRoot) { throw "Release directory already exists; refusing overwrite: $releaseRoot" }

Push-Location $root
try {
    $dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw "Git worktree must be clean before building a release" }
    Invoke-LabOpsChecked $python @('-B', 'scripts\scan_sensitive.py', '--repo-root', $root)
    Invoke-LabOpsChecked $python @('-B', 'scripts\verify_evidence.py')
    New-Item -ItemType Directory -Path (Join-Path $releaseRoot 'evidence') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $releaseRoot 'demo-fixture') -Force | Out-Null

    $sourceZip = Join-Path $releaseRoot 'labops-guard-source.zip'
    Invoke-LabOpsChecked 'git' @('archive', '--format=zip', "--output=$sourceZip", 'HEAD')

    $runnerTarAt003 = Join-Path $releaseRoot 'labops-pytorch-runner-0.1.0.tar'
    Invoke-LabOpsChecked $docker @('save', '--output', $runnerTarAt003, 'labops/pytorch-cpu-runner:0.1.0')
    $runnerTarAt004 = Join-Path $releaseRoot 'labops-pytorch-runner-0.2.0.tar'
    Invoke-LabOpsChecked $docker @('save', '--output', $runnerTarAt004, 'labops/pytorch-cpu-runner:0.2.0')
    $dashboardTar = Join-Path $releaseRoot 'labops-guard-dashboard-local.tar'
    & $docker image inspect 'labops-guard:local' *> $null
    if ($LASTEXITCODE -ne 0) { throw "Dashboard image labops-guard:local is missing" }
    Invoke-LabOpsChecked $docker @('save', '--output', $dashboardTar, 'labops-guard:local')

    $fixtureSource = Join-Path $root 'artifacts\DEMO-RCA-001\baseline\run-01'
    foreach ($required in @('eval_config.json', 'checkpoints\last.pt', 'checkpoints\best.pt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $fixtureSource $required) -PathType Leaf)) { throw "Fixture missing: $required" }
    }
    $fixtureZip = Join-Path $releaseRoot 'demo-fixture\LABOPS-AT-003-baseline-fixture.zip'
    Compress-Archive -Path (Join-Path $fixtureSource '*') -DestinationPath $fixtureZip -CompressionLevel Optimal

    Copy-Item -LiteralPath 'demo\output-agentteams-at002\LABOPS-AT-002-evidence-bundle.zip' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-002-evidence-bundle.zip')
    Copy-Item -LiteralPath 'demo\output-agentteams-at002\evidence_bundle_manifest.json' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-002-evidence-manifest.json')
    Copy-Item -LiteralPath 'demo\output-agentteams-at003\artifacts\DEMO-RCA-003\LABOPS-AT-003-evidence-bundle.zip' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-003-evidence-bundle.zip')
    Copy-Item -LiteralPath 'demo\output-agentteams-at003\artifacts\DEMO-RCA-003\evidence_bundle_manifest.json' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-003-evidence-manifest.json')
    Copy-Item -LiteralPath 'demo\output-agentteams-at004\LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-004-EVAL-DRIFT-evidence-bundle.zip')
    Copy-Item -LiteralPath 'demo\output-agentteams-at004\evidence_manifest.json' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-004-evidence-manifest.json')
    Copy-Item -LiteralPath 'demo\output-agentteams-at004\handoff_manifest.json' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-004-handoff-manifest.json')
    Copy-Item -LiteralPath 'demo\output-agentteams-at004-closure\LABOPS-AT-004-closure-v2.zip' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-004-closure-v2.zip')
    Copy-Item -LiteralPath 'memory\cases\LABOPS-AT-004-EVAL-DRIFT.json' -Destination (Join-Path $releaseRoot 'evidence\LABOPS-AT-004-case-memory.json')
    Copy-Item -LiteralPath 'RELEASE_NOTES.md' -Destination (Join-Path $releaseRoot 'RELEASE_NOTES.md')

    $commit = (git rev-parse HEAD).Trim()
    $imageIdAt003 = (& $docker image inspect 'labops/pytorch-cpu-runner:0.1.0' --format '{{.Id}}').Trim()
    $imageIdAt004 = (& $docker image inspect 'labops/pytorch-cpu-runner:0.2.0' --format '{{.Id}}').Trim()
    $manifest = [ordered]@{
        version = $Version
        git_commit = $commit
        runner_images = @(
            [ordered]@{ task = 'LABOPS-AT-003'; image = 'labops/pytorch-cpu-runner:0.1.0'; image_id = $imageIdAt003 },
            [ordered]@{ task = 'LABOPS-AT-004-EVAL-DRIFT'; image = 'labops/pytorch-cpu-runner:0.2.0'; image_id = $imageIdAt004 }
        )
        dashboard_image = 'labops-guard:local'
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        experiment_network = 'none'
        contains_credentials = $false
        main_demo = 'LABOPS-AT-004-EVAL-DRIFT'
        main_runner = 'labops/pytorch-cpu-runner:0.2.0'
        fallback_runner = 'labops/pytorch-cpu-runner:0.1.0'
        at002_state = 'BLOCKED'
        at003_state = 'PASS / RESOLVED'
        at004_state = 'PASS / RESOLVED'
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $releaseRoot 'release_manifest.json') -Encoding UTF8

    $checksumLines = Get-ChildItem -LiteralPath $releaseRoot -Recurse -File | Where-Object { $_.Name -ne 'checksums.sha256' } | Sort-Object FullName | ForEach-Object {
        $relative = Get-LabOpsRelativePath $releaseRoot $_.FullName
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
    $checksumLines | Set-Content -LiteralPath (Join-Path $releaseRoot 'checksums.sha256') -Encoding ascii
    & (Join-Path $PSScriptRoot 'verify_release.ps1') -ReleaseDirectory $releaseRoot
    Write-Host "Offline release ready: $releaseRoot" -ForegroundColor Green
} finally { Pop-Location }
