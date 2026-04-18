$ErrorActionPreference = 'Stop'

$TaskName = 'Harbor Media Stack Config Backup'
$BackupScript = Join-Path $PSScriptRoot 'backup-media-stack.ps1'

if (-not (Test-Path -LiteralPath $BackupScript)) {
    throw "Backup script not found: $BackupScript"
}

$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$BackupScript`""
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
