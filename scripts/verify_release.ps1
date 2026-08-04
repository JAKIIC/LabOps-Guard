param([Parameter(Mandatory=$true)][string]$ReleaseDirectory)

$ErrorActionPreference = "Stop"
$release = (Resolve-Path -LiteralPath $ReleaseDirectory -ErrorAction Stop).Path
$checksumFile = Join-Path $release 'checksums.sha256'
if (-not (Test-Path -LiteralPath $checksumFile -PathType Leaf)) { throw "checksums.sha256 missing" }
$checked = 0
foreach ($line in Get-Content -LiteralPath $checksumFile) {
    if (-not $line.Trim()) { continue }
    if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { throw "Invalid checksum line" }
    $expected = $Matches[1].ToLowerInvariant()
    $relative = $Matches[2].Replace('/', [IO.Path]::DirectorySeparatorChar)
    $candidate = [IO.Path]::GetFullPath((Join-Path $release $relative))
    $prefix = $release.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe checksum path" }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Missing release file: $relative" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidate).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Checksum mismatch: $relative" }
    $checked++
}
Write-Host "Release checksum verification PASS: $checked files" -ForegroundColor Green
