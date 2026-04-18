$ErrorActionPreference = 'Stop'

$TaskName = 'Harbor Media Stack Safe Update'
$UpdateScript = Join-Path $PSScriptRoot 'safe-update-media-stack.ps1'

if (-not (Test-Path -LiteralPath $UpdateScript)) {
    throw "Update script not found: $UpdateScript"
}

$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$UpdateScript`""
$Triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 4:30AM)
)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Description 'Runs Harbor Media Server safe update orchestration once per day.'

Write-Output "Registered scheduled task: $TaskName"
