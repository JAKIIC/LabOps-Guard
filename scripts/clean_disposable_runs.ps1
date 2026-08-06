[CmdletBinding(SupportsShouldProcess)]
param([string]$Path)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$boundary = Join-Path $root 'artifacts\release-validation'
if (-not $Path) { $Path = $boundary }
$target = [IO.Path]::GetFullPath($Path)
$boundaryFull = [IO.Path]::GetFullPath($boundary).TrimEnd([IO.Path]::DirectorySeparatorChar)
$boundaryPrefix = $boundaryFull + [IO.Path]::DirectorySeparatorChar
if ($target -ne $boundaryFull -and -not $target.StartsWith($boundaryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing path outside disposable boundary: $target"
}
if ($target -eq [IO.Path]::GetFullPath($root) -or $target -match 'output-agentteams-at00[234]') {
    throw "Refusing to remove protected project or formal evidence path"
}
if (Test-Path -LiteralPath $target) {
    if ($PSCmdlet.ShouldProcess($target, 'Remove disposable release-validation output')) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
