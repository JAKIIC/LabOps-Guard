[CmdletBinding()]
param(
    [ValidateSet("quick", "live")]
    [string]$Mode = "quick",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ReviewerArgs
)

$normalizedMode = $Mode.ToLowerInvariant()

& python -B -m labops reviewer preflight --mode $normalizedMode
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& python -B -m labops reviewer start --mode $normalizedMode @ReviewerArgs
exit $LASTEXITCODE
