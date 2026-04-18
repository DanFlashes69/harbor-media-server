[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan'
)

$ErrorActionPreference = 'Stop'

$taskName = 'Harbor Synology Movie Progress'
$scriptPath = Join-Path $PSScriptRoot 'Write-SynologyMovieProgress.ps1'
$escapedScript = $scriptPath.Replace('"', '""')
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$escapedScript`" -NasHost `"$NasHost`""
schtasks.exe /Create /TN $taskName /SC MINUTE /MO 5 /TR $taskCommand /F | Out-Null

