#Requires -Version 5.1

param(
    [string]$DestinationRoot = "$env:USERPROFILE\Desktop\Harbor-Synology-Migration",
    [switch]$IncludeRuntimeConfigs
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$EnvPath = Join-Path $RepoRoot '.env'
$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BundleRoot = Join-Path $DestinationRoot $Timestamp
$ManifestRoot = Join-Path $BundleRoot 'manifests'
$ConfigRoot = Join-Path $BundleRoot 'runtime-config'

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Import-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw ".env not found at $Path"
    }

    $values = @{}
    foreach ($line in Get-Content $Path) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith('#')) { continue }
        $pair = $line -split '=', 2
        if ($pair.Count -ne 2) { continue }
        $values[$pair[0].Trim()] = $pair[1].Trim()
    }

    return $values
}

function Ensure-Directory {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Copy-IfPresent {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        return
    }

    Ensure-Directory -Path (Split-Path -Parent $Destination)

    if ((Get-Item -LiteralPath $Source).PSIsContainer) {
        Ensure-Directory -Path $Destination

        foreach ($item in Get-ChildItem -LiteralPath $Source -Force -ErrorAction SilentlyContinue) {
            try {
                Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Destination $item.Name) -Recurse -Force -ErrorAction Stop
            } catch {
                Write-Warning "Skipped problematic path during export: $($item.FullName)"
            }
        }

        return
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

$envValues = Import-EnvFile -Path $EnvPath
$dockerRoot = $envValues['DOCKER_ROOT']
$dataRoot = $envValues['DATA_ROOT']

Ensure-Directory -Path $BundleRoot
Ensure-Directory -Path $ManifestRoot

Write-Info "Writing migration bundle to $BundleRoot"

Copy-Item -Path (Join-Path $RepoRoot 'docker-compose.yml') -Destination (Join-Path $BundleRoot 'docker-compose.yml') -Force
Copy-Item -Path (Join-Path $RepoRoot '.env.example') -Destination (Join-Path $BundleRoot '.env.example') -Force
Copy-Item -Path (Join-Path $RepoRoot 'README.md') -Destination (Join-Path $BundleRoot 'README.md') -Force
Copy-Item -Path (Join-Path $RepoRoot 'docs\SYNOLOGY-MIGRATION.md') -Destination (Join-Path $BundleRoot 'SYNOLOGY-MIGRATION.md') -Force

docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" | Set-Content -Path (Join-Path $ManifestRoot 'docker-ps.txt')
docker volume ls | Set-Content -Path (Join-Path $ManifestRoot 'docker-volumes.txt')
docker network ls | Set-Content -Path (Join-Path $ManifestRoot 'docker-networks.txt')

Get-Content (Join-Path $RepoRoot 'docker-compose.yml') |
    Select-String -Pattern '^  [a-zA-Z0-9_-]+:$' |
    ForEach-Object { $_.Line.Trim() } |
    Set-Content -Path (Join-Path $ManifestRoot 'compose-services.txt')

$pathMap = [pscustomobject]@{
    Current = [pscustomobject]@{
        RepoRoot = $RepoRoot
        DockerRoot = $dockerRoot
        DataRoot = $dataRoot
    }
    RecommendedSynology = [pscustomobject]@{
        DockerRoot = '/volume1/docker/harbor'
        MediaRoot = '/volume1/media'
        Movies = '/volume1/media/movies'
        Tv = '/volume1/media/tv'
        Music = '/volume1/media/music'
        Photos = '/volume1/photos'
        Downloads = '/volume1/downloads'
        Quarantine = '/volume1/quarantine'
        Backups = '/volume1/backups'
    }
} | ConvertTo-Json -Depth 8

$pathMap | Set-Content -Path (Join-Path $ManifestRoot 'path-map.json')

@"
Harbor Synology migration bundle
Generated: $(Get-Date -Format s)

This bundle contains:
- docker-compose snapshot
- .env example
- current running container inventory
- current Docker volume and network inventory
- current Harbor service inventory
- current-to-Synology path map

Current Windows roots:
- RepoRoot: $RepoRoot
- DockerRoot: $dockerRoot
- DataRoot: $dataRoot

Recommended Synology roots:
- /volume1/docker/harbor
- /volume1/media
- /volume1/photos
- /volume1/downloads
- /volume1/quarantine
- /volume1/backups
"@ | Set-Content -Path (Join-Path $BundleRoot 'README.txt')

if ($IncludeRuntimeConfigs) {
    Ensure-Directory -Path $ConfigRoot

    $runtimeCopies = @(
        @{ Source = Join-Path $dockerRoot 'homepage\config'; Destination = Join-Path $ConfigRoot 'homepage\config' },
        @{ Source = Join-Path $dockerRoot 'recyclarr\config'; Destination = Join-Path $ConfigRoot 'recyclarr\config' },
        @{ Source = Join-Path $dockerRoot 'qbittorrent\config'; Destination = Join-Path $ConfigRoot 'qbittorrent\config' },
        @{ Source = Join-Path $dockerRoot 'sabnzbd\config'; Destination = Join-Path $ConfigRoot 'sabnzbd\config' },
        @{ Source = Join-Path $dockerRoot 'pihole\etc-pihole'; Destination = Join-Path $ConfigRoot 'pihole\etc-pihole' },
        @{ Source = Join-Path $dockerRoot 'pihole\etc-dnsmasq.d'; Destination = Join-Path $ConfigRoot 'pihole\etc-dnsmasq.d' },
        @{ Source = Join-Path $dockerRoot 'overseerr\config'; Destination = Join-Path $ConfigRoot 'overseerr\config' },
        @{ Source = Join-Path $dockerRoot 'tdarr\configs'; Destination = Join-Path $ConfigRoot 'tdarr\configs' },
        @{ Source = Join-Path $dockerRoot 'gluetun'; Destination = Join-Path $ConfigRoot 'gluetun' }
    )

    foreach ($item in $runtimeCopies) {
        Copy-IfPresent -Source $item.Source -Destination $item.Destination
    }

    Write-Info 'Included selected runtime configuration directories.'
}

Write-Host ""
Write-Host "Migration bundle created:" -ForegroundColor Green
Write-Host $BundleRoot -ForegroundColor Green
