[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$LogRoot = 'D:\harbor-media-server\synology-sync-logs\targeted-fresh'
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    $line | Tee-Object -FilePath (Join-Path $LogRoot 'targeted-fresh.log') -Append | Out-Null
}

function Get-TopLevelFolders {
    param([object]$ParityRow)

    $folders = @()
    $folders += @($ParityRow.Missing) | ForEach-Object {
        if ($_ -is [string] -and $_) {
            ($_ -split '[\\/]')[0]
        }
    }
    $folders += @($ParityRow.Mismatch) | ForEach-Object {
        if ($_.RelativePath) {
            ($_.RelativePath -split '[\\/]')[0]
        }
    }

    $folders | Where-Object { $_ } | Sort-Object -Unique
}

function Test-FolderParity {
    param(
        [string]$SourcePath,
        [string]$DestPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath) -or -not (Test-Path -LiteralPath $DestPath)) {
        return $false
    }

    $sourceFiles = Get-ChildItem -LiteralPath $SourcePath -Recurse -File | ForEach-Object {
        [pscustomobject]@{
            RelativePath = $_.FullName.Substring($SourcePath.Length).TrimStart('\')
            Length = $_.Length
        }
    }

    $destFiles = Get-ChildItem -LiteralPath $DestPath -Recurse -File | ForEach-Object {
        [pscustomobject]@{
            RelativePath = $_.FullName.Substring($DestPath.Length).TrimStart('\')
            Length = $_.Length
        }
    }

    if ($sourceFiles.Count -ne $destFiles.Count) {
        return $false
    }

    $sourceMap = @{}
    foreach ($file in $sourceFiles) {
        $sourceMap[$file.RelativePath] = [int64]$file.Length
    }

    foreach ($file in $destFiles) {
        if (-not $sourceMap.ContainsKey($file.RelativePath)) {
            return $false
        }

        if ($sourceMap[$file.RelativePath] -ne [int64]$file.Length) {
            return $false
        }
    }

    return $true
}

function Invoke-FreshMirror {
    param(
        [string]$BucketName,
        [string]$SourceRoot,
        [string]$DestRoot,
        [string[]]$Folders
    )

    if (-not $Folders.Count) {
        Write-Log ("No {0} folders require fresh copy." -f $BucketName)
        return
    }

    $index = 0
    foreach ($folder in $Folders) {
        try {
            $index++
            $src = Join-Path $SourceRoot $folder
            $dst = Join-Path $DestRoot $folder
            $safe = ($folder -replace '[\\/:*?"<>|]', '_')
            $logPath = Join-Path $LogRoot ("{0}-{1}.log" -f $BucketName, $safe)

            if (-not (Test-Path -LiteralPath $src)) {
                Write-Log ("Skipping missing source folder: {0}" -f $src)
                continue
            }

            $verified = $false
            for ($attempt = 1; $attempt -le 2 -and -not $verified; $attempt++) {
                if (Test-Path -LiteralPath $dst) {
                    Write-Log ("[{0}/{1}] Removing stale destination folder: {2}" -f $index, $Folders.Count, $dst)
                    Remove-Item -LiteralPath $dst -Recurse -Force
                }

                Write-Log ("[{0}/{1}] Fresh copying {2}: {3} (attempt {4}/2)" -f $index, $Folders.Count, $BucketName, $folder, $attempt)
                & robocopy.exe $src $dst /MIR /J /FFT /R:3 /W:5 /MT:1 /COPY:DAT /DCOPY:DAT /NP "/LOG:$logPath"
                $exitCode = $LASTEXITCODE
                if ($exitCode -gt 7) {
                    throw ("robocopy failed for {0} -> {1} with exit code {2}" -f $src, $dst, $exitCode)
                }

                $verified = Test-FolderParity -SourcePath $src -DestPath $dst
                if (-not $verified) {
                    Write-Log ("[{0}/{1}] Folder parity mismatch remains for {2} after attempt {3}" -f $index, $Folders.Count, $folder, $attempt)
                }
            }

            if (-not $verified) {
                throw ("post-copy parity failed for {0}" -f $folder)
            }

            Write-Log ("[{0}/{1}] Fresh copy completed and verified for {2}" -f $index, $Folders.Count, $folder)
        }
        catch {
            Write-Log ("[{0}/{1}] Fresh copy failed for {2}: {3}" -f $index, $Folders.Count, $folder, $_.Exception.Message)
        }
    }
}

$manifestRoot = Join-Path $LogRoot 'parity'
$report = & (Join-Path $PSScriptRoot 'Test-SynologyLibraryParity.ps1') -NasHost $NasHost -IncludeDownloads -ManifestRoot $manifestRoot
$movieRow = $report | Where-Object Name -eq 'movies'
$downloadRow = $report | Where-Object Name -eq 'downloads'

$movieFolders = @(Get-TopLevelFolders -ParityRow $movieRow)
$downloadFolders = @(Get-TopLevelFolders -ParityRow $downloadRow)

Write-Log ("Targeted movie folders: {0}" -f $movieFolders.Count)
Write-Log ("Targeted download folders: {0}" -f $downloadFolders.Count)

Invoke-FreshMirror -BucketName 'movies' -SourceRoot 'D:\NAS\media\movies' -DestRoot "\\$NasHost\media\movies" -Folders $movieFolders
Invoke-FreshMirror -BucketName 'downloads' -SourceRoot 'D:\NAS\downloads' -DestRoot "\\$NasHost\downloads" -Folders $downloadFolders

Write-Log 'Targeted fresh copy completed.'

