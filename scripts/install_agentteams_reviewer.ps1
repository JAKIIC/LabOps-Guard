[CmdletBinding()]
param(
    [string]$RuntimeLock,
    [string]$SourcePath,
    [string]$Destination,
    [switch]$Execute,
    [string]$ConfirmVersion
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
if (-not $RuntimeLock) { $RuntimeLock = Join-Path $root "config/reviewer-runtime-lock.json" }
if (-not $Destination) {
    $Destination = Join-Path $root ".cache/agentteams/hiclaw-install-v1.1.2.ps1"
}

try {
    $lock = Get-Content -LiteralPath $RuntimeLock -Raw -Encoding UTF8 | ConvertFrom-Json
    $version = [string]$lock.agentteams.version
    $installerUrl = [string]$lock.agentteams.installer_url
    $expectedSha = ([string]$lock.agentteams.installer_sha256).ToLowerInvariant()
    if ($version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') { throw "INVALID_VERSION" }
    if ($installerUrl -notmatch '^https://raw\.githubusercontent\.com/agentscope-ai/(?:AgentTeams|HiClaw)/v[0-9]+\.[0-9]+\.[0-9]+/install/hiclaw-install\.ps1$' -and -not $SourcePath) {
        throw "UNTRUSTED_INSTALLER_URL"
    }
    if ($expectedSha -notmatch '^[0-9a-f]{64}$') { throw "INVALID_INSTALLER_SHA256" }

    $destinationPath = [IO.Path]::GetFullPath($Destination)
    $destinationParent = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    if ($SourcePath) {
        Copy-Item -LiteralPath $SourcePath -Destination $destinationPath -Force
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $installerUrl -OutFile $destinationPath
    }

    $actualSha = (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha -ne $expectedSha) {
        Remove-Item -LiteralPath $destinationPath -Force -ErrorAction SilentlyContinue
        throw "INSTALLER_SHA256_MISMATCH"
    }

    $executed = $false
    if ($Execute) {
        if ($ConfirmVersion -ne $version) { throw "EXPLICIT_VERSION_CONFIRMATION_REQUIRED" }
        $previousHiClawVersion = $env:HICLAW_VERSION
        $previousAgentTeamsVersion = $env:AGENTTEAMS_VERSION
        try {
            $env:HICLAW_VERSION = $version
            $env:AGENTTEAMS_VERSION = $version
            & pwsh -NoProfile -ExecutionPolicy Bypass -File $destinationPath
            if ($LASTEXITCODE -ne 0) { throw "AGENTTEAMS_INSTALLER_FAILED" }
            $executed = $true
        } finally {
            $env:HICLAW_VERSION = $previousHiClawVersion
            $env:AGENTTEAMS_VERSION = $previousAgentTeamsVersion
        }
    }

    [ordered]@{
        status = if ($executed) { "EXECUTED" } else { "VERIFIED_DOWNLOAD" }
        version = $version
        sha256 = $actualSha
        executed = $executed
        source = if ($SourcePath) { "LOCAL_TEST_OR_CACHE" } else { "OFFICIAL_VERSIONED_URL" }
    } | ConvertTo-Json -Compress
    exit 0
} catch {
    [ordered]@{
        status = "BLOCKED"
        error = $_.Exception.Message
        executed = $false
    } | ConvertTo-Json -Compress
    exit 2
}
