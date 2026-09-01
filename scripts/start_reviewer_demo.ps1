[CmdletBinding()]
param(
    [ValidateSet("quick", "live")]
    [string]$Mode = "quick",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ReviewerArgs
)

$normalizedMode = $Mode.ToLowerInvariant()

if ($normalizedMode -eq "live") {
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $sourceConfigPath = Join-Path $projectRoot "config/reviewer-evidence-source.json"
    $sourceConfig = Get-Content -Raw -LiteralPath $sourceConfigPath | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($env:LABOPS_LIVE_EVIDENCE_CONTAINER)) {
        $env:LABOPS_LIVE_EVIDENCE_CONTAINER = [string]$sourceConfig.container
    }
    if ([string]::IsNullOrWhiteSpace($env:LABOPS_LIVE_EVIDENCE_ROOT)) {
        $env:LABOPS_LIVE_EVIDENCE_ROOT = [string]$sourceConfig.root
    }
}

& python -B -m labops reviewer pack-check --mode $normalizedMode
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& python -B -m labops reviewer preflight --mode $normalizedMode
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& python -B -m labops reviewer start --mode $normalizedMode @ReviewerArgs
exit $LASTEXITCODE
