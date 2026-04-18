[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$NasUser = 'harboradmin',
    [string]$NasPassword = 'change_me',
    [switch]$SkipEicar
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($NasHost)) {
    $NasHost = 'synology.example.lan'
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$envPath = Join-Path $repoRoot '.env.synology.local'
$dockerRoot = "\\$NasHost\docker\harbor\appdata"
$dataRoot = "\\$NasHost\media"
$downloadsRoot = "\\$NasHost\downloads"
$quarantineRoot = "\\$NasHost\quarantine"
$dockerRootPosix = '/volume1/docker/harbor/appdata'
$dataRootPosix = '/volume1/media'
$downloadsRootPosix = '/volume1/downloads'
$quarantineRootPosix = '/volume1/quarantine'
$snapshotPathPosix = '/volume1/docker/harbor/appdata/download-orchestrator/snapshot.json'

function Import-DotEnv {
    param([string]$Path)

    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if (-not $line -or $line.TrimStart().StartsWith('#')) {
            continue
        }
        $parts = $line -split '=', 2
        if ($parts.Count -ne 2) {
            continue
        }
        $map[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $map
}

function Get-XmlValue {
    param(
        [string]$Path,
        [string]$Element
    )

    [xml]$xml = Get-Content -LiteralPath $Path
    return $xml.Config.$Element
}

function Invoke-NasCommand {
    param([string]$Command)

    $commandB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Command))
    $python = @"
import base64
import paramiko

host = r'''$NasHost'''
user = r'''$NasUser'''
password = r'''$NasPassword'''
command = base64.b64decode(r'''$commandB64''').decode('utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=host, username=user, password=password, timeout=30, banner_timeout=30, auth_timeout=30)
stdin, stdout, stderr = client.exec_command(command, get_pty=True)
if 'sudo ' in command:
    stdin.write(password + '\n')
    stdin.flush()
exit_code = stdout.channel.recv_exit_status()
out = stdout.read().decode('utf-8', 'ignore')
err = stderr.read().decode('utf-8', 'ignore')
print(out, end='')
if err and exit_code != 0:
    print(err, end='')
client.close()
raise SystemExit(exit_code)
"@

    $python | python -
}

function Get-NasFileContent {
    param([string]$RemotePath)

    $escapedPath = $RemotePath.Replace('\', '\\').Replace('"', '\"')
    return (@(Invoke-NasCommand -Command "cat `"$escapedPath`"") -join "`n")
}

function Test-NasPathExists {
    param([string]$RemotePath)

    $escapedPath = $RemotePath.Replace('\', '\\').Replace('"', '\"')
    $result = @(
        Invoke-NasCommand -Command "if [ -e `"$escapedPath`" ]; then echo EXISTS; else echo MISSING; fi"
    ) -join "`n"
    return $result -match 'EXISTS'
}

function Wait-NasPathAppears {
    param(
        [string]$RemotePath,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-NasPathExists -RemotePath $RemotePath) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-NasPathRemoved {
    param(
        [string]$RemotePath,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-NasPathExists -RemotePath $RemotePath)) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

$results = New-Object System.Collections.Generic.List[object]
$warnings = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Category,
        [string]$Name,
        [bool]$Ok,
        [object]$Detail
    )

    $results.Add([pscustomobject]@{
        Category = $Category
        Name = $Name
        Ok = $Ok
        Detail = $Detail
    })
}

function Add-Warning {
    param(
        [string]$Category,
        [string]$Name,
        [object]$Detail
    )

    $warnings.Add([pscustomobject]@{
        Category = $Category
        Name = $Name
        Detail = $Detail
    })
}

function Invoke-HttpCheck {
    param(
        [string]$Category,
        [string]$Name,
        [string]$Url
    )

    $tempPath = [System.IO.Path]::GetTempFileName()
    try {
        $curlOutput = & curl.exe --http1.1 -sS -L -m 40 $Url -o $tempPath -w "HTTP_CODE=%{http_code}"
        $statusCode = $null
        if ($curlOutput -match 'HTTP_CODE=(\d{3})') {
            $statusCode = [int]$Matches[1]
        }
        $detail = if ($null -ne $statusCode) { $statusCode } else { 'no-status' }
        Add-Result -Category $Category -Name $Name -Ok ($statusCode -ge 200 -and $statusCode -lt 400) -Detail $detail
    }
    catch {
        Add-Result -Category $Category -Name $Name -Ok $false -Detail $_.Exception.Message
    }
    finally {
        Remove-Item -LiteralPath $tempPath -ErrorAction SilentlyContinue
    }
}

function Invoke-RestWithRetry {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [Microsoft.PowerShell.Commands.WebRequestSession]$WebSession,
        [int]$Attempts = 5
    )

    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            if ($WebSession) {
                return Invoke-RestMethod -Uri $Uri -Headers $Headers -WebSession $WebSession -TimeoutSec 30
            }
            return Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 30
        }
        catch {
            $lastError = $_
            if ($attempt -lt $Attempts) {
                Start-Sleep -Seconds 2
            }
        }
    }
    throw $lastError
}

function Test-PathAppears {
    param(
        [string]$Path,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

$envMap = Import-DotEnv -Path $envPath

$readiness = & (Join-Path $PSScriptRoot 'Test-SynologyBringupReadiness.ps1') -NasHost $NasHost | Out-String
$readinessJson = $readiness | ConvertFrom-Json
Add-Result -Category 'meta' -Name 'bringup-readiness' -Ok ($readinessJson.failures.Count -eq 0) -Detail @{
    warnings = $readinessJson.warnings.Count
    failures = $readinessJson.failures.Count
}
foreach ($warning in $readinessJson.warnings) {
    Add-Warning -Category 'readiness' -Name $warning.name -Detail $warning.detail
}

foreach ($check in @(
    @{ Name = 'NAS Homepage'; Url = "http://${NasHost}:3000" },
    @{ Name = 'NAS Plex'; Url = "http://${NasHost}:32401/identity" },
    @{ Name = 'NAS Immich'; Url = "http://${NasHost}:2283/api/server/ping" },
    @{ Name = 'NAS Radarr'; Url = "http://${NasHost}:7878/ping" },
    @{ Name = 'NAS Sonarr'; Url = "http://${NasHost}:8989/ping" },
    @{ Name = 'NAS Lidarr'; Url = "http://${NasHost}:8686/ping" },
    @{ Name = 'NAS Bazarr'; Url = "http://${NasHost}:6767" },
    @{ Name = 'NAS Prowlarr'; Url = "http://${NasHost}:9696/ping" },
    @{ Name = 'NAS Overseerr'; Url = "http://${NasHost}:5055/login" },
    @{ Name = 'NAS qBittorrent'; Url = "http://${NasHost}:8081" },
    @{ Name = 'NAS SABnzbd'; Url = "http://${NasHost}:8082/wizard/" },
    @{ Name = 'NAS Tdarr'; Url = "http://${NasHost}:8265" },
    @{ Name = 'NAS Pi-hole'; Url = "http://${NasHost}:9080/admin/login" },
    @{ Name = 'NAS Update Status'; Url = "http://${NasHost}:8099" },
    @{ Name = 'Localhost Homepage'; Url = 'http://localhost:3000' },
    @{ Name = 'Localhost Plex'; Url = 'http://localhost:32400/identity' },
    @{ Name = 'Localhost Immich'; Url = 'http://localhost:2283/api/server/ping' },
    @{ Name = 'Localhost Radarr'; Url = 'http://localhost:7878/ping' },
    @{ Name = 'Localhost Sonarr'; Url = 'http://localhost:8989/ping' },
    @{ Name = 'Localhost Lidarr'; Url = 'http://localhost:8686/ping' },
    @{ Name = 'Localhost Prowlarr'; Url = 'http://localhost:9696/ping' },
    @{ Name = 'Localhost qBittorrent'; Url = 'http://localhost:8081' },
    @{ Name = 'Localhost Tdarr'; Url = 'http://localhost:8265' },
    @{ Name = 'Localhost Pi-hole'; Url = 'http://localhost:9080/admin/login' }
)) {
    Invoke-HttpCheck -Category 'http' -Name $check.Name -Url $check.Url
}

try {
    $dockerPs = Invoke-NasCommand -Command 'sudo -S /var/packages/ContainerManager/target/usr/bin/docker ps --format ''{{.Names}}|{{.Status}}'''
    $runningContainers = @{}
    $lines = $dockerPs -split "`r?`n" | Where-Object { $_ -and ($_ -match '\|') }
    foreach ($line in $lines) {
        $parts = $line -split '\|', 2
        $runningContainers[$parts[0]] = $parts[1]
        Add-Result -Category 'docker' -Name $parts[0] -Ok ($parts[1] -match 'Up') -Detail $parts[1]
    }

    $requiredRunningContainers = @(
        'download-orchestrator', 'gluetun', 'qbittorrent', 'sabnzbd', 'clamav', 'scanner',
        'homepage', 'overseerr', 'prowlarr', 'radarr', 'sonarr', 'lidarr', 'bazarr', 'plex'
    )
    foreach ($requiredContainer in $requiredRunningContainers) {
        if (-not $runningContainers.ContainsKey($requiredContainer)) {
            Add-Result -Category 'docker' -Name $requiredContainer -Ok $false -Detail 'missing from docker ps'
        }
    }
}
catch {
    Add-Result -Category 'docker' -Name 'docker-ps' -Ok $false -Detail $_.Exception.Message
}

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri "http://${NasHost}:8081/api/v2/auth/login" -Method Post -Body @{
    username = $envMap['QBIT_USER']
    password = $envMap['QBIT_PASS']
} -WebSession $session -TimeoutSec 20 -UseBasicParsing | Out-Null

$qbitPrefs = Invoke-RestMethod -Uri "http://${NasHost}:8081/api/v2/app/preferences" -WebSession $session -TimeoutSec 20
$qbitTransfer = Invoke-RestMethod -Uri "http://${NasHost}:8081/api/v2/transfer/info" -WebSession $session -TimeoutSec 20
$qbitTorrents = Invoke-RestMethod -Uri "http://${NasHost}:8081/api/v2/torrents/info?filter=all" -WebSession $session -TimeoutSec 30
$forwardedPort = ((Invoke-NasCommand -Command "cat '/volume1/docker/harbor/appdata/gluetun-port/forwarded_port'").Trim() -replace '[^\d]', '')

Add-Result -Category 'qbit' -Name 'listen-port-aligned' -Ok ([string]$qbitPrefs.listen_port -eq [string]$forwardedPort) -Detail "qB=$($qbitPrefs.listen_port) gluetun=$forwardedPort"
Add-Result -Category 'qbit' -Name 'bound-interface' -Ok ($qbitPrefs.current_network_interface -eq 'tun0') -Detail $qbitPrefs.current_network_interface
Add-Result -Category 'qbit' -Name 'save-path' -Ok ($qbitPrefs.save_path -eq '/downloads') -Detail $qbitPrefs.save_path
Add-Result -Category 'qbit' -Name 'temp-path' -Ok ($qbitPrefs.temp_path -eq '/downloads/incomplete') -Detail $qbitPrefs.temp_path
Add-Result -Category 'qbit' -Name 'slow-torrents-dont-count' -Ok ([bool]$qbitPrefs.dont_count_slow_torrents) -Detail $qbitPrefs.dont_count_slow_torrents
Add-Result -Category 'qbit' -Name 'active-download-budget' -Ok ($qbitPrefs.max_active_downloads -ge 3) -Detail $qbitPrefs.max_active_downloads
Add-Result -Category 'qbit' -Name 'active-downloaders' -Ok ((@($qbitTorrents | Where-Object { $_.state -match 'downloading|forcedDL' })).Count -ge 1) -Detail ((@($qbitTorrents | Where-Object { $_.state -match 'downloading|forcedDL' })).Count)
Add-Result -Category 'qbit' -Name 'transfer-sample' -Ok $true -Detail "dl=$($qbitTransfer.dl_info_speed) up=$($qbitTransfer.up_info_speed)"

$socketCheck = @'
import socket, sys
host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(8)
ok = False
try:
    s.connect((host, port))
    ok = True
except Exception:
    ok = False
finally:
    s.close()
print("PORT_OPEN" if ok else "PORT_CLOSED")
'@
$publicIpRaw = @((Invoke-NasCommand -Command "sudo -S -p '' /var/packages/ContainerManager/target/usr/bin/docker exec gluetun sh -c 'if command -v curl >/dev/null 2>&1; then curl -fsS https://ifconfig.me/ip; else wget -qO- https://ifconfig.me/ip; fi'")) -join "`n"
$publicIp = $null
if ($publicIpRaw -match '(\d{1,3}(?:\.\d{1,3}){3})') {
    $publicIp = $Matches[1]
}

if ($publicIp) {
    $socketResult = $socketCheck | python - $publicIp $forwardedPort
    $socketText = (@($socketResult) -join "`n").Trim()
    Add-Result -Category 'vpn' -Name 'forwarded-port-open' -Ok ($socketText -match 'PORT_OPEN') -Detail "${publicIp}:${forwardedPort} => $socketText"
}
else {
    Add-Warning -Category 'vpn' -Name 'forwarded-port-open' -Detail "Could not determine Gluetun exit IP from: $publicIpRaw"
}

$snapshotRaw = Get-NasFileContent -RemotePath $snapshotPathPosix
if ([string]::IsNullOrWhiteSpace($snapshotRaw)) {
    Add-Warning -Category 'orchestrator' -Name 'snapshot-read' -Detail "Could not read $snapshotPathPosix"
}
else {
    $snapshot = $snapshotRaw | ConvertFrom-Json
    Add-Result -Category 'orchestrator' -Name 'tunnel-guard' -Ok ([bool]$snapshot.tunnelGuard.ok) -Detail $snapshot.tunnelGuard
    $policyMode = $snapshot.policy.mode
    $policyAllowed = $snapshot.policy.allowedCount
    $listenPort = $snapshot.tunnelGuard.listenPort
    $forwardedTunnelPort = $snapshot.tunnelGuard.forwardedPort
    Add-Result -Category 'orchestrator' -Name 'mode-is-expansive-or-balanced' -Ok ($policyMode -in @('expansive', 'balanced')) -Detail $policyMode
    Add-Result -Category 'orchestrator' -Name 'allowed-count-positive' -Ok ([int]$policyAllowed -ge 1) -Detail $policyAllowed
    Add-Result -Category 'orchestrator' -Name 'port-alignment' -Ok ([string]$listenPort -eq [string]$forwardedTunnelPort) -Detail "listen=$listenPort forwarded=$forwardedTunnelPort"
}

$radarrKey = $envMap['RADARR_API_KEY']
$sonarrKey = $envMap['SONARR_API_KEY']
$lidarrKey = $envMap['LIDARR_API_KEY']
$prowlarrKey = $envMap['PROWLARR_API_KEY']

$radarrRoots = Invoke-RestWithRetry -Uri "http://${NasHost}:7878/api/v3/rootfolder" -Headers @{ 'X-Api-Key' = $radarrKey }
$sonarrRoots = Invoke-RestWithRetry -Uri "http://${NasHost}:8989/api/v3/rootfolder" -Headers @{ 'X-Api-Key' = $sonarrKey }
$lidarrRoots = Invoke-RestWithRetry -Uri "http://${NasHost}:8686/api/v1/rootfolder" -Headers @{ 'X-Api-Key' = $lidarrKey }
$radarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:7878/api/v3/downloadclient" -Headers @{ 'X-Api-Key' = $radarrKey }
$sonarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:8989/api/v3/downloadclient" -Headers @{ 'X-Api-Key' = $sonarrKey }
$lidarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:8686/api/v1/downloadclient" -Headers @{ 'X-Api-Key' = $lidarrKey }
$prowlarrApps = Invoke-RestWithRetry -Uri "http://${NasHost}:9696/api/v1/applications" -Headers @{ 'X-Api-Key' = $prowlarrKey }
$prowlarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:9696/api/v1/downloadclient" -Headers @{ 'X-Api-Key' = $prowlarrKey }
$prowlarrProxies = Invoke-RestWithRetry -Uri "http://${NasHost}:9696/api/v1/indexerProxy" -Headers @{ 'X-Api-Key' = $prowlarrKey }

function Test-ClientHost {
    param([object[]]$Clients, [string]$ExpectedHost, [int]$ExpectedPort)
    foreach ($client in @($Clients)) {
        $fields = @{}
        foreach ($field in @($client.fields)) {
            $fields[$field.name] = $field.value
        }
        if ($fields['host'] -eq $ExpectedHost -and [int]$fields['port'] -eq $ExpectedPort) {
            return $true
        }
    }
    return $false
}

Add-Result -Category 'arr' -Name 'radarr-root-movies' -Ok (@($radarrRoots | Where-Object path -eq '/movies').Count -ge 1) -Detail (@($radarrRoots | Select-Object path,accessible,freeSpace))
Add-Result -Category 'arr' -Name 'sonarr-root-tv' -Ok (@($sonarrRoots | Where-Object path -eq '/tv').Count -ge 1) -Detail (@($sonarrRoots | Select-Object path,accessible,freeSpace))
Add-Result -Category 'arr' -Name 'lidarr-root-music' -Ok (@($lidarrRoots | Where-Object path -eq '/music').Count -ge 1) -Detail (@($lidarrRoots | Select-Object path,accessible,freeSpace))
Add-Result -Category 'arr' -Name 'radarr-qbit-client' -Ok (Test-ClientHost -Clients $radarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081) -Detail 'expects gluetun:8081'
Add-Result -Category 'arr' -Name 'sonarr-qbit-client' -Ok (Test-ClientHost -Clients $sonarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081) -Detail 'expects gluetun:8081'
Add-Result -Category 'arr' -Name 'lidarr-qbit-client' -Ok (Test-ClientHost -Clients $lidarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081) -Detail 'expects gluetun:8081'
Add-Result -Category 'prowlarr' -Name 'qbit-client' -Ok (Test-ClientHost -Clients $prowlarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081) -Detail 'expects gluetun:8081'
Add-Result -Category 'prowlarr' -Name 'flaresolverr-proxy' -Ok (@($prowlarrProxies | Where-Object { $_.name -eq 'Harbor FlareSolverr' }).Count -ge 1) -Detail (@($prowlarrProxies | Select-Object name,implementationName,tags))
$appBaseUrls = foreach ($app in @($prowlarrApps)) { foreach ($field in @($app.fields)) { if ($field.name -eq 'baseUrl') { $field.value } } }
Add-Result -Category 'prowlarr' -Name 'application-targets' -Ok ((@('http://radarr:7878','http://sonarr:8989','http://lidarr:8686') | ForEach-Object { $appBaseUrls -contains $_ } | Where-Object { $_ }).Count -eq 3) -Detail $appBaseUrls

$overseerrSettings = Get-NasFileContent -RemotePath '/volume1/docker/harbor/appdata/overseerr/config/settings.json' | ConvertFrom-Json
$overseerrHeaders = @{ 'X-Api-Key' = $overseerrSettings.main.apiKey }
$plexSettings = Invoke-RestWithRetry -Uri "http://${NasHost}:5055/api/v1/settings/plex" -Headers $overseerrHeaders
$plexServers = Invoke-RestWithRetry -Uri "http://${NasHost}:5055/api/v1/settings/plex/devices/servers" -Headers $overseerrHeaders
$plexLibraries = Invoke-RestWithRetry -Uri "http://${NasHost}:5055/api/v1/settings/plex/library?sync=true" -Headers $overseerrHeaders
$serviceRadarr = Invoke-RestWithRetry -Uri "http://${NasHost}:5055/api/v1/service/radarr" -Headers $overseerrHeaders
$serviceSonarr = Invoke-RestWithRetry -Uri "http://${NasHost}:5055/api/v1/service/sonarr" -Headers $overseerrHeaders
Add-Result -Category 'overseerr' -Name 'radarr-linked' -Ok (@($serviceRadarr).Count -ge 1) -Detail $serviceRadarr
Add-Result -Category 'overseerr' -Name 'sonarr-linked' -Ok (@($serviceSonarr).Count -ge 1) -Detail $serviceSonarr
Add-Result -Category 'overseerr' -Name 'plex-server-visible' -Ok (@($plexServers).Count -ge 1) -Detail (@($plexServers | Select-Object name,productVersion,presence,publicAddressMatches))
Add-Result -Category 'overseerr' -Name 'plex-libraries-visible' -Ok (@($plexLibraries).Count -ge 2) -Detail $plexLibraries
if ((@($plexSettings.libraries | Where-Object enabled).Count) -lt 1) {
    Add-Warning -Category 'overseerr' -Name 'plex-library-enable-persistence' -Detail 'Overseerr sees the NAS Plex libraries, but does not persist the enabled flags across reads. Request routing still works.'
}

$tdarrQsvResult = Invoke-NasCommand -Command @'
/var/packages/ContainerManager/target/usr/bin/docker exec tdarr sh -lc "sample=\$(find /media -type f \( -name '*.mkv' -o -name '*.mp4' \) | head -n 1); test -n \"\$sample\"; ffmpeg -hide_banner -y -v error -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -hwaccel qsv -hwaccel_output_format qsv -i \"\$sample\" -t 5 -c:v h264_qsv -c:a copy /tmp/tdarr-qsv-test.mp4 && test -s /tmp/tdarr-qsv-test.mp4 && rm -f /tmp/tdarr-qsv-test.mp4 && echo QSV_OK"
'@
$tdarrQsvText = (@($tdarrQsvResult) -join "`n").Trim()
Add-Result -Category 'tdarr' -Name 'qsv-transcode' -Ok ($tdarrQsvText -match 'QSV_OK') -Detail $tdarrQsvText

if (-not $SkipEicar) {
    $eicarPath = "$downloadsRootPosix/_omega_eicar/eicar.com.txt"
    $quarantinedPath = "$quarantineRootPosix/_omega_eicar/eicar.com.txt"
    Invoke-NasCommand -Command @'
mkdir -p /volume1/downloads/_omega_eicar /volume1/quarantine/_omega_eicar
rm -f /volume1/downloads/_omega_eicar/eicar.com.txt /volume1/quarantine/_omega_eicar/eicar.com.txt
printf 'X5O!P%%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /volume1/downloads/_omega_eicar/eicar.com.txt
touch -d '20 minutes ago' /volume1/downloads/_omega_eicar/eicar.com.txt
'@
    $quarantined = Wait-NasPathAppears -RemotePath $quarantinedPath -TimeoutSeconds 180
    $sourceRemoved = $false
    if ($quarantined) {
        $sourceRemoved = Wait-NasPathRemoved -RemotePath $eicarPath -TimeoutSeconds 60
    }
    Add-Result -Category 'scanner' -Name 'eicar-quarantine' -Ok $quarantined -Detail @{
        quarantined = $quarantined
        sourceRemoved = $sourceRemoved
        quarantinePath = $quarantinedPath
    }
    Invoke-NasCommand -Command "rm -f /volume1/downloads/_omega_eicar/eicar.com.txt /volume1/quarantine/_omega_eicar/eicar.com.txt"
}

$sampleMovie = Invoke-RestWithRetry -Uri "http://${NasHost}:7878/api/v3/movie?hasFile=true" -Headers @{ 'X-Api-Key' = $radarrKey }
$chosenMovie = $sampleMovie | Where-Object { $_.path -and $_.movieFile.path } | Select-Object -First 1
if ($null -ne $chosenMovie) {
    $prefsText = Get-NasFileContent -RemotePath '/volume1/docker/harbor/appdata/plex/config/Library/Application Support/Plex Media Server/Preferences.xml'
    if ($prefsText -match 'PlexOnlineToken="([^"]+)"') {
        $plexToken = $Matches[1]
        $plexSearch = Invoke-WebRequest -Uri ("http://${NasHost}:32401/search?query=" + [uri]::EscapeDataString($chosenMovie.title)) -Headers @{ 'X-Plex-Token' = $plexToken; 'Accept' = 'application/json' } -TimeoutSec 30 -UseBasicParsing
        $chosenMovieNasPath = "$dataRootPosix/movies" + ($chosenMovie.path -replace '^/movies', '')
        Add-Result -Category 'pipeline' -Name 'radarr-file-exists' -Ok (Test-NasPathExists -RemotePath $chosenMovieNasPath) -Detail $chosenMovie.path
        Add-Result -Category 'pipeline' -Name 'plex-can-find-sample-movie' -Ok ($plexSearch.StatusCode -ge 200 -and $plexSearch.StatusCode -lt 400 -and $plexSearch.Content -match [regex]::Escape($chosenMovie.title)) -Detail $chosenMovie.title
    }
}

$readinessFailures = @($results | Where-Object { -not $_.Ok })
$payload = [pscustomobject]@{
    timestamp = (Get-Date).ToString('o')
    host = $NasHost
    warnings = $warnings
    failures = $readinessFailures
    checks = $results
}

$payload | ConvertTo-Json -Depth 8

if ($readinessFailures.Count -gt 0) {
    exit 1
}

