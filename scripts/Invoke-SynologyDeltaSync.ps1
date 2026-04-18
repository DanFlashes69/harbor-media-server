[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$NasUser = 'harboradmin',
    [string]$NasPassword = 'change_me',
    [switch]$Mirror
)

$ErrorActionPreference = 'Stop'

$logRoot = Join-Path $PSScriptRoot '..\synology-sync-logs'
$logRoot = [System.IO.Path]::GetFullPath($logRoot)
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$shareRoots = @('docker', 'media', 'downloads', 'photos', 'quarantine', 'backups')
foreach ($share in $shareRoots) {
    cmd /c "net use \\$NasHost\$share /user:$NasUser $NasPassword" | Out-Null
}

$sources = @(
    @{ name = 'media-movies'; src = 'D:\NAS\media\movies'; dst = "\\$NasHost\media\movies" },
    @{ name = 'media-tv'; src = 'D:\NAS\media\tv'; dst = "\\$NasHost\media\tv" },
    @{ name = 'media-music'; src = 'D:\NAS\media\music'; dst = "\\$NasHost\media\music" },
    @{ name = 'media-photos'; src = 'D:\NAS\media\photos'; dst = "\\$NasHost\media\photos" },
    @{ name = 'downloads'; src = 'D:\NAS\downloads'; dst = "\\$NasHost\downloads" },
    @{ name = 'photos'; src = 'D:\NAS\photos'; dst = "\\$NasHost\photos" },
    @{ name = 'quarantine'; src = 'D:\NAS\quarantine'; dst = "\\$NasHost\quarantine" }
)

$modeArg = if ($Mirror) { '/MIR' } else { '/E' }
$started = @()

foreach ($job in $sources) {
    if (-not (Test-Path $job.src)) {
        continue
    }

    $isMovieLane = $job.name -eq 'media-movies'
    $isLargeMutableLane = $job.name -in @('media-movies', 'downloads')
    $transferMode = if ($isLargeMutableLane) { '/Z' } else { '/J' }
    $retryCount = if ($isLargeMutableLane) { '/R:5' } else { '/R:0' }
    $retryWait = if ($isLargeMutableLane) { '/W:10' } else { '/W:0' }
    $threadCount = if ($isMovieLane) { '/MT:1' } elseif ($job.name -eq 'downloads') { '/MT:4' } else { '/MT:32' }

    $log = Join-Path $logRoot ("delta-{0}.log" -f $job.name)
    $args = @(
        $job.src,
        $job.dst,
        $modeArg,
        $transferMode,
        '/FFT',
        $retryCount,
        $retryWait,
        $threadCount,
        '/COPY:DAT',
        '/DCOPY:DAT',
        '/NP',
        "/LOG:$log"
    ) | Where-Object { $_ }

    $proc = Start-Process -FilePath 'robocopy.exe' -ArgumentList $args -PassThru -WindowStyle Hidden
    $started += [pscustomobject]@{
        job = $job.name
        pid = $proc.Id
        log = $log
        mode = if ($Mirror) { 'mirror' } else { 'sync' }
    }
}

$started

