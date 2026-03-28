$ErrorActionPreference = 'Stop'

function Get-EnvMap {
    param([string]$Path)

    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $map
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith('#')) { continue }
        if ($line -notmatch '^[A-Za-z_][A-Za-z0-9_]*=') { continue }

        $parts = $line -split '=', 2
        $map[$parts[0]] = $parts[1]
    }

    return $map
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $RepoRoot '.env'
$EnvMap = Get-EnvMap -Path $EnvPath
$DockerRoot = $EnvMap['DOCKER_ROOT']

if ([string]::IsNullOrWhiteSpace($DockerRoot)) {
    throw "DOCKER_ROOT was not found in $EnvPath"
}

$BackupRoot = Join-Path $RepoRoot 'backups'
$Timestamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$StagingRoot = Join-Path $BackupRoot ("staging_" + $Timestamp)
$ArchivePath = Join-Path $BackupRoot ("media-stack-config_" + $Timestamp + ".zip")
$ExcludedDirectoryNames = @('.cache', 'cache', 'logs', 'Logs', 'MediaCover', 'Sentry', 'Cache')
$AllowedExtensions = @('.db', '.xml', '.json', '.yml', '.yaml', '.conf', '.cfg', '.sqlite', '.txt')

$Items = @(
  @{ Source = (Join-Path $RepoRoot 'docker-compose.yml'); Target = 'compose\docker-compose.yml'; Optional = $false },
  @{ Source = (Join-Path $RepoRoot '.env'); Target = 'compose\.env'; Optional = $true },
  @{ Source = (Join-Path $DockerRoot 'radarr\config'); Target = 'apps\radarr\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'sonarr\config'); Target = 'apps\sonarr\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'lidarr\config'); Target = 'apps\lidarr\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'bazarr\config'); Target = 'apps\bazarr\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'prowlarr\config'); Target = 'apps\prowlarr\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'overseerr\config'); Target = 'apps\overseerr\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'qbittorrent\config\qBittorrent\qBittorrent.conf'); Target = 'apps\qbittorrent\qBittorrent.conf'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'homepage\config'); Target = 'apps\homepage\config'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'pihole\etc-pihole'); Target = 'apps\pihole\etc-pihole'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'pihole\etc-dnsmasq.d'); Target = 'apps\pihole\etc-dnsmasq.d'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'tdarr\configs'); Target = 'apps\tdarr\configs'; Optional = $false },
  @{ Source = (Join-Path $DockerRoot 'plex\config\Library\Application Support\Plex Media Server\Preferences.xml'); Target = 'apps\plex\Preferences.xml'; Optional = $false }
)

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

Get-ChildItem -LiteralPath $BackupRoot -Directory -Filter 'staging_*' -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
  }
  catch {
    Write-Warning ("Could not remove stale staging folder: " + $_.FullName)
  }
}

New-Item -ItemType Directory -Path $StagingRoot -Force | Out-Null

foreach ($Item in $Items) {
  if (-not (Test-Path -LiteralPath $Item.Source)) {
    if (-not $Item.Optional) {
      Write-Warning ("Missing backup source: " + $Item.Source)
    }
    continue
  }

  $Destination = Join-Path $StagingRoot $Item.Target
  $DestinationParent = Split-Path -Parent $Destination
  New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null

  $SourceItem = Get-Item -LiteralPath $Item.Source
  if ($SourceItem.PSIsContainer) {
    $SourceRoot = (Resolve-Path -LiteralPath $Item.Source).Path.TrimEnd('\')
    $Files = Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force | Where-Object {
      $PathParts = $_.DirectoryName -split '\\'
      $HasExcludedDirectory = ($PathParts | Where-Object { $ExcludedDirectoryNames -contains $_ }).Count -gt 0
      $Extension = $_.Extension.ToLowerInvariant()
      $AllowedName = $_.Name -match '\.(db|sqlite)-(shm|wal)$'
      (-not $HasExcludedDirectory) -and ($AllowedExtensions -contains $Extension -or $AllowedName)
    }

    foreach ($File in $Files) {
      $RelativePath = $File.FullName.Substring($SourceRoot.Length).TrimStart('\')
      $FileDestination = Join-Path $Destination $RelativePath
      $FileDestinationParent = Split-Path -Parent $FileDestination
      New-Item -ItemType Directory -Path $FileDestinationParent -Force | Out-Null
      Copy-Item -LiteralPath $File.FullName -Destination $FileDestination -Force
    }
  }
  else {
    Copy-Item -LiteralPath $Item.Source -Destination $Destination -Force
  }
}

if (Test-Path -LiteralPath $ArchivePath) {
  Remove-Item -LiteralPath $ArchivePath -Force
}

Compress-Archive -Path (Join-Path $StagingRoot '*') -DestinationPath $ArchivePath -CompressionLevel Optimal

$OldBackups = Get-ChildItem -LiteralPath $BackupRoot -Filter 'media-stack-config_*.zip' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 14

foreach ($OldBackup in $OldBackups) {
  Remove-Item -LiteralPath $OldBackup.FullName -Force
}

Write-Output ("Created backup: " + $ArchivePath)
