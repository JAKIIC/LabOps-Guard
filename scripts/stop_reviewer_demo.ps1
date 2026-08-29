[CmdletBinding()]
param(
    [string]$SessionsRoot = "demo/live-sessions"
)

& python -B -m labops reviewer stop --sessions-root $SessionsRoot
exit $LASTEXITCODE
