param(
    [string]$PythonPath,
    [string]$At002Bundle,
    [string]$At002Manifest,
    [string]$At003Bundle,
    [string]$At003Manifest,
    [string]$At004Bundle,
    [string]$At004Manifest
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$python = Get-LabOpsPython $PythonPath
$arguments = @('-B', (Join-Path $PSScriptRoot 'verify_evidence.py'))
if ($At002Bundle) { $arguments += @('--at002-bundle', $At002Bundle) }
if ($At002Manifest) { $arguments += @('--at002-manifest', $At002Manifest) }
if ($At003Bundle) { $arguments += @('--at003-bundle', $At003Bundle) }
if ($At003Manifest) { $arguments += @('--at003-manifest', $At003Manifest) }
if ($At004Bundle) { $arguments += @('--at004-bundle', $At004Bundle) }
if ($At004Manifest) { $arguments += @('--at004-manifest', $At004Manifest) }
Invoke-LabOpsChecked $python $arguments
