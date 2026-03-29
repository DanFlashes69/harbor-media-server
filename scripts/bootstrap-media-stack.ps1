#Requires -Version 5.1
<#
  Harbor Media Server post-launch bootstrap.
  This script configures as much of the stack as possible after the containers
  are running so a new user does not have to hand-link every service.
#>

param(
    [switch]$SkipHomepageRuntime,
    [switch]$SkipProwlarrIndexers
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$EnvPath = Join-Path $RepoRoot '.env'

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

function Get-JsonClone {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)
    process {
        return ($InputObject | ConvertTo-Json -Depth 20 | ConvertFrom-Json)
    }
}

function Wait-ContainerHealthy {
    param(
        [string]$Container,
        [int]$TimeoutSeconds = 300
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $Container 2>$null
        if ($LASTEXITCODE -eq 0 -and ($status -eq 'healthy' -or $status -eq 'running')) {
            return
        }
        Start-Sleep -Seconds 3
    }

    throw "Timed out waiting for container '$Container' to become healthy."
}

function Wait-Http {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds = 300,
        [int[]]$AcceptStatus = @(200, 204, 302, 307, 401)
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 10
            if ($AcceptStatus -contains [int]$response.StatusCode) {
                return
            }
        } catch {
            $resp = $_.Exception.Response
            if ($resp -and ($AcceptStatus -contains [int]$resp.StatusCode)) {
                return
            }
        }
        Start-Sleep -Seconds 3
    }

    throw "Timed out waiting for HTTP endpoint '$Uri'."
}

function Get-ConfigXmlApiKey {
    param([string]$Container)

    $content = docker exec $Container sh -lc "cat /config/config.xml" 2>$null | Out-String
    $match = [regex]::Match($content, '<ApiKey>([^<]+)</ApiKey>')
    if (-not $match.Success) {
        throw "Could not read API key from $Container"
    }

    return $match.Groups[1].Value
}

function Get-SabApiKey {
    param([string]$DockerRoot)

    $iniPath = Join-Path $DockerRoot 'sabnzbd\config\sabnzbd.ini'
    if (-not (Test-Path $iniPath)) {
        throw "SABnzbd config file not found at $iniPath"
    }

    $line = Get-Content $iniPath | Select-String '^\s*api_key\s*=\s*(.+)$' | Select-Object -First 1
    if (-not $line) {
        throw "Could not read SABnzbd API key from $iniPath"
    }

    return $line.Matches[0].Groups[1].Value.Trim()
}

function Invoke-ServarrApi {
    param(
        [string]$Method,
        [string]$BaseUrl,
        [string]$Path,
        [string]$ApiKey,
        $Body = $null
    )

    $headers = @{ 'X-Api-Key' = $ApiKey }
    $uri = "$BaseUrl$Path"

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Headers $headers -Uri $uri -TimeoutSec 30
    }

    $json = $Body | ConvertTo-Json -Depth 20
    return Invoke-RestMethod -Method $Method -Headers $headers -Uri $uri -ContentType 'application/json' -Body $json -TimeoutSec 30
}

function Set-FieldValue {
    param(
        [object]$Field,
        $Value
    )

    if ($Field.PSObject.Properties.Match('value').Count -gt 0) {
        $Field.value = $Value
    } else {
        $Field | Add-Member -NotePropertyName value -NotePropertyValue $Value -Force
    }
}

function Ensure-ServarrDownloadClient {
    param(
        [string]$Name,
        [string]$BaseUrl,
        [string]$ApiPath,
        [string]$ApiKey,
        [string]$Implementation,
        [int]$Priority,
        [bool]$Enabled,
        [hashtable]$FieldValues
    )

    $existing = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path $ApiPath -ApiKey $ApiKey)
    if ($existing | Where-Object { $_.name -eq $Name }) {
        Write-Info "Servarr download client already exists: $Name"
        return
    }

    $schema = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path ($ApiPath + '/schema') -ApiKey $ApiKey)
    $template = $schema | Where-Object { $_.implementation -eq $Implementation } | Select-Object -First 1
    if (-not $template) {
        throw "Could not find schema for Servarr download client '$Implementation'"
    }

    $payload = $template | Get-JsonClone
    $payload.name = $Name
    $payload.enable = $Enabled
    $payload.priority = $Priority

    foreach ($field in $payload.fields) {
        if ($FieldValues.ContainsKey($field.name)) {
            Set-FieldValue -Field $field -Value $FieldValues[$field.name]
        }
    }

    Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path $ApiPath -ApiKey $ApiKey -Body $payload | Out-Null
    Write-Good "Created Servarr download client: $Name"
}

function Ensure-RootFolder {
    param(
        [string]$ServiceName,
        [string]$BaseUrl,
        [string]$ApiPath,
        [string]$ApiKey,
        [string]$Path
    )

    $existing = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path $ApiPath -ApiKey $ApiKey)
    if ($existing | Where-Object { $_.path -eq $Path }) {
        Write-Info "$ServiceName root folder already exists: $Path"
        return
    }

    try {
        Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path $ApiPath -ApiKey $ApiKey -Body @{ path = $Path } | Out-Null
        Write-Good "Created $ServiceName root folder: $Path"
    } catch {
        Write-Warn "Could not create $ServiceName root folder $Path automatically. $_"
    }
}

function Ensure-ProwlarrTag {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Label
    )

    $tags = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/tag' -ApiKey $ApiKey)
    $existing = $tags | Where-Object { $_.label -eq $Label } | Select-Object -First 1
    if ($existing) {
        return $existing.id
    }

    $created = Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path '/api/v1/tag' -ApiKey $ApiKey -Body @{ label = $Label }
    Write-Good "Created Prowlarr tag: $Label"
    return $created.id
}

function Ensure-ProwlarrApplication {
    param(
        [string]$Name,
        [string]$Implementation,
        [bool]$Enabled,
        [string]$SyncLevel,
        [hashtable]$FieldValues,
        [string]$BaseUrl,
        [string]$ApiKey
    )

    $existing = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/applications' -ApiKey $ApiKey)
    if ($existing | Where-Object { $_.name -eq $Name }) {
        Write-Info "Prowlarr application already exists: $Name"
        return
    }

    $schema = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/applications/schema' -ApiKey $ApiKey)
    $template = $schema | Where-Object { $_.implementation -eq $Implementation } | Select-Object -First 1
    if (-not $template) {
        throw "Could not find Prowlarr application schema for '$Implementation'"
    }

    $payload = $template | Get-JsonClone
    $payload.name = $Name
    $payload.enable = $Enabled
    $payload.syncLevel = $SyncLevel

    foreach ($field in $payload.fields) {
        if ($FieldValues.ContainsKey($field.name)) {
            Set-FieldValue -Field $field -Value $FieldValues[$field.name]
        }
    }

    Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path '/api/v1/applications' -ApiKey $ApiKey -Body $payload | Out-Null
    Write-Good "Created Prowlarr application: $Name"
}

function Ensure-ProwlarrDownloadClient {
    param(
        [string]$Name,
        [string]$Implementation,
        [int]$Priority,
        [bool]$Enabled,
        [hashtable]$FieldValues,
        [string]$BaseUrl,
        [string]$ApiKey
    )

    $existing = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/downloadclient' -ApiKey $ApiKey)
    if ($existing | Where-Object { $_.name -eq $Name }) {
        Write-Info "Prowlarr download client already exists: $Name"
        return
    }

    $schema = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/downloadclient/schema' -ApiKey $ApiKey)
    $template = $schema | Where-Object { $_.implementation -eq $Implementation } | Select-Object -First 1
    if (-not $template) {
        throw "Could not find Prowlarr download client schema for '$Implementation'"
    }

    $payload = $template | Get-JsonClone
    $payload.name = $Name
    $payload.enable = $Enabled
    $payload.priority = $Priority

    foreach ($field in $payload.fields) {
        if ($FieldValues.ContainsKey($field.name)) {
            Set-FieldValue -Field $field -Value $FieldValues[$field.name]
        }
    }

    Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path '/api/v1/downloadclient' -ApiKey $ApiKey -Body $payload | Out-Null
    Write-Good "Created Prowlarr download client: $Name"
}

function Ensure-ProwlarrIndexerProxy {
    param(
        [string]$Name,
        [string]$Implementation,
        [bool]$Enabled,
        [hashtable]$FieldValues,
        [int[]]$Tags,
        [string]$BaseUrl,
        [string]$ApiKey
    )

    $existing = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/indexerproxy' -ApiKey $ApiKey)
    if ($existing | Where-Object { $_.implementation -eq $Implementation }) {
        Write-Info "Prowlarr indexer proxy already exists: $Implementation"
        return
    }

    $schema = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/indexerproxy/schema' -ApiKey $ApiKey)
    $template = $schema | Where-Object { $_.implementation -eq $Implementation } | Select-Object -First 1
    if (-not $template) {
        throw "Could not find Prowlarr indexer proxy schema for '$Implementation'"
    }

    $payload = $template | Get-JsonClone
    $payload.name = $Name
    $payload.tags = @($Tags)

    foreach ($field in $payload.fields) {
        if ($FieldValues.ContainsKey($field.name)) {
            Set-FieldValue -Field $field -Value $FieldValues[$field.name]
        }
    }

    Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path '/api/v1/indexerproxy' -ApiKey $ApiKey -Body $payload | Out-Null
    Write-Good "Created Prowlarr indexer proxy: $Name"
}

function Ensure-ProwlarrIndexer {
    param(
        [string]$DefinitionName,
        [int]$Priority,
        [bool]$Enabled,
        [int]$AppProfileId,
        [int[]]$Tags,
        [hashtable]$FieldOverrides,
        [string]$BaseUrl,
        [string]$ApiKey
    )

    $existing = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/indexer' -ApiKey $ApiKey)
    if ($existing | Where-Object { $_.definitionName -eq $DefinitionName }) {
        Write-Info "Prowlarr indexer already exists: $DefinitionName"
        return
    }

    $schema = @(Invoke-ServarrApi -Method Get -BaseUrl $BaseUrl -Path '/api/v1/indexer/schema' -ApiKey $ApiKey)
    $template = $schema | Where-Object { $_.definitionName -eq $DefinitionName } | Select-Object -First 1
    if (-not $template) {
        throw "Could not find Prowlarr indexer schema for '$DefinitionName'"
    }

    $payload = $template | Get-JsonClone
    $payload.enable = $Enabled
    $payload.priority = $Priority
    $payload.appProfileId = $AppProfileId
    $payload.tags = @($Tags)

    foreach ($field in $payload.fields) {
        if ($FieldOverrides.ContainsKey($field.name)) {
            Set-FieldValue -Field $field -Value $FieldOverrides[$field.name]
        }
    }

    Invoke-ServarrApi -Method Post -BaseUrl $BaseUrl -Path '/api/v1/indexer' -ApiKey $ApiKey -Body $payload | Out-Null
    Write-Good "Created Prowlarr indexer: $DefinitionName"
}

function Try-QbLogin {
    param(
        [string]$Username,
        [string]$Password
    )

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    try {
        $response = Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:8081/api/v2/auth/login' -Body @{ username = $Username; password = $Password } -WebSession $session -UseBasicParsing -TimeoutSec 20
        if ($response.Content -match 'Ok\.') {
            return $session
        }
    } catch {
        return $null
    }

    return $null
}

function Get-QbSession {
    param([hashtable]$EnvValues)

    $session = Try-QbLogin -Username $EnvValues.QBIT_USER -Password $EnvValues.QBIT_PASS
    if ($session) {
        return [pscustomobject]@{
            Session = $session
            UsedTemporaryPassword = $false
        }
    }

    $logs = docker logs qbittorrent --tail 200 2>&1 | Out-String
    $match = [regex]::Match($logs, 'temporary password.*?:\s*(\S+)', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $match.Success) {
        throw 'Could not authenticate to qBittorrent with .env credentials or a temporary bootstrap password from container logs.'
    }

    $tempPassword = $match.Groups[1].Value.Trim()
    $tempSession = Try-QbLogin -Username 'admin' -Password $tempPassword
    if (-not $tempSession) {
        throw 'qBittorrent temporary bootstrap password was found in logs, but login still failed.'
    }

    return [pscustomobject]@{
        Session = $tempSession
        UsedTemporaryPassword = $true
    }
}

function Invoke-QbSetPreferences {
    param(
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session,
        [hashtable]$Preferences
    )

    $json = $Preferences | ConvertTo-Json -Compress
    Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:8081/api/v2/app/setPreferences' -Body @{ json = $json } -WebSession $Session -UseBasicParsing -TimeoutSec 20 | Out-Null
}

function Ensure-QbCategory {
    param(
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session,
        [string]$Category
    )

    try {
        Invoke-WebRequest -Method Post -Uri 'http://127.0.0.1:8081/api/v2/torrents/createCategory' -Body @{ category = $Category; savePath = '' } -WebSession $Session -UseBasicParsing -TimeoutSec 20 | Out-Null
    } catch {
        $message = $_.Exception.Message
        $statusCode = $null
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }

        if ($statusCode -ne 409 -and $message -notmatch 'Unable to create category') {
            throw
        }
    }
}

function Set-OrInsert-IniLine {
    param(
        [System.Collections.Generic.List[string]]$Lines,
        [string]$Section,
        [string]$Key,
        [string]$Value
    )

    $sectionHeader = "[$Section]"
    $sectionIndex = $Lines.IndexOf($sectionHeader)
    if ($sectionIndex -lt 0) {
        $Lines.Add($sectionHeader) | Out-Null
        $Lines.Add("$Key=$Value") | Out-Null
        return $true
    }

    $insertAt = $Lines.Count
    for ($i = $sectionIndex + 1; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\[.+\]$') {
            $insertAt = $i
            break
        }

        if ($Lines[$i] -match ('^{0}\s*=' -f [regex]::Escape($Key))) {
            if ($Lines[$i] -ne "$Key=$Value") {
                $Lines[$i] = "$Key=$Value"
                return $true
            }
            return $false
        }
    }

    $Lines.Insert($insertAt, "$Key=$Value")
    return $true
}

function Configure-Qbittorrent {
    param([hashtable]$EnvValues)

    Write-Section 'qBittorrent bootstrap'

    Wait-ContainerHealthy -Container 'gluetun'
    Wait-ContainerHealthy -Container 'qbittorrent'
    Wait-Http -Uri 'http://127.0.0.1:8081/'

    $qbAuth = Get-QbSession -EnvValues $EnvValues

    $preferences = @{
        web_ui_username   = $EnvValues.QBIT_USER
        web_ui_password   = $EnvValues.QBIT_PASS
        save_path         = '/downloads'
        temp_path         = '/downloads/incomplete'
        temp_path_enabled = $true
        random_port       = $false
        upnp              = $false
        queueing_enabled  = $true
    }

    Invoke-QbSetPreferences -Session $qbAuth.Session -Preferences $preferences
    Write-Good 'Applied qBittorrent WebUI and path preferences.'

    foreach ($category in 'radarr', 'sonarr', 'lidarr', 'prowlarr', 'manual') {
        Ensure-QbCategory -Session $qbAuth.Session -Category $category
    }
    Write-Good 'Ensured qBittorrent categories exist.'

    $configPath = Join-Path $EnvValues.DOCKER_ROOT 'qbittorrent\config\qBittorrent\qBittorrent.conf'
    if (-not (Test-Path $configPath)) {
        throw "qBittorrent config file not found at $configPath"
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in Get-Content $configPath) {
        $lines.Add($line) | Out-Null
    }

    $changed = $false
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'BitTorrent' -Key 'Session\Interface' -Value 'tun0') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'BitTorrent' -Key 'Session\InterfaceName' -Value 'tun0') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'Preferences' -Key 'WebUI\Address' -Value '*') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'Preferences' -Key 'WebUI\AuthSubnetWhitelist' -Value '100.64.0.0/10, 172.16.0.0/12, 192.168.0.0/16, 10.0.0.0/8') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'Preferences' -Key 'WebUI\AuthSubnetWhitelistEnabled' -Value 'true') -or $changed

    if ($changed) {
        Set-Content -Path $configPath -Value $lines -Encoding UTF8
        docker restart qbittorrent | Out-Null
        Wait-ContainerHealthy -Container 'qbittorrent'
        Wait-Http -Uri 'http://127.0.0.1:8081/'
        $null = Get-QbSession -EnvValues $EnvValues
        Write-Good 'Patched qBittorrent network interface binding and restarted the container.'
    } else {
        Write-Info 'qBittorrent config file already matched the expected interface binding.'
    }
}

function Configure-Sabnzbd {
    param(
        [hashtable]$EnvValues,
        [string]$ServerHost
    )

    Write-Section 'SABnzbd bootstrap'

    Wait-ContainerHealthy -Container 'sabnzbd'
    Wait-Http -Uri 'http://127.0.0.1:8082/'

    $iniPath = Join-Path $EnvValues.DOCKER_ROOT 'sabnzbd\config\sabnzbd.ini'
    if (-not (Test-Path $iniPath)) {
        throw "SABnzbd config file not found at $iniPath"
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in Get-Content $iniPath) {
        $lines.Add($line) | Out-Null
    }

    $changed = $false
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'download_dir' -Value '/downloads/usenet/incomplete') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'complete_dir' -Value '/downloads/usenet/complete') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'auto_browser' -Value '0') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'direct_unpack' -Value '1') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'fail_hopeless_jobs' -Value '1') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'fast_fail' -Value '1') -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'auto_disconnect' -Value '1') -or $changed

    $hostWhitelist = @('localhost', '127.0.0.1', '::1', 'gluetun')
    if ($ServerHost -and $ServerHost -notin $hostWhitelist) {
        $hostWhitelist += $ServerHost
    }
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'host_whitelist' -Value ($hostWhitelist -join ', ')) -or $changed
    $changed = (Set-OrInsert-IniLine -Lines $lines -Section 'misc' -Key 'local_ranges' -Value '127.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 10.0.0.0/8') -or $changed

    $requiredCategories = @(
        @{ Name = 'radarr';  Dir = 'radarr' },
        @{ Name = 'sonarr';  Dir = 'sonarr' },
        @{ Name = 'lidarr';  Dir = 'lidarr' },
        @{ Name = 'manual';  Dir = 'manual' },
        @{ Name = 'prowlarr'; Dir = 'prowlarr' }
    )

    foreach ($category in $requiredCategories) {
        $sectionMarker = "[[$($category.Name)]]"
        if ($lines -notcontains $sectionMarker) {
            if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -ne '') {
                $lines.Add('') | Out-Null
            }
            $lines.Add($sectionMarker) | Out-Null
            $lines.Add("name = $($category.Name)") | Out-Null
            $lines.Add('order = 0') | Out-Null
            $lines.Add('pp = 3') | Out-Null
            $lines.Add('script = None') | Out-Null
            $lines.Add("dir = $($category.Dir)") | Out-Null
            $lines.Add('newzbin = ""') | Out-Null
            $lines.Add('priority = 0') | Out-Null
            $changed = $true
        }
    }

    if ($changed) {
        Set-Content -Path $iniPath -Value $lines -Encoding UTF8
        docker restart sabnzbd | Out-Null
        Wait-ContainerHealthy -Container 'sabnzbd'
        Wait-Http -Uri 'http://127.0.0.1:8082/'
        Write-Good 'Patched SABnzbd config and restarted the container.'
    } else {
        Write-Info 'SABnzbd config already matched the expected baseline.'
    }
}

function Configure-Servarr {
    param([hashtable]$EnvValues)

    Write-Section 'Servarr bootstrap'

    $sabApiKey = Get-SabApiKey -DockerRoot $EnvValues.DOCKER_ROOT
    $radarrKey = Get-ConfigXmlApiKey -Container 'radarr'
    $sonarrKey = Get-ConfigXmlApiKey -Container 'sonarr'
    $lidarrKey = Get-ConfigXmlApiKey -Container 'lidarr'
    $prowlarrKey = Get-ConfigXmlApiKey -Container 'prowlarr'

    Ensure-RootFolder -ServiceName 'Radarr' -BaseUrl 'http://127.0.0.1:7878' -ApiPath '/api/v3/rootfolder' -ApiKey $radarrKey -Path '/movies'
    Ensure-RootFolder -ServiceName 'Sonarr' -BaseUrl 'http://127.0.0.1:8989' -ApiPath '/api/v3/rootfolder' -ApiKey $sonarrKey -Path '/tv'
    Ensure-RootFolder -ServiceName 'Lidarr' -BaseUrl 'http://127.0.0.1:8686' -ApiPath '/api/v1/rootfolder' -ApiKey $lidarrKey -Path '/music'

    Ensure-ServarrDownloadClient -Name 'qBittorrent' -BaseUrl 'http://127.0.0.1:7878' -ApiPath '/api/v3/downloadclient' -ApiKey $radarrKey -Implementation 'QBittorrent' -Priority 1 -Enabled $true -FieldValues @{
        host                  = 'gluetun'
        port                  = 8081
        useSsl                = $false
        urlBase               = ''
        username              = $EnvValues.QBIT_USER
        password              = $EnvValues.QBIT_PASS
        movieCategory         = 'radarr'
        movieImportedCategory = ''
        recentMoviePriority   = 1
        olderMoviePriority    = 0
        initialState          = 0
        sequentialOrder       = $false
        firstAndLast          = $false
        contentLayout         = 0
    }
    Ensure-ServarrDownloadClient -Name 'SABnzbd' -BaseUrl 'http://127.0.0.1:7878' -ApiPath '/api/v3/downloadclient' -ApiKey $radarrKey -Implementation 'Sabnzbd' -Priority 2 -Enabled $false -FieldValues @{
        host                = 'gluetun'
        port                = 8080
        useSsl              = $false
        urlBase             = ''
        apiKey              = $sabApiKey
        username            = ''
        password            = ''
        movieCategory       = 'radarr'
        recentMoviePriority = -100
        olderMoviePriority  = -100
    }

    Ensure-ServarrDownloadClient -Name 'qBittorrent' -BaseUrl 'http://127.0.0.1:8989' -ApiPath '/api/v3/downloadclient' -ApiKey $sonarrKey -Implementation 'QBittorrent' -Priority 1 -Enabled $true -FieldValues @{
        host               = 'gluetun'
        port               = 8081
        useSsl             = $false
        urlBase            = ''
        username           = $EnvValues.QBIT_USER
        password           = $EnvValues.QBIT_PASS
        tvCategory         = 'sonarr'
        tvImportedCategory = ''
        recentTvPriority   = 1
        olderTvPriority    = 0
        initialState       = 0
        sequentialOrder    = $false
        firstAndLast       = $false
        contentLayout      = 0
    }
    Ensure-ServarrDownloadClient -Name 'SABnzbd' -BaseUrl 'http://127.0.0.1:8989' -ApiPath '/api/v3/downloadclient' -ApiKey $sonarrKey -Implementation 'Sabnzbd' -Priority 2 -Enabled $false -FieldValues @{
        host             = 'gluetun'
        port             = 8080
        useSsl           = $false
        urlBase          = ''
        apiKey           = $sabApiKey
        username         = ''
        password         = ''
        tvCategory       = 'sonarr'
        recentTvPriority = -100
        olderTvPriority  = -100
    }

    Ensure-ServarrDownloadClient -Name 'qBittorrent' -BaseUrl 'http://127.0.0.1:8686' -ApiPath '/api/v1/downloadclient' -ApiKey $lidarrKey -Implementation 'QBittorrent' -Priority 1 -Enabled $true -FieldValues @{
        host                  = 'gluetun'
        port                  = 8081
        useSsl                = $false
        urlBase               = ''
        username              = $EnvValues.QBIT_USER
        password              = $EnvValues.QBIT_PASS
        musicCategory         = 'lidarr'
        musicImportedCategory = ''
        recentMusicPriority   = 0
        olderMusicPriority    = 0
        initialState          = 0
        sequentialOrder       = $false
        firstAndLast          = $false
        contentLayout         = 0
    }
    Ensure-ServarrDownloadClient -Name 'SABnzbd' -BaseUrl 'http://127.0.0.1:8686' -ApiPath '/api/v1/downloadclient' -ApiKey $lidarrKey -Implementation 'Sabnzbd' -Priority 2 -Enabled $false -FieldValues @{
        host                = 'gluetun'
        port                = 8080
        useSsl              = $false
        urlBase             = ''
        apiKey              = $sabApiKey
        username            = ''
        password            = ''
        musicCategory       = 'lidarr'
        recentMusicPriority = -100
        olderMusicPriority  = -100
    }

    $flaresolverrTagId = Ensure-ProwlarrTag -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -Label 'flaresolverr'

    Ensure-ProwlarrApplication -Name 'Radarr' -Implementation 'Radarr' -Enabled $true -SyncLevel 'fullSync' -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -FieldValues @{
        prowlarrUrl = 'http://prowlarr:9696'
        baseUrl = 'http://radarr:7878'
        apiKey = $radarrKey
        syncCategories = @(2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060, 2070, 2080, 2090)
        syncRejectBlocklistedTorrentHashesWhileGrabbing = $false
    }
    Ensure-ProwlarrApplication -Name 'Sonarr' -Implementation 'Sonarr' -Enabled $true -SyncLevel 'fullSync' -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -FieldValues @{
        prowlarrUrl = 'http://prowlarr:9696'
        baseUrl = 'http://sonarr:8989'
        apiKey = $sonarrKey
        syncCategories = @(5000, 5010, 5020, 5030, 5040, 5045, 5050, 5090)
        animeSyncCategories = @(5070)
        syncAnimeStandardFormatSearch = $true
        syncRejectBlocklistedTorrentHashesWhileGrabbing = $false
    }
    Ensure-ProwlarrApplication -Name 'Lidarr' -Implementation 'Lidarr' -Enabled $true -SyncLevel 'fullSync' -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -FieldValues @{
        prowlarrUrl = 'http://prowlarr:9696'
        baseUrl = 'http://lidarr:8686'
        apiKey = $lidarrKey
        syncCategories = @(3000, 3010, 3030, 3040, 3050, 3060)
        syncRejectBlocklistedTorrentHashesWhileGrabbing = $false
    }

    Ensure-ProwlarrDownloadClient -Name 'qBittorrent' -Implementation 'QBittorrent' -Priority 1 -Enabled $true -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -FieldValues @{
        host = 'gluetun'
        port = 8081
        useSsl = $false
        urlBase = ''
        username = $EnvValues.QBIT_USER
        password = $EnvValues.QBIT_PASS
        category = 'prowlarr'
        priority = 0
        initialState = 0
        sequentialOrder = $false
        firstAndLast = $false
        contentLayout = 0
    }
    Ensure-ProwlarrDownloadClient -Name 'SABnzbd' -Implementation 'Sabnzbd' -Priority 2 -Enabled $false -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -FieldValues @{
        host = 'gluetun'
        port = 8080
        useSsl = $false
        urlBase = ''
        apiKey = $sabApiKey
        username = ''
        password = ''
        category = 'prowlarr'
        priority = -100
    }

    Ensure-ProwlarrIndexerProxy -Name 'FlareSolverr' -Implementation 'FlareSolverr' -Enabled $true -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey -Tags @($flaresolverrTagId) -FieldValues @{
        host = 'http://flaresolverr:8191/'
        requestTimeout = 60
    }

    if (-not $SkipProwlarrIndexers) {
        $indexers = @(
            @{ Definition = '1337x';        Priority = 10; Tags = @($flaresolverrTagId); Fields = @{ 'torrentBaseSettings.appMinimumSeeders' = 5; 'downloadlink' = 0; 'downloadlink2' = 1; 'sort' = 2; 'type' = 1 } },
            @{ Definition = 'eztv';         Priority = 15; Tags = @($flaresolverrTagId); Fields = @{ 'torrentBaseSettings.appMinimumSeeders' = 5 } },
            @{ Definition = 'limetorrents'; Priority = 20; Tags = @(); Fields = @{ 'torrentBaseSettings.appMinimumSeeders' = 5; 'downloadlink' = 1; 'downloadlink2' = 0; 'sort' = 0 } },
            @{ Definition = 'nyaasi';       Priority = 25; Tags = @(); Fields = @{ 'torrentBaseSettings.appMinimumSeeders' = 5; 'prefer_magnet_links' = $true } },
            @{ Definition = 'thepiratebay'; Priority = 35; Tags = @(); Fields = @{ 'torrentBaseSettings.appMinimumSeeders' = 5; 'apiurl' = 'apibay.org' } },
            @{ Definition = 'yts';          Priority = 40; Tags = @(); Fields = @{ 'apiurl' = 'movies-api.accel.li' } }
        )

        foreach ($indexer in $indexers) {
            Ensure-ProwlarrIndexer -DefinitionName $indexer.Definition -Priority $indexer.Priority -Enabled $true -AppProfileId 1 -Tags $indexer.Tags -FieldOverrides $indexer.Fields -BaseUrl 'http://127.0.0.1:9696' -ApiKey $prowlarrKey
        }
    } else {
        Write-Warn 'Skipping default Prowlarr public indexer pack.'
    }
}

function Update-RecyclarrRuntimeConfig {
    param([hashtable]$EnvValues)

    Write-Section 'Recyclarr runtime config'

    $runtimePath = Join-Path $EnvValues.DOCKER_ROOT 'recyclarr\config\recyclarr.yml'
    if (-not (Test-Path $runtimePath)) {
        Write-Warn "Recyclarr runtime config not found at $runtimePath"
        return
    }

    $radarrKey = Get-ConfigXmlApiKey -Container 'radarr'
    $sonarrKey = Get-ConfigXmlApiKey -Container 'sonarr'

    $content = Get-Content -Raw $runtimePath
    $content = $content.Replace('YOUR_RADARR_API_KEY', $radarrKey)
    $content = $content.Replace('YOUR_SONARR_API_KEY', $sonarrKey)
    Set-Content -Path $runtimePath -Value $content -Encoding UTF8
    Write-Good 'Updated runtime Recyclarr config with current API keys.'
}

function Write-HomepageRuntimeConfig {
    param(
        [hashtable]$EnvValues,
        [string]$ServerHost
    )

    if ($SkipHomepageRuntime) {
        Write-Warn 'Skipping Homepage runtime config generation.'
        return
    }

    Write-Section 'Homepage runtime config'

    $runtimePath = Join-Path $EnvValues.DOCKER_ROOT 'homepage\config\services.yaml'
    $radarrKey = Get-ConfigXmlApiKey -Container 'radarr'
    $sonarrKey = Get-ConfigXmlApiKey -Container 'sonarr'
    $lidarrKey = Get-ConfigXmlApiKey -Container 'lidarr'
    $prowlarrKey = Get-ConfigXmlApiKey -Container 'prowlarr'

    $content = @"
---
- Media:
    - Plex:
        icon: plex.svg
        href: http://$ServerHost:32400/web
        description: Media streaming server
    - Radarr:
        icon: radarr.svg
        href: http://$ServerHost:7878
        description: Movie management
        widget:
          type: radarr
          url: http://radarr:7878
          key: $radarrKey
    - Sonarr:
        icon: sonarr.svg
        href: http://$ServerHost:8989
        description: TV show management
        widget:
          type: sonarr
          url: http://sonarr:8989
          key: $sonarrKey
    - Lidarr:
        icon: lidarr.svg
        href: http://$ServerHost:8686
        description: Music management
        widget:
          type: lidarr
          url: http://lidarr:8686
          key: $lidarrKey
- Downloads:
    - qBittorrent:
        icon: qbittorrent.svg
        href: http://$ServerHost:8081
        description: Torrent client (VPN protected)
        widget:
          type: qbittorrent
          url: http://gluetun:8081
          username: $($EnvValues.QBIT_USER)
          password: $($EnvValues.QBIT_PASS)
    - SABnzbd:
        icon: sabnzbd.svg
        href: http://$ServerHost:8082
        description: Usenet client (VPN protected)
    - Prowlarr:
        icon: prowlarr.svg
        href: http://$ServerHost:9696
        description: Indexer manager
        widget:
          type: prowlarr
          url: http://prowlarr:9696
          key: $prowlarrKey
    - Overseerr:
        icon: overseerr.svg
        href: http://$ServerHost:5055
        description: Media requests
- Photos & Management:
    - Immich:
        icon: immich.svg
        href: http://$ServerHost:2283
        description: Photo & video management
    - Bazarr:
        icon: bazarr.svg
        href: http://$ServerHost:6767
        description: Subtitle downloads
    - Portainer:
        icon: portainer.svg
        href: http://$ServerHost:9000
        description: Docker management
    - Pi-hole:
        icon: pi-hole.svg
        href: http://$ServerHost:8080/admin
        description: Network ad blocker
        widget:
          type: pihole
          url: http://pihole:80
          key: $($EnvValues.PIHOLE_PASSWORD)
          version: 6
- Optimization:
    - Tdarr:
        icon: mdi-video-converter
        href: http://$ServerHost:8265
        description: Media transcoding
        widget:
          type: tdarr
          url: http://tdarr:8265
"@

    Set-Content -Path $runtimePath -Value $content -Encoding UTF8
    docker restart homepage | Out-Null
    Wait-ContainerHealthy -Container 'homepage'
    Write-Good 'Generated runtime Homepage services.yaml and restarted Homepage.'
}

function Show-ManualRemainders {
    Write-Section 'Still manual by design'
    Write-Host 'The repo and bootstrap now handle the bulk of the stack wiring.' -ForegroundColor Gray
    Write-Host 'These are still intentionally left to the operator or an autonomous browser agent:' -ForegroundColor Gray
    Write-Host '  - Add your OpenVPN .ovpn file to DOCKER_ROOT\gluetun\custom.ovpn'
    Write-Host '  - Complete Plex web onboarding / claim and create libraries if this is the first launch'
    Write-Host '  - Complete Overseerr first admin login and connect Plex if this is the first launch'
    Write-Host '  - Add private trackers or authenticated indexers in Prowlarr'
    Write-Host '  - Add a real Usenet provider and NZB indexers if you want SABnzbd to download jobs'
    Write-Host '  - Add API-token-only Homepage widgets such as Plex, Immich, Portainer, and Overseerr if you want them'
    Write-Host '  - Configure Cloudflare Tunnel and domain routing if you want public Plex remote access'
    Write-Host ''
    Write-Host 'See docs\SETUP.md, docs\SERVICE-SETUP.md, and docs\AI-SETUP.md for the full guided flow.' -ForegroundColor DarkGray
}

$envValues = Import-EnvFile -Path $EnvPath
$serverHost = if ($envValues.ContainsKey('SERVER_HOST') -and -not [string]::IsNullOrWhiteSpace($envValues.SERVER_HOST)) { $envValues.SERVER_HOST } else { 'localhost' }

Write-Host 'Harbor Media Server post-launch bootstrap' -ForegroundColor Magenta
Write-Host 'Repository root:' $RepoRoot -ForegroundColor DarkGray

Configure-Qbittorrent -EnvValues $envValues
Configure-Sabnzbd -EnvValues $envValues -ServerHost $serverHost
Configure-Servarr -EnvValues $envValues
Update-RecyclarrRuntimeConfig -EnvValues $envValues
Write-HomepageRuntimeConfig -EnvValues $envValues -ServerHost $serverHost
Show-ManualRemainders

Write-Good 'Bootstrap complete.'
