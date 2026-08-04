Set-StrictMode -Version Latest

function Get-LabOpsDocker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) { return $fallback }
    throw "Docker CLI not found. Start Docker Desktop or add docker.exe to PATH."
}

function Get-LabOpsPython([string]$Preferred) {
    if ($Preferred) {
        $resolved = Resolve-Path -LiteralPath $Preferred -ErrorAction Stop
        return $resolved.Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $polar = "D:\APP\Anaconda\envs\polar\python.exe"
    if (Test-Path -LiteralPath $polar -PathType Leaf) { return $polar }
    throw "Python not found. Pass -PythonPath with a Python 3.9+ executable."
}

function Assert-LabOpsChildPath([string]$Path, [string]$Boundary) {
    $full = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetFullPath($Boundary).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $prefix = $root + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside boundary: $full"
    }
    return $full
}

function Get-LabOpsRelativePath([string]$Boundary, [string]$Path) {
    $root = [IO.Path]::GetFullPath($Boundary).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $prefix = $root + [IO.Path]::DirectorySeparatorChar
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing relative path outside boundary: $full"
    }
    return $full.Substring($prefix.Length).Replace('\', '/')
}

function Invoke-LabOpsChecked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE"
    }
}
