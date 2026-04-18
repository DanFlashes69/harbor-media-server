[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$NasUser = 'harboradmin',
    [string]$NasPassword = 'change_me',
    [int]$PollSeconds = 60,
    [int]$HealthRetries = 60,
    [int]$RobocopyStaleMinutes = 15
)

$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$logPath = Join-Path $repoRoot 'synology-sync-logs\finalize.log'

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    $line | Tee-Object -FilePath $logPath -Append | Out-Null
}

$otherFinalize = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.Name -match 'powershell' -and
        $_.CommandLine -match 'Invoke-SynologyFinalize\.ps1'
    }

if ($otherFinalize) {
    Write-Log 'Another finalize instance is already running. Exiting.'
    exit 0
}

function Get-ActiveNasRoboCopy {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -ieq 'robocopy.exe' -and
            $_.CommandLine -match '\\\\192\.168\.1\.8\\(media|downloads|photos|quarantine)'
        }
}

function Get-RobocopyLogPath {
    param([string]$CommandLine)

    if ($CommandLine -match '/LOG:([^\s]+)') {
        return $Matches[1]
    }

    return $null
}

function Test-RobocopyStale {
    param(
        [object[]]$Processes,
        [int]$StaleMinutes
    )

    if (-not $Processes.Count) {
        return $false
    }

    $threshold = (Get-Date).AddMinutes(-1 * $StaleMinutes)
    $staleCount = 0

    foreach ($proc in $Processes) {
        $logPath = Get-RobocopyLogPath -CommandLine $proc.CommandLine
        if (-not $logPath) {
            continue
        }

        if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).LastWriteTime -lt $threshold) {
            $staleCount++
        }
    }

    return $staleCount -eq $Processes.Count
}

function Test-LibraryParityComplete {
    $report = & (Join-Path $PSScriptRoot 'Test-SynologyLibraryParity.ps1') -NasHost $NasHost -IncludeDownloads
    $issues = @($report | Where-Object { $_.MissingCount -gt 0 -or $_.MismatchCount -gt 0 })

    foreach ($row in $report) {
        Write-Log ("Parity {0}: src={1} dst={2} missing={3} mismatch={4} extra={5}" -f $row.Name, $row.SourceCount, $row.DestCount, $row.MissingCount, $row.MismatchCount, $row.ExtraCount)
    }

    return ($issues.Count -eq 0)
}

Write-Log 'Finalize watcher started.'

while ($true) {
    $active = @(Get-ActiveNasRoboCopy)
    if ($active.Count) {
        if (Test-RobocopyStale -Processes $active -StaleMinutes $RobocopyStaleMinutes) {
            Write-Log ("Detected {0} stale robocopy job(s). Restarting delta sync." -f $active.Count)
            $active | ForEach-Object {
                try {
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                }
                catch {
                    Write-Log ("Unable to stop stale robocopy process {0}: {1}" -f $_.ProcessId, $_.Exception.Message)
                }
            }

            & (Join-Path $PSScriptRoot 'Invoke-SynologyDeltaSync.ps1') -NasHost $NasHost -NasUser $NasUser -NasPassword $NasPassword | Out-Null
            Start-Sleep -Seconds $PollSeconds
            continue
        }

        Write-Log ("Waiting for {0} active robocopy job(s)." -f $active.Count)
        Start-Sleep -Seconds $PollSeconds
        continue
    }

    Write-Log 'No active robocopy jobs detected. Checking parity before cutover.'
    if (Test-LibraryParityComplete) {
        break
    }

    Write-Log 'Parity not complete yet. Launching targeted fresh copy repair.'
    & (Join-Path $PSScriptRoot 'Invoke-SynologyTargetedFreshCopy.ps1') -NasHost $NasHost | Out-Null
    Start-Sleep -Seconds $PollSeconds
}

Write-Log 'Bulk data sync appears complete. Starting cutover.'
& (Join-Path $PSScriptRoot 'Invoke-SynologyCutover.ps1') -NasHost $NasHost -NasUser $NasUser -NasPassword $NasPassword -MirrorData
Write-Log 'Cutover command completed. Beginning health verification.'

$attempt = 0
do {
    $attempt++
    $health = & (Join-Path $PSScriptRoot 'Test-SynologyStackHealth.ps1') -NasHost $NasHost
    $failed = @($health | Where-Object { -not $_.Ok })

    if (-not $failed.Count) {
        $gauntlet = & (Join-Path $PSScriptRoot 'Test-SynologyHarborGauntlet.ps1') -NasHost $NasHost -NasUser $NasUser -NasPassword $NasPassword
        $gauntletFailures = @($gauntlet | Where-Object { -not $_.Ok })

        if ($gauntletFailures.Count) {
            $gauntletSummary = ($gauntletFailures | ForEach-Object {
                '{0}/{1}({2})' -f $_.Category, $_.Name, $_.Detail
            }) -join ', '

            Write-Log ("Deep gauntlet attempt {0}/{1} still failing: {2}" -f $attempt, $HealthRetries, $gauntletSummary)
            Start-Sleep -Seconds 30
            continue
        }

        try {
            $adapter = Get-NetIPConfiguration |
                Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
                Select-Object -First 1

            if ($adapter -and $adapter.InterfaceAlias) {
                Set-DnsClientServerAddress -InterfaceAlias $adapter.InterfaceAlias -ServerAddresses $NasHost
                Write-Log ("Set local DNS server for {0} to {1}" -f $adapter.InterfaceAlias, $NasHost)
            }
        }
        catch {
            Write-Log ("DNS update skipped: {0}" -f $_.Exception.Message)
        }

        Write-Log 'NAS-only bring-up verified. No PC worker conversion is applied in the all-on-NAS model.'

        Write-Log 'All health checks and deep gauntlet checks passed.'
        exit 0
    }

    $failedSummary = ($failed | ForEach-Object {
        '{0}({1})' -f $_.Name, ($(if ($null -eq $_.StatusCode) { 'no-response' } else { $_.StatusCode }))
    }) -join ', '

    Write-Log ("Health attempt {0}/{1} still failing: {2}" -f $attempt, $HealthRetries, $failedSummary)
    Start-Sleep -Seconds 30
}
while ($attempt -lt $HealthRetries)

Write-Log 'Health verification timed out before all checks passed.'
exit 1

