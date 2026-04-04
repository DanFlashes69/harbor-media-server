#Requires -Version 5.1
<#
  Harbor Media Server setup helper.
  This script assumes the repository root is the Docker Compose project root.
#>

param(
    [switch]$SkipPreflightChecks = $false,
    [switch]$SkipPortScan = $false,
    [switch]$NoLaunch = $false,
    [switch]$NoBootstrap = $false,
    [switch]$NoUpdateTask = $false
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
    8082  = 'SABnzbd WebUI'
    8191  = 'FlareSolverr'
    8265  = 'Tdarr WebUI'
    8266  = 'Tdarr server'
    8686  = 'Lidarr'
    8989  = 'Sonarr'
    9000  = 'Portainer'
    8099  = 'Update status page'
    9696  = 'Prowlarr'
    32400 = 'Plex'
}

$DockerDirectories = @(
    'gluetun',
    'indexer-guardian',
    'qbittorrent\config',
    'sabnzbd\config',
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
    'update-guardian\status',
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
    'downloads\usenet\incomplete',
    'downloads\usenet\complete',
    'downloads\.arr-recycle\radarr',
    'downloads\.arr-recycle\sonarr',
    'media\movies',
    'media\tv',
    'media\music',
    'photos',
    'quarantine'
)

$NamedDockerVolumes = @(
    'radarr_config',
    'sonarr_config',
    'lidarr_config',
    'bazarr_config',
    'prowlarr_config'
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

function Write-UpdateStatusPlaceholder {
    param(
        [string]$DockerRoot
    )

    $statusRoot = Join-Path $DockerRoot 'update-guardian\status'
    $indexPath = Join-Path $statusRoot 'index.html'
    $jsonPath = Join-Path $statusRoot 'status.json'

    New-Item -ItemType Directory -Force -Path $statusRoot | Out-Null

    if (-not (Test-Path $indexPath)) {
        $html = @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Harbor Update Status</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { background:#0f172a; color:#e5e7eb; font-family:Segoe UI, Arial, sans-serif; margin:0; padding:32px; }
    .card { max-width:840px; margin:0 auto; background:#111827; border:1px solid #1f2937; border-radius:16px; padding:24px; }
    h1 { margin-top:0; color:#f8fafc; }
    p { line-height:1.6; }
    code { color:#93c5fd; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Harbor Update Status</h1>
    <p>No update scan has been run yet.</p>
    <p>Run <code>scripts\safe-update-media-stack.ps1</code> or install the scheduled task to generate the live update report.</p>
  </div>
</body>
</html>
"@
        Set-Content -Path $indexPath -Value $html -Encoding UTF8
    }

    if (-not (Test-Path $jsonPath)) {
        $payload = @{
            generatedAt = (Get-Date).ToString('o')
            status = 'not-run'
            summary = 'No safe update scan has been run yet.'
            updated = @()
            deferred = @()
            blocked = @()
            manual = @()
            appWarnings = @()
        } | ConvertTo-Json -Depth 6
        Set-Content -Path $jsonPath -Value $payload -Encoding UTF8
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

function Ensure-NamedVolumes {
    Write-Section 'Ensuring named Docker volumes'

    foreach ($volume in $NamedDockerVolumes) {
        try {
            docker volume inspect $volume | Out-Null
            Write-Info "Docker volume already exists: $volume"
        } catch {
            docker volume create $volume | Out-Null
            Write-Good "Created Docker volume: $volume"
        }
    }
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
SERVER_HOST=$($Values.ServerHost)
TIMEZONE=$($Values.Timezone)
VPN_USERNAME=$($Values.VpnUsername)
VPN_PASSWORD=$($Values.VpnPassword)
QBIT_USER=$($Values.QbitUser)
QBIT_PASS=$($Values.QbitPass)
PIHOLE_PASSWORD=$($Values.PiholePassword)
IMMICH_DB_PASSWORD=$($Values.ImmichDbPassword)
PLEX_ADVERTISE_IP=$($Values.PlexAdvertiseIp)
CLOUDFLARE_TUNNEL_TOKEN=
SAB_SERVER_NAME=PrimaryUsenet
SAB_SERVER_HOST=
SAB_SERVER_PORT=563
SAB_SERVER_USERNAME=
SAB_SERVER_PASSWORD=
SAB_SERVER_SSL=true
SAB_SERVER_CONNECTIONS=20
PROWLARR_NEWZNAB_NAME=Primary Newznab
PROWLARR_NEWZNAB_URL=
PROWLARR_NEWZNAB_API_KEY=
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
    Write-Host "SERVER_HOST:      $($Values.ServerHost)"
    Write-Host ''
    Write-Host 'Important next steps:' -ForegroundColor Cyan
    Write-Host '  1. Put your OpenVPN config at DOCKER_ROOT\gluetun\custom.ovpn'
    Write-Host '  2. Start the stack from the repository root with docker compose up -d --build'
    Write-Host '  3. Run scripts\bootstrap-media-stack.ps1 to wire qBittorrent, SABnzbd, Prowlarr, the Arr apps, Recyclarr, and Homepage'
    Write-Host '  4. Run scripts\safe-update-media-stack.ps1 -Preview or install the scheduled safe-update task'
    Write-Host '  5. Finish the remaining UI-only setup steps in Plex, Overseerr, Cloudflare, and any private indexers or Usenet providers'
    Write-Host '  6. Review docs\SETUP.md for the full setup flow, docs\SERVICE-SETUP.md for the service reference, and docs\AI-SETUP.md if you want an autonomous agent to finish the rest'
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
    Write-Host '  - Optional server hostname or LAN IP for generated Homepage links'
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
$dataRoot = Read-Default 'DATA_ROOT' 'D:\media'
$serverHost = Read-Default 'Server host for generated Homepage links' 'localhost'
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
    ServerHost      = $(if ([string]::IsNullOrWhiteSpace($serverHost)) { 'localhost' } else { $serverHost })
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
Ensure-NamedVolumes
Seed-Templates -DockerRoot $values.DockerRoot
Write-UpdateStatusPlaceholder -DockerRoot $values.DockerRoot
Write-EnvFile -Values $values
Test-VpnFile -DockerRoot $values.DockerRoot | Out-Null
Test-NativeQbittorrent
Show-Summary -Values $values

if (-not $NoUpdateTask -and (Confirm-Step 'Install the daily Harbor safe update task now')) {
    & (Join-Path $RepoRoot 'scripts\install-update-task.ps1')
    Write-Good 'Installed the Harbor safe update scheduled task.'
}

if (-not $NoLaunch -and (Confirm-Step 'Start Docker Compose now')) {
    Start-Stack

    if (-not $NoBootstrap -and (Confirm-Step 'Run the post-launch bootstrap now')) {
        & (Join-Path $RepoRoot 'scripts\bootstrap-media-stack.ps1')
    }

    if (-not $NoUpdateTask -and (Confirm-Step 'Run a safe-update preview now to seed the status page')) {
        & (Join-Path $RepoRoot 'scripts\safe-update-media-stack.ps1') -Preview
    }
}

Write-Good 'Setup complete.'
