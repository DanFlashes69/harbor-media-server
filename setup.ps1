#Requires -Version 5.1
<#
  Harbor Media Server setup helper.
  This script assumes the repository root is the Docker Compose project root.
#>

param(
    [switch]$SkipPreflightChecks = $false,
    [switch]$SkipPortScan = $false,
    [switch]$NoLaunch = $false
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$RepoRoot = Split-Path -Parent $PSCommandPath
$EnvPath = Join-Path $RepoRoot '.env'

$RequiredPorts = [ordered]@{
    53    = 'Pi-hole DNS'
    2283  = 'Immich'
    3000  = 'Homepage'
    5055  = 'Overseerr'
    6767  = 'Bazarr'
    6881  = 'qBittorrent peer port'
    7878  = 'Radarr'
    8080  = 'Pi-hole HTTP'
    8081  = 'qBittorrent WebUI'
    8191  = 'FlareSolverr'
    8265  = 'Tdarr WebUI'
    8266  = 'Tdarr server'
    8686  = 'Lidarr'
    8989  = 'Sonarr'
    9000  = 'Portainer'
    9696  = 'Prowlarr'
    32400 = 'Plex'
}

$DockerDirectories = @(
    'gluetun',
    'qbittorrent\config',
    'radarr\config',
    'sonarr\config',
    'lidarr\config',
    'bazarr\config',
    'prowlarr\config',
    'plex\config',
    'plex\transcode',
    'overseerr\config',
    'immich\model-cache',
    'immich\postgres',
    'homepage\config',
    'portainer\data',
    'recyclarr\config',
    'pihole\etc-pihole',
    'pihole\etc-dnsmasq.d',
    'scanner\logs',
    'tdarr\server',
    'tdarr\configs',
    'tdarr\logs',
    'tdarr\transcode_cache'
)

$DataDirectories = @(
    'downloads',
    'downloads\incomplete',
    'downloads\.arr-recycle\radarr',
    'downloads\.arr-recycle\sonarr',
    'media\movies',
    'media\tv',
    'media\music',
    'photos',
    'quarantine'
)

function Write-Section {
    param([string]$Title)
    Write-Host "`n== $Title ==" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Gray
}

function Write-Good {
    param([string]$Message)
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Bad {
    param([string]$Message)
    Write-Host "[ERR]  $Message" -ForegroundColor Red
}

function Read-Default {
    param(
        [string]$Prompt,
        [string]$Default
    )

    $value = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }

    return $value.Trim()
}

function Confirm-Step {
    param([string]$Prompt)
    $answer = Read-Host "$Prompt (y/n)"
    return $answer -match '^(y|yes)$'
}

function Test-Prerequisites {
    Write-Section 'Prerequisite checks'

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Bad 'Docker was not found in PATH. Install Docker Desktop first.'
        return $false
    }
    Write-Good "Docker found at $($docker.Source)"

    try {
        docker info | Out-Null
        Write-Good 'Docker daemon is reachable.'
    } catch {
        Write-Bad 'Docker Desktop is not running or is not reachable.'
        return $false
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        Write-Good "Git found at $($git.Source)"
    } else {
        Write-Warn 'Git was not found in PATH. Repo updates will be manual until Git is installed.'
    }

    return $true
}

function Test-PortAvailability {
    param([int]$Port)

    try {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return ($null -eq $listener)
    } catch {
        return $true
    }
}

function Scan-Ports {
    if ($SkipPortScan) {
        Write-Warn 'Port scan skipped.'
        return $true
    }

    Write-Section 'Port scan'
    $conflicts = @()

    foreach ($port in $RequiredPorts.Keys) {
        if (Test-PortAvailability -Port $port) {
            Write-Good "Port $port available for $($RequiredPorts[$port])"
        } else {
            Write-Bad "Port $port is already in use ($($RequiredPorts[$port]))"
            $conflicts += $port
        }
    }

    if ($conflicts.Count -gt 0) {
        return (Confirm-Step 'Continue anyway')
    }

    return $true
}

function Seed-Templates {
    param(
        [string]$DockerRoot
    )

    Write-Section 'Seeding config templates'

    $copyMap = @(
        @{ Source = (Join-Path $RepoRoot 'homepage\config');  Destination = (Join-Path $DockerRoot 'homepage\config') },
        @{ Source = (Join-Path $RepoRoot 'recyclarr\config'); Destination = (Join-Path $DockerRoot 'recyclarr\config') }
    )

    foreach ($item in $copyMap) {
        if (-not (Test-Path $item.Source)) {
            Write-Warn "Template source missing: $($item.Source)"
            continue
        }

        New-Item -ItemType Directory -Force -Path $item.Destination | Out-Null

        Get-ChildItem -Path $item.Source -File | ForEach-Object {
            $target = Join-Path $item.Destination $_.Name
            if (-not (Test-Path $target)) {
                Copy-Item $_.FullName $target
                Write-Good "Copied $($_.Name) to $($item.Destination)"
            } else {
                Write-Info "Kept existing $target"
            }
        }
    }
}

function New-Directories {
    param(
        [string]$DockerRoot,
        [string]$DataRoot
    )

    Write-Section 'Creating directories'

    foreach ($relativePath in $DockerDirectories) {
        New-Item -ItemType Directory -Force -Path (Join-Path $DockerRoot $relativePath) | Out-Null
    }
    Write-Good 'Docker config directories are ready.'

    foreach ($relativePath in $DataDirectories) {
        New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $relativePath) | Out-Null
    }
    Write-Good 'Media, downloads, recycle bins, and quarantine directories are ready.'
}

function Write-EnvFile {
    param(
        [hashtable]$Values
    )

    if ((Test-Path $EnvPath) -and -not (Confirm-Step ".env already exists at $EnvPath. Overwrite it")) {
        Write-Info 'Keeping existing .env file.'
        return
    }

    $content = @"
# Harbor Media Server environment file
# Generated by setup.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

DOCKER_ROOT=$($Values.DockerRoot)
DATA_ROOT=$($Values.DataRoot)
TIMEZONE=$($Values.Timezone)
VPN_USERNAME=$($Values.VpnUsername)
VPN_PASSWORD=$($Values.VpnPassword)
QBIT_USER=$($Values.QbitUser)
QBIT_PASS=$($Values.QbitPass)
PIHOLE_PASSWORD=$($Values.PiholePassword)
IMMICH_DB_PASSWORD=$($Values.ImmichDbPassword)
PLEX_ADVERTISE_IP=$($Values.PlexAdvertiseIp)
RADARR_API_KEY=
SONARR_API_KEY=
LIDARR_API_KEY=
"@

    Set-Content -Path $EnvPath -Value $content -Encoding UTF8
    Write-Good "Wrote .env to $EnvPath"
}

function Test-VpnFile {
    param([string]$DockerRoot)

    Write-Section 'VPN configuration'
    $ovpnPath = Join-Path $DockerRoot 'gluetun\custom.ovpn'
    if (Test-Path $ovpnPath) {
        Write-Good "Found VPN config at $ovpnPath"
        return $true
    }

    Write-Warn "Missing VPN config: $ovpnPath"
    Write-Warn 'Place your provider OpenVPN config there before launching the stack.'
    return (Confirm-Step 'Continue without the VPN file')
}

function Test-NativeQbittorrent {
    Write-Section 'Native qBittorrent check'

    $paths = @(
        'C:\Program Files\qBittorrent\qbittorrent.exe',
        'C:\Program Files (x86)\qBittorrent\qbittorrent.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\qBittorrent\qbittorrent.exe')
    )

    $found = $paths | Where-Object { Test-Path $_ }
    if ($found) {
        Write-Warn 'A native qBittorrent install was detected. If it uses the same ports, stop or uninstall it.'
        $found | ForEach-Object { Write-Info $_ }
    } else {
        Write-Good 'No native qBittorrent install detected.'
    }
}

function Start-Stack {
    Write-Section 'Starting Docker Compose'
    Push-Location $RepoRoot
    try {
        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) {
            throw 'docker compose up failed'
        }
    } finally {
        Pop-Location
    }

    Write-Good 'Docker Compose launch completed.'
}

function Show-Summary {
    param([hashtable]$Values)

    Write-Section 'Summary'
    Write-Host "Repo root:        $RepoRoot"
    Write-Host "Environment file: $EnvPath"
    Write-Host "DOCKER_ROOT:      $($Values.DockerRoot)"
    Write-Host "DATA_ROOT:        $($Values.DataRoot)"
    Write-Host ''
    Write-Host 'Important next steps:' -ForegroundColor Cyan
    Write-Host '  1. Put your OpenVPN config at DOCKER_ROOT\gluetun\custom.ovpn'
    Write-Host '  2. Start the stack from the repository root with docker compose up -d --build'
    Write-Host '  3. Finish first-run app setup in qBittorrent, Plex, Prowlarr, Radarr, Sonarr, Lidarr, and Overseerr'
    Write-Host '  4. Replace placeholder API keys only in local runtime config and .env, never in tracked files'
}

Clear-Host
Write-Host 'Harbor Media Server setup' -ForegroundColor Magenta
Write-Host 'Repository root:' $RepoRoot -ForegroundColor DarkGray

if (-not $SkipPreflightChecks) {
    Write-Section 'Preflight checklist'
    Write-Host 'Have these ready before continuing:'
    Write-Host '  - Docker Desktop'
    Write-Host '  - Git for Windows'
    Write-Host '  - VPN OpenVPN config (.ovpn)'
    Write-Host '  - VPN manual credentials'
    Write-Host '  - Pi-hole password'
    Write-Host '  - Immich DB password'
    Write-Host '  - qBittorrent credentials for the port-updater'
    Write-Host '  - Plex LAN advertise URL such as http://192.168.1.100:32400/'
    if (-not (Confirm-Step 'Continue')) {
        exit 0
    }
}

if (-not (Test-Prerequisites)) {
    exit 1
}

if (-not (Scan-Ports)) {
    exit 1
}

$dockerRoot = Read-Default 'DOCKER_ROOT' 'D:\docker'
$dataRoot = Read-Default 'DATA_ROOT' 'D:\NAS'
$timezone = Read-Default 'Timezone' 'America/Los_Angeles'
$vpnUsername = Read-Default 'VPN username' 'your_vpn_username_here'
$vpnPassword = Read-Default 'VPN password' 'your_vpn_password_here'
$qbitUser = Read-Default 'qBittorrent username for port-updater' 'admin'
$qbitPass = Read-Default 'qBittorrent password for port-updater' 'change_me'
$piholePassword = Read-Default 'Pi-hole password' 'change_me'
$immichDbPassword = Read-Default 'Immich DB password' 'change_me_to_a_strong_password'
$plexAdvertiseIp = Read-Default 'Plex advertise URL' 'http://192.168.1.100:32400/'

$values = @{
    DockerRoot      = $dockerRoot.TrimEnd('\')
    DataRoot        = $dataRoot.TrimEnd('\')
    Timezone        = $timezone
    VpnUsername     = $vpnUsername
    VpnPassword     = $vpnPassword
    QbitUser        = $qbitUser
    QbitPass        = $qbitPass
    PiholePassword  = $piholePassword
    ImmichDbPassword = $immichDbPassword
    PlexAdvertiseIp = $plexAdvertiseIp
}

New-Directories -DockerRoot $values.DockerRoot -DataRoot $values.DataRoot
Seed-Templates -DockerRoot $values.DockerRoot
Write-EnvFile -Values $values
Test-VpnFile -DockerRoot $values.DockerRoot | Out-Null
Test-NativeQbittorrent
Show-Summary -Values $values

if (-not $NoLaunch -and (Confirm-Step 'Start Docker Compose now')) {
    Start-Stack
}

Write-Good 'Setup complete.'
