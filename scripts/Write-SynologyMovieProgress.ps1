[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$LogRoot = 'D:\harbor-media-server\synology-sync-logs'
)

$ErrorActionPreference = 'Stop'

$jsonPath = Join-Path $LogRoot 'movie-progress.json'
$logPath = Join-Path $LogRoot 'movie-progress.log'
$targetedLogPath = Join-Path $LogRoot 'targeted-fresh\targeted-fresh.log'

function Get-DirectoryStats {
    param([string]$Path)

    $items = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue
    [pscustomobject]@{
        FileCount = @($items).Count
        TotalBytes = [int64](($items | Measure-Object -Property Length -Sum).Sum)
    }
}

function Get-CurrentCopyFolder {
    $proc = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -ieq 'robocopy.exe' -and
            $_.CommandLine -match '\\\\192\.168\.1\.29\\media\\movies'
        } |
        Select-Object -First 1

    if (-not $proc) {
        return $null
    }

    if ($proc.CommandLine -match '"D:\\NAS\\media\\movies\\(.+?)"\s+"\\\\192\.168\.1\.29\\media\\movies') {
        return $Matches[1]
    }

    return $proc.CommandLine
}

function Get-TargetedProgress {
    if (-not (Test-Path -LiteralPath $targetedLogPath)) {
        return $null
    }

    $lines = Get-Content -LiteralPath $targetedLogPath -Tail 50
    $matchLine = $lines | Select-String -Pattern '\[(\d+)/(\d+)\].*Fresh copying movies:\s+(.*)$' | Select-Object -Last 1
    if (-not $matchLine) {
        return $null
    }

    $m = [regex]::Match($matchLine.Line, '\[(\d+)/(\d+)\].*Fresh copying movies:\s+(.*)$')
    if (-not $m.Success) {
        return $null
    }

    [pscustomobject]@{
        Current = [int]$m.Groups[1].Value
        Total = [int]$m.Groups[2].Value
        Folder = $m.Groups[3].Value.Trim()
    }
}

$srcStats = Get-DirectoryStats -Path 'D:\NAS\media\movies'
$dstStats = Get-DirectoryStats -Path "\\$NasHost\media\movies"
$targeted = Get-TargetedProgress
$parity = & (Join-Path $PSScriptRoot 'Test-SynologyLibraryParity.ps1') -NasHost $NasHost -IncludeDownloads
$movieRow = $parity | Where-Object Name -eq 'movies'

$percent = if ($srcStats.TotalBytes -gt 0) {
    [math]::Round(($dstStats.TotalBytes / $srcStats.TotalBytes) * 100, 2)
} else {
    100
}

$snapshot = [pscustomobject]@{
    Timestamp = (Get-Date).ToString('o')
    SourceBytes = $srcStats.TotalBytes
    DestBytes = $dstStats.TotalBytes
    PercentBytes = $percent
    SourceFiles = $srcStats.FileCount
    DestFiles = $dstStats.FileCount
    MissingCount = $movieRow.MissingCount
    MismatchCount = $movieRow.MismatchCount
    ExtraCount = $movieRow.ExtraCount
    ActiveCopyFolder = Get-CurrentCopyFolder
    TargetedCurrent = if ($targeted) { $targeted.Current } else { $null }
    TargetedTotal = if ($targeted) { $targeted.Total } else { $null }
    TargetedFolder = if ($targeted) { $targeted.Folder } else { $null }
}

$snapshot | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jsonPath -Encoding utf8

$summary = "{0} movies={1}% bytes={2}/{3} files={4}/{5} missing={6} mismatch={7} active='{8}' targeted={9}/{10} '{11}'" -f `
    (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),
    $snapshot.PercentBytes,
    $snapshot.DestBytes,
    $snapshot.SourceBytes,
    $snapshot.DestFiles,
    $snapshot.SourceFiles,
    $snapshot.MissingCount,
    $snapshot.MismatchCount,
    $snapshot.ActiveCopyFolder,
    $snapshot.TargetedCurrent,
    $snapshot.TargetedTotal,
    $snapshot.TargetedFolder

$summary | Tee-Object -FilePath $logPath -Append | Out-Null

