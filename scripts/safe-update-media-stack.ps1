param(
    [switch]$Preview,
    [switch]$SkipPull,
    [switch]$SkipBackup
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

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

function Invoke-ComposeCapture {
    param([string[]]$Args)

    $commandArgs = @('compose', '--profile', 'experimental', '-f', $script:ComposeFile, '--env-file', $script:EnvFile) + $Args
    $stderrPath = [System.IO.Path]::GetTempFileName()

    try {
        $stdout = (& docker @commandArgs 2> $stderrPath | Out-String)
        $exitCode = $LASTEXITCODE
        $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { '' }

        return [pscustomobject]@{
            ExitCode = $exitCode
            StdOut = $stdout
            StdErr = $stderr
            Command = "docker " + ($commandArgs -join ' ')
        }
    } finally {
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Compose {
    param([string[]]$Args)

    $result = Invoke-ComposeCapture -Args $Args
    if ($result.ExitCode -ne 0) {
        $details = @($result.StdOut.Trim(), $result.StdErr.Trim()) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        throw ($result.Command + "`n" + ($details -join "`n"))
    }

    return $result.StdOut
}

function Invoke-ComposeNoThrow {
    param([string[]]$Args)

    $result = Invoke-ComposeCapture -Args $Args
    return [pscustomobject]@{
        ExitCode = $result.ExitCode
        Output = (($result.StdOut, $result.StdErr) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join "`n"
    }
}

function Convert-ComposeJson {
    param(
        [string]$Text,
        [switch]$JsonLines
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return @()
    }

    $trimmed = $Text.Trim()

    try {
        return $trimmed | ConvertFrom-Json
    } catch {
        $lines = @(
            $trimmed -split "(`r`n|`n)" |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Where-Object { $_.StartsWith('{') -or $_.StartsWith('[') }
        )
        if ($JsonLines -or $lines.Count -gt 1) {
            return @($lines | ForEach-Object { $_ | ConvertFrom-Json })
        }

        throw
    }
}

function Get-ComposeConfig {
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $json = (& docker compose --profile experimental -f $script:ComposeFile --env-file $script:EnvFile config --format json 2> $stderrPath | Out-String)
        if ($LASTEXITCODE -ne 0) {
            $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { '' }
            throw ("docker compose config --format json failed`n" + $stderr.Trim())
        }
    } finally {
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }

    return Convert-ComposeJson -Text $json
}

function Get-ComposePs {
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $json = (& docker compose --profile experimental -f $script:ComposeFile --env-file $script:EnvFile ps --format json 2> $stderrPath | Out-String)
        if ($LASTEXITCODE -ne 0) {
            $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { '' }
            throw ("docker compose ps --format json failed`n" + $stderr.Trim())
        }
    } finally {
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }

    return @(Convert-ComposeJson -Text $json -JsonLines)
}

function Wait-ContainerHealthy {
    param(
        [string]$Container,
        [int]$TimeoutSeconds = 240
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $Container 2>$null
        if ($LASTEXITCODE -eq 0 -and ($status -eq 'healthy' -or $status -eq 'running')) {
            return $true
        }

        Start-Sleep -Seconds 3
    }

    return $false
}

function Wait-Http {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds = 180,
        [int[]]$AcceptStatus = @(200, 204, 302, 307, 401)
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 10
            if ($AcceptStatus -contains [int]$response.StatusCode) {
                return $true
            }
        } catch {
            $resp = $_.Exception.Response
            if ($resp -and ($AcceptStatus -contains [int]$resp.StatusCode)) {
                return $true
            }
        }

        Start-Sleep -Seconds 3
    }

    return $false
}

function Get-QbSession {
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    try {
        $response = Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:8081/api/v2/auth/login' -Body @{
            username = $script:EnvMap['QBIT_USER']
            password = $script:EnvMap['QBIT_PASS']
        } -WebSession $session -UseBasicParsing -TimeoutSec 20

        if ($response.Content -match 'Ok\.') {
            return $session
        }
    } catch {
        return $null
    }

    return $null
}

function Get-QbActivity {
    $session = Get-QbSession
    if (-not $session) {
        return [pscustomobject]@{
            Authenticated = $false
            DownloadingCount = 0
            ForcedDownloadingCount = 0
        }
    }

    $downloading = @(Invoke-RestMethod -Uri 'http://127.0.0.1:8081/api/v2/torrents/info?filter=downloading' -WebSession $session -TimeoutSec 20)
    $forced = @($downloading | Where-Object { $_.force_start -eq $true })

    return [pscustomobject]@{
        Authenticated = $true
        DownloadingCount = $downloading.Count
        ForcedDownloadingCount = $forced.Count
    }
}

function Get-PlexSessionCount {
    $prefPath = Join-Path $script:DockerRoot 'plex\config\Library\Application Support\Plex Media Server\Preferences.xml'
    if (-not (Test-Path -LiteralPath $prefPath)) {
        return 0
    }

    [xml]$xml = Get-Content -LiteralPath $prefPath
    $token = $xml.Preferences.PlexOnlineToken
    if ([string]::IsNullOrWhiteSpace($token)) {
        return 0
    }

    try {
        [xml]$sessions = Invoke-RestMethod -Uri ("http://127.0.0.1:32400/status/sessions?X-Plex-Token=" + $token) -TimeoutSec 20
        if ($sessions.MediaContainer.Metadata) {
            return @($sessions.MediaContainer.Metadata).Count
        }
    } catch {
        return 0
    }

    return 0
}

function Get-TdarrBusy {
    $output = docker exec tdarr sh -lc "pgrep -fa 'ffmpeg|Tdarr_Node|Tdarr_Transcode' || true" 2>$null | Out-String
    return (-not [string]::IsNullOrWhiteSpace($output.Trim()))
}

function Get-ServiceApiKey {
    param(
        [string]$RelativeConfigPath,
        [string]$ContainerName
    )

    $configText = $null

    if (-not [string]::IsNullOrWhiteSpace($RelativeConfigPath)) {
        $configPath = Join-Path $script:DockerRoot $RelativeConfigPath
        if (Test-Path -LiteralPath $configPath) {
            $configText = Get-Content -LiteralPath $configPath -Raw
        }
    }

    if ([string]::IsNullOrWhiteSpace($configText) -and -not [string]::IsNullOrWhiteSpace($ContainerName)) {
        $configText = docker exec $ContainerName sh -lc "cat /config/config.xml" 2>$null | Out-String
    }

    if ([string]::IsNullOrWhiteSpace($configText)) {
        return $null
    }

    $match = [regex]::Match($configText, '<ApiKey>([^<]+)</ApiKey>')
    if (-not $match.Success) {
        return $null
    }

    return $match.Groups[1].Value
}

function Get-ServiceWarnings {
    param(
        [string]$ServiceName,
        [string]$BaseUrl,
        [string]$HealthPath,
        [string]$RelativeConfigPath,
        [string]$ContainerName
    )

    $apiKey = Get-ServiceApiKey -RelativeConfigPath $RelativeConfigPath -ContainerName $ContainerName
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        return @()
    }

    try {
        $items = @(Invoke-RestMethod -Headers @{ 'X-Api-Key' = $apiKey } -Uri ($BaseUrl + $HealthPath) -TimeoutSec 20)
        return @($items | ForEach-Object {
            [pscustomobject]@{
                service = $ServiceName
                source = $_.source
                type = $_.type
                message = $_.message
            }
        } | Where-Object { -not [string]::IsNullOrWhiteSpace($_.message) })
    } catch {
        return @([pscustomobject]@{
            service = $ServiceName
            source = 'UpdateGuardian'
            type = 'warning'
            message = "Could not query $ServiceName health: $($_.Exception.Message)"
        })
    }
}

function Get-RunningImageId {
    param([string]$ContainerName)
    return (docker inspect --format '{{.Image}}' $ContainerName 2>$null | Out-String).Trim()
}

function Get-LocalImageId {
    param([string]$ImageRef)
    return (docker image inspect --format '{{.Id}}' $ImageRef 2>$null | Out-String).Trim()
}

function New-Decision {
    param(
        [string]$Bundle,
        [string]$Status,
        [string]$Reason,
        [string[]]$Services
    )

    return [pscustomobject]@{
        bundle = $Bundle
        status = $Status
        reason = $Reason
        services = @($Services)
    }
}

function Get-EndpointMap {
    return @{
        'homepage' = @{ Uri = 'http://127.0.0.1:3000'; Accept = @(200) }
        'update-status' = @{ Uri = 'http://127.0.0.1:8099'; Accept = @(200) }
        'qbittorrent' = @{ Uri = 'http://127.0.0.1:8081'; Accept = @(200) }
        'sabnzbd' = @{ Uri = 'http://127.0.0.1:8082'; Accept = @(200) }
        'radarr' = @{ Uri = 'http://127.0.0.1:7878/ping'; Accept = @(200) }
        'sonarr' = @{ Uri = 'http://127.0.0.1:8989/ping'; Accept = @(200) }
        'lidarr' = @{ Uri = 'http://127.0.0.1:8686/ping'; Accept = @(200) }
        'bazarr' = @{ Uri = 'http://127.0.0.1:6767'; Accept = @(200) }
        'prowlarr' = @{ Uri = 'http://127.0.0.1:9696/ping'; Accept = @(200) }
        'overseerr' = @{ Uri = 'http://127.0.0.1:5055/api/v1/status'; Accept = @(200) }
        'plex' = @{ Uri = 'http://127.0.0.1:32400/identity'; Accept = @(200) }
        'pihole' = @{ Uri = 'http://127.0.0.1:8080/admin/login'; Accept = @(200, 302) }
        'tdarr' = @{ Uri = 'http://127.0.0.1:8265'; Accept = @(200) }
        'portainer' = @{ Uri = 'http://127.0.0.1:9000'; Accept = @(200) }
        'immich-server' = @{ Uri = 'http://127.0.0.1:2283/api/server/ping'; Accept = @(200) }
    }
}

function Test-ServiceValidation {
    param([string[]]$Services)

    $endpointMap = Get-EndpointMap
    foreach ($service in $Services) {
        $containerName = $script:ServiceMap[$service].container
        if (-not (Wait-ContainerHealthy -Container $containerName)) {
            return "Container did not become healthy: $service"
        }

        if ($endpointMap.ContainsKey($service)) {
            if (-not (Wait-Http -Uri $endpointMap[$service].Uri -AcceptStatus $endpointMap[$service].Accept)) {
                return "Endpoint check failed: $service"
            }
        }
    }

    return $null
}

function Write-StatusArtifacts {
    param(
        [pscustomobject]$Report
    )

    New-Item -ItemType Directory -Path $script:StatusRoot -Force | Out-Null
    $jsonPath = Join-Path $script:StatusRoot 'status.json'
    $htmlPath = Join-Path $script:StatusRoot 'index.html'

    $Report | ConvertTo-Json -Depth 12 | Set-Content -Path $jsonPath -Encoding UTF8

    $summaryColor = if ($Report.summaryStatus -eq 'ok') { '#16a34a' } elseif ($Report.summaryStatus -eq 'warning') { '#d97706' } else { '#dc2626' }

    $renderRows = {
        param($Items)
        if (-not $Items -or $Items.Count -eq 0) {
            return '<tr><td colspan="4">None</td></tr>'
        }

        return (($Items | ForEach-Object {
            $services = ($_.services -join ', ')
            "<tr><td>$($_.bundle)</td><td>$services</td><td>$($_.status)</td><td>$($_.reason)</td></tr>"
        }) -join "`n")
    }

    $renderWarnings = {
        param($Items)
        if (-not $Items -or $Items.Count -eq 0) {
            return '<li>None</li>'
        }

        return (($Items | ForEach-Object {
            "<li><strong>$($_.service)</strong>: $($_.message)</li>"
        }) -join "`n")
    }

    $html = @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Harbor Update Status</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin:0; background:#0f172a; color:#e5e7eb; font-family:Segoe UI, Arial, sans-serif; }
    main { max-width:1100px; margin:0 auto; padding:32px 20px 48px; }
    .hero { background:#111827; border:1px solid #1f2937; border-radius:18px; padding:24px; margin-bottom:24px; }
    .pill { display:inline-block; padding:6px 12px; border-radius:999px; font-weight:600; background:$summaryColor; color:white; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-top:20px; }
    .card { background:#111827; border:1px solid #1f2937; border-radius:16px; padding:18px; }
    h1,h2 { color:#f8fafc; }
    table { width:100%; border-collapse:collapse; background:#111827; border:1px solid #1f2937; border-radius:16px; overflow:hidden; }
    th,td { padding:12px; text-align:left; border-bottom:1px solid #1f2937; vertical-align:top; }
    th { background:#0b1220; color:#cbd5e1; }
    code { color:#93c5fd; }
    ul { line-height:1.6; }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="pill">$($Report.summaryStatus.ToUpperInvariant())</span>
      <h1>Harbor Safe Update Status</h1>
      <p>$($Report.summary)</p>
      <div class="grid">
        <div class="card"><strong>Last run</strong><br>$($Report.generatedAt)</div>
        <div class="card"><strong>Mode</strong><br>$($Report.mode)</div>
        <div class="card"><strong>Updated bundles</strong><br>$($Report.updated.Count)</div>
        <div class="card"><strong>Blocked or manual bundles</strong><br>$($Report.deferred.Count + $Report.manual.Count + $Report.failed.Count)</div>
      </div>
    </section>

    <h2>Updated Bundles</h2>
    <table>
      <thead><tr><th>Bundle</th><th>Services</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        $(& $renderRows $Report.updated)
      </tbody>
    </table>

    <h2>Deferred Bundles</h2>
    <table>
      <thead><tr><th>Bundle</th><th>Services</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        $(& $renderRows $Report.deferred)
      </tbody>
    </table>

    <h2>Manual or Protected Bundles</h2>
    <table>
      <thead><tr><th>Bundle</th><th>Services</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        $(& $renderRows $Report.manual)
      </tbody>
    </table>

    <h2>Failed Bundles</h2>
    <table>
      <thead><tr><th>Bundle</th><th>Services</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        $(& $renderRows $Report.failed)
      </tbody>
    </table>

    <h2>Application Warnings</h2>
    <ul>
      $(& $renderWarnings $Report.appWarnings)
    </ul>

    <h2>Notes</h2>
    <ul>
      <li>Registry-backed containers can be updated automatically when Harbor decides the update is safe.</li>
      <li>Repository-built services such as the scanner, port-updater, namespace guard, and download orchestrator are refreshed by pulling the repository and rebuilding, not by registry image updates.</li>
      <li>Protected services such as Pi-hole or complex stacks such as Immich may be intentionally deferred for manual review if Harbor decides an autonomous update could interrupt core infrastructure.</li>
    </ul>
  </main>
</body>
</html>
"@

    Set-Content -Path $htmlPath -Value $html -Encoding UTF8
}

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:ComposeFile = Join-Path $script:RepoRoot 'docker-compose.yml'
$script:EnvFile = Join-Path $script:RepoRoot '.env'
$script:EnvMap = Get-EnvMap -Path $script:EnvFile
$script:DockerRoot = $script:EnvMap['DOCKER_ROOT']

if ([string]::IsNullOrWhiteSpace($script:DockerRoot)) {
    throw "DOCKER_ROOT was not found in $script:EnvFile"
}

$script:StatusRoot = Join-Path $script:DockerRoot 'update-guardian\status'
$placeholderJsonPath = Join-Path $script:StatusRoot 'status.json'
$placeholderHtmlPath = Join-Path $script:StatusRoot 'index.html'
New-Item -ItemType Directory -Path $script:StatusRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $placeholderJsonPath)) {
    Set-Content -Path $placeholderJsonPath -Encoding UTF8 -Value (@'
{
  "generatedAt": null,
  "mode": "placeholder",
  "summaryStatus": "warning",
  "summary": "No safe-update scan has been run yet.",
  "backupCreated": false,
  "stackHealthy": false,
  "updated": [],
  "deferred": [],
  "manual": [],
  "failed": [],
  "appWarnings": []
}
'@)
}
if (-not (Test-Path -LiteralPath $placeholderHtmlPath)) {
    Set-Content -Path $placeholderHtmlPath -Encoding UTF8 -Value (@'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Harbor Update Status</title>
</head>
<body>
  <h1>Harbor Update Status</h1>
  <p>No safe-update scan has been run yet.</p>
</body>
</html>
'@)
}
$ServiceMap = @{}
$ComposeConfig = Get-ComposeConfig

foreach ($prop in $ComposeConfig.services.PSObject.Properties) {
    $serviceName = $prop.Name
    $serviceDef = $prop.Value
    $ServiceMap[$serviceName] = @{
        container = $serviceDef.container_name
        image = $serviceDef.image
        hasBuild = ($serviceDef.PSObject.Properties.Name -contains 'build')
    }
}

$BuildManagedServices = @(
    'download-orchestrator',
    'gluetun-namespace-guard',
    'port-updater',
    'scanner'
)

$BundleDefinitions = @(
    @{ Name = 'download-path'; Services = @('gluetun', 'qbittorrent', 'sabnzbd', 'port-updater', 'gluetun-namespace-guard'); Policy = 'downloads' },
    @{ Name = 'download-orchestrator'; Services = @('download-orchestrator'); Policy = 'downloads' },
    @{ Name = 'arr-stack'; Services = @('prowlarr', 'radarr', 'sonarr', 'lidarr', 'bazarr', 'flaresolverr', 'unpackerr', 'recyclarr', 'overseerr'); Policy = 'safe' },
    @{ Name = 'dashboard-and-ops'; Services = @('homepage', 'update-status', 'portainer', 'autoheal', 'watchtower', 'cloudflared'); Policy = 'safe' },
    @{ Name = 'plex'; Services = @('plex'); Policy = 'plex' },
    @{ Name = 'tdarr'; Services = @('tdarr'); Policy = 'tdarr' },
    @{ Name = 'immich-stack'; Services = @('immich-server', 'immich-machine-learning', 'immich-redis', 'immich-postgres'); Policy = 'manual' },
    @{ Name = 'pihole'; Services = @('pihole'); Policy = 'manual' },
    @{ Name = 'scanner-security'; Services = @('clamav', 'scanner'); Policy = 'safe' }
)

Write-Section 'Harbor safe update pass'
Write-Info ("Mode: " + ($(if ($Preview) { 'preview' } else { 'apply' })))

$psState = Get-ComposePs
$stackHealthy = $true
$nonBlockingHealthServices = @('update-status')
foreach ($row in $psState) {
    if ($nonBlockingHealthServices -contains $row.Service) {
        continue
    }

    $health = if ($row.Health) { $row.Health } else { $row.State }
    if ($health -notin @('healthy', 'running')) {
        $stackHealthy = $false
        break
    }
}

$appWarnings = @()
$appWarnings += Get-ServiceWarnings -ServiceName 'Radarr' -BaseUrl 'http://127.0.0.1:7878' -HealthPath '/api/v3/health' -RelativeConfigPath 'radarr\config\config.xml' -ContainerName 'radarr'
$appWarnings += Get-ServiceWarnings -ServiceName 'Sonarr' -BaseUrl 'http://127.0.0.1:8989' -HealthPath '/api/v3/health' -RelativeConfigPath 'sonarr\config\config.xml' -ContainerName 'sonarr'
$appWarnings += Get-ServiceWarnings -ServiceName 'Lidarr' -BaseUrl 'http://127.0.0.1:8686' -HealthPath '/api/v1/health' -RelativeConfigPath 'lidarr\config\config.xml' -ContainerName 'lidarr'
$appWarnings += Get-ServiceWarnings -ServiceName 'Prowlarr' -BaseUrl 'http://127.0.0.1:9696' -HealthPath '/api/v1/health' -RelativeConfigPath 'prowlarr\config\config.xml' -ContainerName 'prowlarr'

if (-not $SkipPull) {
    Write-Section 'Pulling latest images'
    Invoke-Compose -Args @('pull') | Out-Null
    Write-Good 'Pulled latest images for registry-backed services.'
} else {
    Write-Warn 'Skipping image pull.'
}

$OutdatedServices = @()
foreach ($serviceName in $ServiceMap.Keys) {
    $service = $ServiceMap[$serviceName]
    if ($service.hasBuild -or [string]::IsNullOrWhiteSpace($service.image)) {
        continue
    }

    $runningImageId = Get-RunningImageId -ContainerName $service.container
    $localImageId = Get-LocalImageId -ImageRef $service.image
    if (-not [string]::IsNullOrWhiteSpace($runningImageId) -and -not [string]::IsNullOrWhiteSpace($localImageId) -and $runningImageId -ne $localImageId) {
        $OutdatedServices += $serviceName
    }
}

$qbActivity = Get-QbActivity
$plexSessions = Get-PlexSessionCount
$tdarrBusy = Get-TdarrBusy

$updated = @()
$deferred = @()
$manual = @()
$failed = @()
$backupCreated = $false
$bootstrapNeeded = $false

if (-not $stackHealthy) {
    $deferred += New-Decision -Bundle 'global' -Status 'deferred' -Reason 'The stack is not fully healthy, so safe updates were skipped.' -Services @()
} else {
    foreach ($bundle in $BundleDefinitions) {
        $bundleOutdated = @($bundle.Services | Where-Object { $OutdatedServices -contains $_ })
        if ($bundleOutdated.Count -eq 0) {
            continue
        }

        switch ($bundle.Policy) {
            'downloads' {
                if ($qbActivity.DownloadingCount -gt 0) {
                    $deferred += New-Decision -Bundle $bundle.Name -Status 'deferred' -Reason "Active qB downloads detected ($($qbActivity.DownloadingCount)); Harbor is preserving the download path." -Services $bundleOutdated
                    continue
                }
            }
            'plex' {
                if ($plexSessions -gt 0) {
                    $deferred += New-Decision -Bundle $bundle.Name -Status 'deferred' -Reason "Plex has $plexSessions active session(s); media-serving updates were deferred." -Services $bundleOutdated
                    continue
                }
            }
            'tdarr' {
                if ($tdarrBusy) {
                    $deferred += New-Decision -Bundle $bundle.Name -Status 'deferred' -Reason 'Tdarr appears busy; transcode updates were deferred.' -Services $bundleOutdated
                    continue
                }
            }
            'manual' {
                $manual += New-Decision -Bundle $bundle.Name -Status 'manual' -Reason 'This bundle is protected and requires manual review before updates are applied.' -Services $bundleOutdated
                continue
            }
        }

        if ($Preview) {
            $updated += New-Decision -Bundle $bundle.Name -Status 'preview' -Reason 'Would update this bundle in apply mode.' -Services $bundleOutdated
            continue
        }

        if (-not $SkipBackup -and -not $backupCreated) {
            Write-Section 'Creating safety backup'
            & (Join-Path $script:RepoRoot 'scripts\backup-media-stack.ps1') | Out-Null
            $backupCreated = $true
            Write-Good 'Created a config backup before applying updates.'
        }

        Write-Section ("Updating bundle: " + $bundle.Name)
        try {
            Invoke-Compose -Args (@('up', '-d') + $bundleOutdated) | Out-Null
            $validationError = Test-ServiceValidation -Services $bundleOutdated
            if ($validationError) {
                $failed += New-Decision -Bundle $bundle.Name -Status 'failed' -Reason $validationError -Services $bundleOutdated
                break
            }

            $updated += New-Decision -Bundle $bundle.Name -Status 'updated' -Reason 'Bundle updated and validated successfully.' -Services $bundleOutdated

            if (@('download-path', 'download-orchestrator', 'arr-stack', 'dashboard-and-ops') -contains $bundle.Name) {
                $bootstrapNeeded = $true
            }
        } catch {
            $failed += New-Decision -Bundle $bundle.Name -Status 'failed' -Reason $_.Exception.Message -Services $bundleOutdated
            break
        }
    }

    if ($bootstrapNeeded -and $failed.Count -eq 0) {
        Write-Section 'Reapplying Harbor runtime defaults'
        & (Join-Path $script:RepoRoot 'scripts\bootstrap-media-stack.ps1')
        Write-Good 'Re-ran Harbor bootstrap to reinforce qB, SAB, Arr, Recyclarr, and Homepage settings after updates.'
    }
}

$repoManaged = @($BuildManagedServices | Where-Object { $ServiceMap.ContainsKey($_) })
foreach ($serviceName in $repoManaged) {
    $manual += New-Decision -Bundle $serviceName -Status 'manual' -Reason 'This service is built from the Harbor repository and is refreshed by git pull plus docker compose up -d --build, not by registry image updates.' -Services @($serviceName)
}

$summaryStatus = 'ok'
$summary = 'No updates were required or the safe-update pass completed without blockers.'
if ($failed.Count -gt 0) {
    $summaryStatus = 'error'
    $summary = 'At least one update bundle failed validation. Harbor stopped further autonomous updates and wrote the failure report.'
} elseif ($deferred.Count -gt 0 -or $manual.Count -gt 0 -or ($appWarnings | Where-Object { $_.type -eq 'warning' }).Count -gt 0) {
    $summaryStatus = 'warning'
    $summary = 'Harbor completed the safe-update pass, but some bundles were deferred or require manual review.'
}

$report = [pscustomobject]@{
    generatedAt = (Get-Date).ToString('o')
    mode = $(if ($Preview) { 'preview' } else { 'apply' })
    summaryStatus = $summaryStatus
    summary = $summary
    backupCreated = $backupCreated
    stackHealthy = $stackHealthy
    updated = @($updated)
    deferred = @($deferred)
    manual = @($manual)
    failed = @($failed)
    appWarnings = @($appWarnings)
}

Write-StatusArtifacts -Report $report

Write-Section 'Summary'
Write-Host $summary
Write-Host ("Status page: " + (Join-Path $script:StatusRoot 'index.html'))
Write-Host ("JSON report: " + (Join-Path $script:StatusRoot 'status.json'))
