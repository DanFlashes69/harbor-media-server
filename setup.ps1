#Requires -Version 5.1
<#
================================================================================
  HARBOR MEDIA SERVER — Automated Setup Script

  This script automates the setup of a 23-container Docker Compose media
  server stack on Windows. It handles prerequisites, port conflicts, directory
  creation, configuration generation, and initial launch.

  Usage: .\setup.ps1

  Author: Harbor Media Server Setup
  Version: 1.0.0
  Updated: 2026
================================================================================
#>

param(
    [switch]$SkipPreflightChecks = $false,
    [switch]$SkipPortScan = $false,
    [switch]$AutoLaunch = $false
)

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# All ports used by the Harbor Media Server stack
$REQUIRED_PORTS = @{
    53    = "Pi-hole (DNS)"
    2283  = "Immich"
    3000  = "Homepage"
    5055  = "Overseerr"
    6767  = "Bazarr"
    6881  = "qBittorrent (Peer)"
    7878  = "Radarr"
    8080  = "Pi-hole (Web)"
    8081  = "qBittorrent (WebUI)"
    8191  = "FlareSolverr"
    8265  = "Tdarr (WebUI)"
    8266  = "Tdarr (Server)"
    8686  = "Lidarr"
    8989  = "Sonarr"
    9000  = "Portainer"
    9696  = "Prowlarr"
    32400 = "Plex"
}

# Directory structure that needs to be created
$DOCKER_DIRECTORIES = @(
    "gluetun",
    "qbittorrent\config",
    "radarr\config",
    "sonarr\config",
    "lidarr\config",
    "bazarr\config",
    "prowlarr\config",
    "plex\config",
    "overseerr\config",
    "immich\model-cache",
    "immich\postgres",
    "homepage\config",
    "portainer\data",
    "recyclarr\config",
    "pihole\etc-pihole",
    "pihole\etc-dnsmasq.d",
    "scanner\logs",
    "tdarr\server",
    "tdarr\configs",
    "tdarr\logs",
    "tdarr\transcode_cache"
)

$MEDIA_DIRECTORIES = @(
    "downloads",
    "movies",
    "tv",
    "music",
    "photos"
)

# ============================================================================
# COLOR & OUTPUT FUNCTIONS
# ============================================================================

function Write-Success {
    param([string]$Message)
    Write-Host "? $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "? $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "? $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    Write-Host "? $Message" -ForegroundColor Cyan
}

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 80) -ForegroundColor Magenta
    Write-Host " $Title" -ForegroundColor Magenta
    Write-Host ("=" * 80) -ForegroundColor Magenta
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "? $Title" -ForegroundColor Cyan
    Write-Host ("-" * 80) -ForegroundColor Cyan
}

# ============================================================================
# PROMPT FUNCTIONS
# ============================================================================

function Read-UserInput {
    param(
        [string]$Prompt,
        [string]$Default,
        [scriptblock]$Validation = $null
    )

    do {
        $input = Read-Host "$Prompt (default: $Default)"
        $input = if ([string]::IsNullOrWhiteSpace($input)) { $Default } else { $input }

        if ($null -ne $Validation) {
            $isValid = & $Validation $input
            if (-not $isValid) {
                Write-Warning "Invalid input. Please try again."
                continue
            }
        }
        break
    } while ($true)

    return $input
}

function Confirm-Action {
    param([string]$Message)
    $response = Read-Host "$Message (y/n)"
    return $response -eq 'y' -or $response -eq 'Y'
}

# ============================================================================
# PREFLIGHT CHECKS
# ============================================================================

function Show-PreflightChecklist {
    Write-Header "PRE-FLIGHT CHECKLIST"

    Write-Info "Before running this setup script, ensure you have the following ready:"
    Write-Host ""
    Write-Host "  ? Docker Desktop installed and running on Windows" -ForegroundColor White
    Write-Host "  ? Git for Windows installed (for repository cloning)" -ForegroundColor White
    Write-Host "  ? Windows 10/11 with WSL2 backend for Docker" -ForegroundColor White
    Write-Host "  ? At least 50GB free disk space for containers and media" -ForegroundColor White
    Write-Host "  ? OpenVPN config file (.ovpn) ready from your VPN provider" -ForegroundColor White
    Write-Host "    - For ExpressVPN: https://www.expressvpn.com/setup#manual" -ForegroundColor White
    Write-Host "    - For Mullvad: https://mullvad.net/en/guides/wireguard-and-openvpn/" -ForegroundColor White
    Write-Host "    - For NordVPN: https://nordvpn.com/download/" -ForegroundColor White
    Write-Host "  ? VPN username and password" -ForegroundColor White
    Write-Host "  ? Two free folders on your system:" -ForegroundColor White
    Write-Host "    - One for Docker config (e.g., D:\docker)" -ForegroundColor White
    Write-Host "    - One for media/downloads (e.g., D:\NAS)" -ForegroundColor White
    Write-Host "  ? Timezone identifier (e.g., America/New_York)" -ForegroundColor White
    Write-Host "  ? Desired passwords for Pi-hole and Immich" -ForegroundColor White
    Write-Host ""

    if (-not $SkipPreflightChecks) {
        $proceed = Confirm-Action "Do you have all items ready? Continue with setup?"
        if (-not $proceed) {
            Write-Warning "Setup cancelled. Please prepare the required items and run again."
            exit 0
        }
    }
}

# ============================================================================
# PREREQUISITE CHECKS
# ============================================================================

function Test-Prerequisites {
    Write-Section "Checking Prerequisites"

    $allGood = $true

    # Check Windows version
    Write-Host "Checking Windows version..." -ForegroundColor White
    $osVersion = [System.Environment]::OSVersion
    if ($osVersion.Version.Major -ge 10) {
        Write-Success "Windows 10/11 detected ($($osVersion.Version))"
    } else {
        Write-Error "Windows 10 or later is required"
        $allGood = $false
    }

    # Check if Docker is installed
    Write-Host "Checking for Docker Desktop..." -ForegroundColor White
    $dockerPath = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerPath) {
        Write-Success "Docker found at: $($dockerPath.Source)"
    } else {
        Write-Error "Docker not found. Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
        $allGood = $false
    }

    # Check if Docker daemon is running
    if ($dockerPath) {
        Write-Host "Checking if Docker daemon is running..." -ForegroundColor White
        try {
            $dockerInfo = docker info --format "{{.OSType}}" 2>$null
            if ($dockerInfo) {
                Write-Success "Docker daemon is running"
            } else {
                Write-Error "Docker daemon is not running. Please start Docker Desktop."
                $allGood = $false
            }
        } catch {
            Write-Error "Docker daemon is not running. Please start Docker Desktop."
            $allGood = $false
        }
    }

    # Check if Git is installed
    Write-Host "Checking for Git..." -ForegroundColor White
    $gitPath = Get-Command git -ErrorAction SilentlyContinue
    if ($gitPath) {
        Write-Success "Git found at: $($gitPath.Source)"
    } else {
        Write-Warning "Git not found. It's recommended for cloning repos, but not required."
    }

    return $allGood
}

# ============================================================================
# PORT CONFLICT DETECTION
# ============================================================================

function Test-PortAvailability {
    param([int]$Port)

    try {
        $tcpConnection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return $null -eq $tcpConnection
    } catch {
        return $true
    }
}

function Get-ProcessUsingPort {
    param([int]$Port)

    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        $process = Get-Process -Id $connections.OwningProcess -ErrorAction SilentlyContinue
        if ($process) {
            return @{
                ProcessName = $process.ProcessName
                ProcessId   = $process.Id
                Path        = $process.Path
            }
        }
    } catch {
        # Ignore errors, port might not be in use
    }

    return $null
}

function Scan-PortConflicts {
    if ($SkipPortScan) {
        Write-Info "Port scan skipped (use -SkipPortScan:`$false to scan)"
        return $true
    }

    Write-Section "Scanning for Port Conflicts"

    $conflicts = @()
    $allGood = $true

    Write-Host "Scanning $(($REQUIRED_PORTS.Keys).Count) required ports..." -ForegroundColor White

    foreach ($port in $REQUIRED_PORTS.Keys | Sort-Object) {
        $service = $REQUIRED_PORTS[$port]
        $available = Test-PortAvailability -Port $port

        if (-not $available) {
            $allGood = $false
            $process = Get-ProcessUsingPort -Port $port

            if ($process) {
                Write-Error "Port $port ($service) — IN USE by $($process.ProcessName) [PID: $($process.ProcessId)]"
                $conflicts += @{
                    Port        = $port
                    Service     = $service
                    ProcessName = $process.ProcessName
                    ProcessId   = $process.ProcessId
                }
            } else {
                Write-Error "Port $port ($service) — IN USE (process unknown)"
                $conflicts += @{
                    Port    = $port
                    Service = $service
                }
            }
        } else {
            Write-Success "Port $port ($service) — Available"
        }
    }

    if ($conflicts.Count -gt 0) {
        Write-Host ""
        Write-Warning "Found $($conflicts.Count) port conflicts. To resolve:"
        foreach ($conflict in $conflicts) {
            Write-Host "  • Port $($conflict.Port) ($($conflict.Service)): Stop $($conflict.ProcessName) or change its port"
        }
        Write-Host ""
        $proceed = Confirm-Action "Continue despite port conflicts?"
        return $proceed
    }

    return $allGood
}

# ============================================================================
# PATH CONFIGURATION
# ============================================================================

function Get-UserPaths {
    Write-Section "Configuring Paths"

    Write-Info "You need to provide two paths:"
    Write-Host "  1. DOCKER_ROOT — where Docker config will be stored (use fast drive)" -ForegroundColor White
    Write-Host "  2. DATA_ROOT — where media and downloads will be stored (can be slower drive)" -ForegroundColor White
    Write-Host ""

    $dockerRoot = Read-UserInput -Prompt "Enter DOCKER_ROOT path" -Default "D:\docker" -Validation {
        param($path)
        $path -match '^[A-Z]:\\' -and $path.Length -gt 3
    }

    # Ensure no trailing backslash
    $dockerRoot = $dockerRoot.TrimEnd('\')

    $dataRoot = Read-UserInput -Prompt "Enter DATA_ROOT path" -Default "D:\NAS" -Validation {
        param($path)
        $path -match '^[A-Z]:\\' -and $path.Length -gt 3
    }

    # Ensure no trailing backslash
    $dataRoot = $dataRoot.TrimEnd('\')

    Write-Success "DOCKER_ROOT: $dockerRoot"
    Write-Success "DATA_ROOT: $dataRoot"

    return @{
        DockerRoot = $dockerRoot
        DataRoot   = $dataRoot
    }
}

# ============================================================================
# DIRECTORY CREATION
# ============================================================================

function New-DirectoryStructure {
    param(
        [string]$DockerRoot,
        [string]$DataRoot
    )

    Write-Section "Creating Directory Structure"

    # Create Docker directories
    Write-Host "Creating Docker config directories..." -ForegroundColor White
    $dockerDirsCreated = 0
    $dockerDirsExisted = 0

    foreach ($dir in $DOCKER_DIRECTORIES) {
        $fullPath = Join-Path $DockerRoot $dir
        if (-not (Test-Path -Path $fullPath)) {
            New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
            $dockerDirsCreated++
            Write-Host "  Created: $dir" -ForegroundColor Gray
        } else {
            $dockerDirsExisted++
        }
    }

    if ($dockerDirsCreated -gt 0) {
        Write-Success "Created $dockerDirsCreated Docker directories ($dockerDirsExisted already existed)"
    } else {
        Write-Info "All Docker directories already exist ($dockerDirsExisted)"
    }

    # Create media directories (under DATA_ROOT/media or directly under DATA_ROOT)
    Write-Host "Creating media directories..." -ForegroundColor White
    $mediaDirsCreated = 0
    $mediaDirsExisted = 0

    foreach ($dir in $MEDIA_DIRECTORIES) {
        # Try DATA_ROOT/media/dir first, then DATA_ROOT/dir
        $mediaPath = Join-Path $DataRoot "media" $dir
        if (-not (Test-Path -Path $mediaPath)) {
            $fallbackPath = Join-Path $DataRoot $dir
            if (Test-Path -Path $fallbackPath) {
                # Already exists at fallback location, skip
                Write-Host "  Exists: $dir (at $fallbackPath)" -ForegroundColor Gray
                $mediaDirsExisted++
            } else {
                # Create at media subdirectory
                New-Item -ItemType Directory -Path $mediaPath -Force | Out-Null
                $mediaDirsCreated++
                Write-Host "  Created: media\$dir" -ForegroundColor Gray
            }
        } else {
            Write-Host "  Exists: media\$dir" -ForegroundColor Gray
            $mediaDirsExisted++
        }
    }

    if ($mediaDirsCreated -gt 0) {
        Write-Success "Created $mediaDirsCreated media directories ($mediaDirsExisted already existed)"
    } else {
        Write-Info "All media directories already exist ($mediaDirsExisted)"
    }

    return @{
        DockerDirsCreated = $dockerDirsCreated
        DockerDirsExisted = $dockerDirsExisted
        MediaDirsCreated  = $mediaDirsCreated
        MediaDirsExisted  = $mediaDirsExisted
    }
}

# ============================================================================
# CONFIGURATION FILE HANDLING
# ============================================================================

function Copy-ConfigFiles {
    param(
        [string]$DockerRoot,
        [string]$SourceDir
    )

    Write-Section "Copying Configuration Files"

    $copiedCount = 0
    $skippedCount = 0

    # Copy homepage config files
    Write-Host "Copying homepage config..." -ForegroundColor White
    $homepageSource = Join-Path $SourceDir "homepage" "config"
    $homepageDestDir = Join-Path $DockerRoot "homepage" "config"

    if (Test-Path -Path $homepageSource) {
        if (-not (Test-Path -Path $homepageDestDir)) {
            New-Item -ItemType Directory -Path $homepageDestDir -Force | Out-Null
        }

        Get-ChildItem -Path $homepageSource -File | ForEach-Object {
            $destFile = Join-Path $homepageDestDir $_.Name
            if (-not (Test-Path -Path $destFile)) {
                Copy-Item -Path $_.FullName -Destination $destFile -Force
                $copiedCount++
                Write-Host "  Copied: $($_.Name)" -ForegroundColor Gray
            } else {
                $skippedCount++
                Write-Host "  Skipped: $($_.Name) (already exists)" -ForegroundColor Gray
            }
        }
    } else {
        Write-Warning "Homepage config source not found at: $homepageSource"
    }

    # Copy recyclarr config
    Write-Host "Copying recyclarr config..." -ForegroundColor White
    $recyclarrSource = Join-Path $SourceDir "recyclarr" "config"
    $recyclarrDestDir = Join-Path $DockerRoot "recyclarr" "config"

    if (Test-Path -Path $recyclarrSource) {
        if (-not (Test-Path -Path $recyclarrDestDir)) {
            New-Item -ItemType Directory -Path $recyclarrDestDir -Force | Out-Null
        }

        Get-ChildItem -Path $recyclarrSource -File | ForEach-Object {
            $destFile = Join-Path $recyclarrDestDir $_.Name
            if (-not (Test-Path -Path $destFile)) {
                Copy-Item -Path $_.FullName -Destination $destFile -Force
                $copiedCount++
                Write-Host "  Copied: $($_.Name)" -ForegroundColor Gray
            } else {
                $skippedCount++
                Write-Host "  Skipped: $($_.Name) (already exists)" -ForegroundColor Gray
            }
        }
    } else {
        Write-Warning "Recyclarr config source not found at: $recyclarrSource"
    }

    if ($copiedCount -gt 0) {
        Write-Success "Copied $copiedCount config files ($skippedCount skipped)"
    } else {
        Write-Info "All config files already in place ($skippedCount)"
    }

    return $copiedCount
}

# ============================================================================
# ENVIRONMENT FILE GENERATION
# ============================================================================

function New-EnvironmentFile {
    param(
        [string]$DockerRoot,
        [string]$DataRoot
    )

    Write-Section "Generating .env File"

    $envPath = Join-Path $DockerRoot ".env"

    if (Test-Path -Path $envPath) {
        Write-Warning ".env already exists at: $envPath"
        $overwrite = Confirm-Action "Overwrite existing .env file?"
        if (-not $overwrite) {
            Write-Info "Keeping existing .env file"
            return $envPath
        }
    }

    # Collect environment variables from user
    Write-Host "Enter configuration values. Press Enter to use defaults where shown." -ForegroundColor White
    Write-Host ""

    # Timezone
    $timezone = Read-UserInput -Prompt "Timezone" -Default "America/New_York"

    # VPN Credentials
    Write-Host ""
    Write-Host "VPN Configuration:" -ForegroundColor Cyan
    $vpnUsername = Read-UserInput -Prompt "VPN Username" -Default "your_vpn_username_here"
    $vpnPassword = Read-UserInput -Prompt "VPN Password" -Default "your_vpn_password_here"

    # Pi-hole
    Write-Host ""
    Write-Host "Pi-hole Configuration:" -ForegroundColor Cyan
    $piholePassword = Read-UserInput -Prompt "Pi-hole Admin Password" -Default "changeme"

    # Immich
    Write-Host ""
    Write-Host "Immich Configuration:" -ForegroundColor Cyan
    $immichDbPassword = Read-UserInput -Prompt "Immich Database Password (make it strong)" -Default "change_me_to_a_strong_password"

    # Generate .env content
    $envContent = @"
# ============================================================================
#  HARBOR MEDIA SERVER — Environment Variables
#  Generated by setup.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
# ============================================================================

# --- PATHS ---
# Where Docker config data lives
DOCKER_ROOT=$DockerRoot

# Where your media and downloads live
DATA_ROOT=$DataRoot

# --- TIMEZONE ---
# Find yours: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
TIMEZONE=$timezone

# --- VPN CREDENTIALS ---
# Get from your VPN provider's manual OpenVPN configuration page
# For ExpressVPN: https://www.expressvpn.com/setup#manual
# For Mullvad: https://mullvad.net/en/guides/wireguard-and-openvpn/
# For NordVPN: https://nordvpn.com/download/
VPN_USERNAME=$vpnUsername
VPN_PASSWORD=$vpnPassword

# --- PI-HOLE ---
# Admin password for Pi-hole web interface
PIHOLE_PASSWORD=$piholePassword

# --- IMMICH ---
# Set a strong password for the Immich database (can be anything, just make it secure)
IMMICH_DB_PASSWORD=$immichDbPassword

# --- API KEYS (fill these in AFTER first launch) ---
# You'll get these from each app's Settings > General > API Key after setup
# Do NOT fill these in before first launch - the services won't be running yet
RADARR_API_KEY=
SONARR_API_KEY=
LIDARR_API_KEY=
"@

    # Write .env file
    Set-Content -Path $envPath -Value $envContent -Encoding UTF8
    Write-Success "Created .env file at: $envPath"

    return $envPath
}

# ============================================================================
# DOCKER COMPOSE COPY
# ============================================================================

function Copy-DockerCompose {
    param(
        [string]$DockerRoot,
        [string]$SourceDir
    )

    Write-Section "Copying docker-compose.yml"

    $sourceCompose = Join-Path $SourceDir "docker-compose.yml"
    $destCompose = Join-Path $DockerRoot "docker-compose.yml"

    if (-not (Test-Path -Path $sourceCompose)) {
        Write-Error "docker-compose.yml not found at: $sourceCompose"
        return $false
    }

    Copy-Item -Path $sourceCompose -Destination $destCompose -Force
    Write-Success "Copied docker-compose.yml to: $destCompose"

    return $true
}

# ============================================================================
# VPN CONFIGURATION VALIDATION
# ============================================================================

function Test-VpnConfiguration {
    param([string]$DockerRoot)

    Write-Section "Validating VPN Configuration"

    $gluetunDir = Join-Path $DockerRoot "gluetun"
    $ovpnFile = Join-Path $gluetunDir "custom.ovpn"

    if (-not (Test-Path -Path $ovpnFile)) {
        Write-Warning "OpenVPN config file not found at: $ovpnFile"
        Write-Info "Before starting containers, you must place your VPN provider's .ovpn file here"
        Write-Info "File location: $ovpnFile"
        Write-Info ""
        Write-Info "To obtain the .ovpn file:"
        Write-Info "  • ExpressVPN: https://www.expressvpn.com/setup#manual"
        Write-Info "  • Mullvad: https://mullvad.net/en/guides/wireguard-and-openvpn/"
        Write-Info "  • NordVPN: https://nordvpn.com/download/"
        Write-Info "  • CyberGhost: https://support.cyberghostvpn.com/hc/en-us/articles/..."
        Write-Info ""

        $proceed = Confirm-Action "Continue without VPN config? (containers will fail to start until you add it)"
        return $proceed
    }

    Write-Success "OpenVPN config file found: $ovpnFile"
    return $true
}

# ============================================================================
# QBITTORRENT NATIVE CHECK
# ============================================================================

function Test-QbittorrentNative {
    Write-Section "Checking for Native qBittorrent Installation"

    $qbittorrentPaths = @(
        "C:\Program Files\qBittorrent\qbittorrent.exe",
        "C:\Program Files (x86)\qBittorrent\qbittorrent.exe",
        "$env:LOCALAPPDATA\Programs\qBittorrent\qbittorrent.exe"
    )

    $found = $false
    foreach ($path in $qbittorrentPaths) {
        if (Test-Path -Path $path) {
            Write-Warning "Found native qBittorrent installation at: $path"
            $found = $true
        }
    }

    if ($found) {
        Write-Warning "Having both native qBittorrent and Docker qBittorrent may cause port conflicts"
        Write-Info "Recommendation: Uninstall or disable native qBittorrent before launching containers"
    } else {
        Write-Success "No native qBittorrent installation detected"
    }
}

# ============================================================================
# FIRST LAUNCH
# ============================================================================

function Start-FirstLaunch {
    param(
        [string]$DockerRoot
    )

    Write-Section "Docker Compose Launch Options"

    Write-Info "Recommended first launch order:"
    Write-Host "  1. Start Pi-hole + Gluetun first (15 second wait)" -ForegroundColor White
    Write-Host "  2. Then start remaining services" -ForegroundColor White
    Write-Host ""
    Write-Host "This ensures DNS and VPN are ready before dependent services start" -ForegroundColor White
    Write-Host ""

    $launchNow = Confirm-Action "Start Docker services now?"
    if (-not $launchNow) {
        Write-Info "To start services manually later, run:"
        Write-Host "  cd $DockerRoot" -ForegroundColor Cyan
        Write-Host "  docker compose up -d --build" -ForegroundColor Cyan
        return
    }

    Write-Host ""
    Write-Info "Starting Pi-hole and Gluetun first..."
    Push-Location $DockerRoot
    try {
        # Start just Pi-hole and Gluetun
        docker compose up -d pihole gluetun --build 2>&1 | ForEach-Object {
            Write-Host $_
        }

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Pi-hole and Gluetun started successfully"
            Write-Info "Waiting 15 seconds for services to stabilize..."
            Start-Sleep -Seconds 15

            # Now start the rest
            Write-Info "Starting remaining services..."
            docker compose up -d --build 2>&1 | ForEach-Object {
                Write-Host $_
            }

            if ($LASTEXITCODE -eq 0) {
                Write-Success "All services started successfully"
                Write-Info "Containers are initializing. Check status with: docker compose ps"
            } else {
                Write-Error "Some services failed to start. Check Docker logs."
            }
        } else {
            Write-Error "Failed to start Pi-hole and Gluetun. Check Docker logs."
        }
    } finally {
        Pop-Location
    }
}

# ============================================================================
# SUMMARY REPORT
# ============================================================================

function Show-Summary {
    param(
        [hashtable]$Stats,
        [string]$DockerRoot,
        [string]$DataRoot
    )

    Write-Header "SETUP COMPLETE - SUMMARY"

    Write-Host ""
    Write-Host "Directories Created:" -ForegroundColor Cyan
    Write-Host "  Docker configs:   $($Stats.DockerDirsCreated) new, $($Stats.DockerDirsExisted) existing" -ForegroundColor White
    Write-Host "  Media directories: $($Stats.MediaDirsCreated) new, $($Stats.MediaDirsExisted) existing" -ForegroundColor White

    Write-Host ""
    Write-Host "Configuration:" -ForegroundColor Cyan
    Write-Host "  DOCKER_ROOT: $DockerRoot" -ForegroundColor White
    Write-Host "  DATA_ROOT:   $DataRoot" -ForegroundColor White
    Write-Host "  .env file:   $(Join-Path $DockerRoot '.env')" -ForegroundColor White

    Write-Host ""
    Write-Host "Next Steps:" -ForegroundColor Cyan
    Write-Host "  1. Verify OpenVPN config file is placed at:" -ForegroundColor White
    Write-Host "     $DockerRoot\gluetun\custom.ovpn" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  2. Review and customize configuration files:" -ForegroundColor White
    Write-Host "     • $DockerRoot\homepage\config\*.yaml" -ForegroundColor Gray
    Write-Host "     • $DockerRoot\recyclarr\config\recyclarr.yml" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  3. Access the services once they're running:" -ForegroundColor White
    Write-Host "     • Homepage:   http://localhost:3000" -ForegroundColor Gray
    Write-Host "     • Plex:       http://localhost:32400" -ForegroundColor Gray
    Write-Host "     • Radarr:     http://localhost:7878" -ForegroundColor Gray
    Write-Host "     • Sonarr:     http://localhost:8989" -ForegroundColor Gray
    Write-Host "     • Lidarr:     http://localhost:8686" -ForegroundColor Gray
    Write-Host "     • qBittorrent: http://localhost:8081" -ForegroundColor Gray
    Write-Host "     • Portainer:  http://localhost:9000" -ForegroundColor Gray
    Write-Host "     • Tdarr:      http://localhost:8265" -ForegroundColor Gray
    Write-Host "     • Overseerr:  http://localhost:5055" -ForegroundColor Gray
    Write-Host "     • Immich:     http://localhost:2283" -ForegroundColor Gray
    Write-Host "     • Pi-hole:    http://localhost:8080/admin" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  4. After first launch, add API keys to .env:" -ForegroundColor White
    Write-Host "     • Get from each app's Settings > General > API Key" -ForegroundColor Gray
    Write-Host "     • Update: $DockerRoot\.env" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  5. Useful Docker commands:" -ForegroundColor White
    Write-Host "     docker compose ps          # See running containers" -ForegroundColor Gray
    Write-Host "     docker compose logs -f     # View live logs" -ForegroundColor Gray
    Write-Host "     docker compose restart     # Restart all services" -ForegroundColor Gray
    Write-Host "     docker compose down        # Stop all services" -ForegroundColor Gray

    Write-Host ""
    Write-Host "Documentation:" -ForegroundColor Cyan
    Write-Host "  GitHub: https://github.com/yourusername/harbor-media-server" -ForegroundColor Gray
    Write-Host "  Wiki:   https://github.com/yourusername/harbor-media-server/wiki" -ForegroundColor Gray

    Write-Host ""
}

# ============================================================================
# MAIN SCRIPT
# ============================================================================

function Main {
    Clear-Host

    Write-Header "HARBOR MEDIA SERVER — SETUP"

    # Show preflight checklist
    Show-PreflightChecklist

    # Test prerequisites
    if (-not (Test-Prerequisites)) {
        Write-Header "SETUP FAILED"
        Write-Error "Prerequisites not met. Please install required software and try again."
        exit 1
    }

    # Scan for port conflicts
    if (-not (Scan-PortConflicts)) {
        Write-Header "SETUP INTERRUPTED"
        Write-Error "Port conflicts detected. Please resolve them and try again."
        exit 1
    }

    # Get user paths
    $paths = Get-UserPaths
    $dockerRoot = $paths.DockerRoot
    $dataRoot = $paths.DataRoot

    # Create directory structure
    $stats = New-DirectoryStructure -DockerRoot $dockerRoot -DataRoot $dataRoot

    # Copy configuration files
    $sourceDir = Split-Path -Parent $PSCommandPath
    Copy-ConfigFiles -DockerRoot $dockerRoot -SourceDir $sourceDir | Out-Null

    # Generate .env file
    New-EnvironmentFile -DockerRoot $dockerRoot -DataRoot $dataRoot | Out-Null

    # Copy docker-compose.yml
    if (-not (Copy-DockerCompose -DockerRoot $dockerRoot -SourceDir $sourceDir)) {
        Write-Error "Failed to copy docker-compose.yml"
        exit 1
    }

    # Validate VPN configuration
    Test-VpnConfiguration -DockerRoot $dockerRoot | Out-Null

    # Check for native qBittorrent
    Test-QbittorrentNative

    # Show summary
    Show-Summary -Stats $stats -DockerRoot $dockerRoot -DataRoot $dataRoot

    # First launch option
    if (-not $AutoLaunch) {
        Start-FirstLaunch -DockerRoot $dockerRoot
    } else {
        Write-Info "Auto-launch disabled. To start services, run:"
        Write-Host "  cd $dockerRoot" -ForegroundColor Cyan
        Write-Host "  docker compose up -d --build" -ForegroundColor Cyan
    }

    Write-Host ""
    Write-Success "Setup completed!"
    Write-Host ""
}

# Run main function
try {
    Main
} catch {
    Write-Host ""
    Write-Error "Setup script error: $_"
    Write-Error "Stack trace: $($_.ScriptStackTrace)"
    exit 1
}
