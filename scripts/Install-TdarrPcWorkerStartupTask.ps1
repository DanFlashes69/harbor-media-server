[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$MediaDriveLetter = 'M',
    [string]$NodeName = 'PcGpuOverflowNode'
)

$ErrorActionPreference = 'Stop'

$taskName = 'Harbor Tdarr PC Worker'
$scriptPath = Join-Path $PSScriptRoot 'Invoke-TdarrPcWorkerCutover.ps1'
$escapedScript = $scriptPath.Replace('"', '""')
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$escapedScript`" -NasHost `"$NasHost`" -MediaDriveLetter `"$MediaDriveLetter`" -NodeName `"$NodeName`""

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

