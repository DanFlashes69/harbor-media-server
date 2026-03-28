$ErrorActionPreference = 'Stop'

$TaskName = 'Harbor Media Stack Config Backup'
$RunBackupCmd = Join-Path $PSScriptRoot 'run-backup.cmd'

if (-not (Test-Path -LiteralPath $RunBackupCmd)) {
    throw "Backup runner not found: $RunBackupCmd"
}

$Action = New-ScheduledTaskAction -Execute $RunBackupCmd
$Triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 5:00PM),
    (New-ScheduledTaskTrigger -Daily -At 1:00AM),
    (New-ScheduledTaskTrigger -Daily -At 9:00AM)
)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Description 'Creates Harbor Media Server config backups three times per day.'

Write-Output "Registered scheduled task: $TaskName"
