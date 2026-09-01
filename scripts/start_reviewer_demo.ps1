[CmdletBinding()]
param(
    [ValidateSet("quick", "live")]
    [string]$Mode = "quick",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ReviewerArgs
)

$normalizedMode = $Mode.ToLowerInvariant()

if ($normalizedMode -eq "live") {
    if ([string]::IsNullOrWhiteSpace($env:LABOPS_LIVE_EVIDENCE_CONTAINER)) {
        $env:LABOPS_LIVE_EVIDENCE_CONTAINER = "hiclaw-manager"
    }
    if ([string]::IsNullOrWhiteSpace($env:LABOPS_LIVE_EVIDENCE_ROOT)) {
        $env:LABOPS_LIVE_EVIDENCE_ROOT = "/root/hiclaw-fs/shared/tasks/live-demo"
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
