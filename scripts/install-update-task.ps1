$ErrorActionPreference = 'Stop'

$TaskName = 'Harbor Media Stack Safe Update'
$RunUpdateCmd = Join-Path $PSScriptRoot 'run-safe-update.cmd'

if (-not (Test-Path -LiteralPath $RunUpdateCmd)) {
    throw "Update runner not found: $RunUpdateCmd"
}

$Action = New-ScheduledTaskAction -Execute $RunUpdateCmd
$Triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 4:30AM)
)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Description 'Runs Harbor Media Server safe update orchestration once per day.'

Write-Output "Registered scheduled task: $TaskName"
