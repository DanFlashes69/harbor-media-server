[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$NasUser = 'harboradmin',
    [string]$NasPassword = 'change_me'
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($NasHost)) {
    $NasHost = 'synology.example.lan'
}

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
import paramiko
import base64
host = r'''$NasHost'''
user = r'''$NasUser'''
password = r'''$NasPassword'''
command = "export HOME=/tmp; " + base64.b64decode(r'''$commandB64''').decode('utf-8')
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=host, username=user, password=password, timeout=20)
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

function Invoke-HttpCheck {
    param(
        [string]$Name,
        [string]$Url
    )

    $tempPath = [System.IO.Path]::GetTempFileName()
    try {
        $curlOutput = & curl.exe --http1.1 -sS -L -m 40 $Url -o $tempPath -w "HTTP_CODE=%{http_code}"
        $status = $null
        if ($curlOutput -match 'HTTP_CODE=(\d{3})') {
            $status = [int]$Matches[1]
        }

        [pscustomobject]@{
            Category = 'http'
            Name = $Name
            Ok = ($status -ge 200 -and $status -lt 400)
            Detail = if ($status) { [string]$status } else { 'no-status' }
        }
    }
    catch {
        [pscustomobject]@{
            Category = 'http'
            Name = $Name
            Ok = $false
            Detail = $_.Exception.Message
        }
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
                return Invoke-RestMethod -Uri $Uri -Headers $Headers -WebSession $WebSession -TimeoutSec 20
            }

            return Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 20
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

function Test-ClientHostPort {
    param(
        [object]$Clients,
        [string]$ExpectedHost,
        [int]$ExpectedPort
    )

    foreach ($client in @($Clients)) {
        $fieldMap = @{}
        foreach ($field in @($client.fields)) {
            $fieldMap[$field.name] = $field.value
        }

        if ($fieldMap['host'] -eq $ExpectedHost -and [int]$fieldMap['port'] -eq $ExpectedPort) {
            return $true
        }
    }

    return $false
}

$envMap = Import-DotEnv -Path (Join-Path ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))) '.env.synology.local')
$dockerBin = '/var/packages/ContainerManager/target/usr/bin/docker'
$dockerRoot = $envMap['DOCKER_ROOT']
$results = New-Object System.Collections.Generic.List[object]

$httpChecks = @(
    @{ Name = 'Homepage'; Url = "http://${NasHost}:3000" },
    @{ Name = 'Radarr'; Url = "http://${NasHost}:7878/ping" },
    @{ Name = 'Sonarr'; Url = "http://${NasHost}:8989/ping" },
    @{ Name = 'Lidarr'; Url = "http://${NasHost}:8686/ping" },
    @{ Name = 'Bazarr'; Url = "http://${NasHost}:6767" },
    @{ Name = 'Prowlarr'; Url = "http://${NasHost}:9696/ping" },
    @{ Name = 'Overseerr'; Url = "http://${NasHost}:5055/login" },
    @{ Name = 'Plex'; Url = "http://${NasHost}:32401/identity" },
    @{ Name = 'Immich'; Url = "http://${NasHost}:2283/api/server/ping" },
    @{ Name = 'Tdarr'; Url = "http://${NasHost}:8265" },
    @{ Name = 'Pi-hole'; Url = "http://${NasHost}:9080/admin/login" },
    @{ Name = 'qBittorrent'; Url = "http://${NasHost}:8081" },
    @{ Name = 'SABnzbd'; Url = "http://${NasHost}:8082/wizard/" },
    @{ Name = 'UpdateStatus'; Url = "http://${NasHost}:8099" }
)

foreach ($check in $httpChecks) {
    $results.Add((Invoke-HttpCheck -Name $check.Name -Url $check.Url))
}

try {
    $dockerPs = Invoke-NasCommand -Command "sudo -S $dockerBin ps --format '{{.Names}}|{{.Status}}'"
    $runningContainers = @{}
    foreach ($line in ($dockerPs -split "`r?`n" | Where-Object { $_ })) {
        $parts = $line -split '\|', 2
        if ($parts.Count -ne 2) {
            continue
        }

        $status = $parts[1]
        $runningContainers[$parts[0]] = $status
        $results.Add([pscustomobject]@{
            Category = 'docker'
            Name = $parts[0]
            Ok = ($status -match 'Up')
            Detail = $status
        })
    }

    $requiredRunningContainers = @(
        'download-orchestrator', 'gluetun', 'qbittorrent', 'sabnzbd', 'clamav', 'scanner',
        'homepage', 'overseerr', 'prowlarr', 'radarr', 'sonarr', 'lidarr', 'bazarr', 'plex'
    )
    foreach ($requiredContainer in $requiredRunningContainers) {
        if (-not $runningContainers.ContainsKey($requiredContainer)) {
            $results.Add([pscustomobject]@{
                Category = 'docker'
                Name = $requiredContainer
                Ok = $false
                Detail = 'missing from docker ps'
            })
        }
    }
}
catch {
    $results.Add([pscustomobject]@{
        Category = 'docker'
        Name = 'docker-ps'
        Ok = $false
        Detail = $_.Exception.Message
    })
}

try {
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $loginResponse = Invoke-WebRequest -Uri "http://${NasHost}:8081/api/v2/auth/login" -Method Post -Body @{
        username = $envMap['QBIT_USER']
        password = $envMap['QBIT_PASS']
    } -WebSession $session -TimeoutSec 20 -UseBasicParsing

    $prefs = Invoke-RestMethod -Uri "http://${NasHost}:8081/api/v2/app/preferences" -WebSession $session -TimeoutSec 20
    $transfer = Invoke-RestMethod -Uri "http://${NasHost}:8081/api/v2/transfer/info" -WebSession $session -TimeoutSec 20
    $forwardedPort = ((Invoke-NasCommand -Command "cat '$dockerRoot/gluetun-port/forwarded_port'").Trim() -replace '[^\d]', '')
    $portAligned = ([string]$prefs.listen_port -eq [string]$forwardedPort)

    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'auth'
        Ok = ($loginResponse.Content -match 'Ok')
        Detail = 'authenticated'
    })
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'listen-port'
        Ok = $portAligned
        Detail = "qB=$($prefs.listen_port) gluetun=$forwardedPort"
    })
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'interface'
        Ok = ($prefs.current_network_interface -eq 'tun0')
        Detail = [string]$prefs.current_network_interface
    })
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'transfer'
        Ok = $true
        Detail = "dl=$($transfer.dl_info_speed) up=$($transfer.up_info_speed)"
    })
}
catch {
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'api'
        Ok = $false
        Detail = $_.Exception.Message
    })
}

try {
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'save-path'
        Ok = ($prefs.save_path.TrimEnd('/') -eq '/downloads')
        Detail = [string]$prefs.save_path
    })
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'temp-path'
        Ok = ($prefs.temp_path.TrimEnd('/') -eq '/downloads/incomplete')
        Detail = [string]$prefs.temp_path
    })
}
catch {
    $results.Add([pscustomobject]@{
        Category = 'qbit'
        Name = 'paths'
        Ok = $false
        Detail = $_.Exception.Message
    })
}

try {
    $radarrHeaders = @{ 'X-Api-Key' = $envMap['RADARR_API_KEY'] }
    $sonarrHeaders = @{ 'X-Api-Key' = $envMap['SONARR_API_KEY'] }
    $lidarrHeaders = @{ 'X-Api-Key' = $envMap['LIDARR_API_KEY'] }
    $prowlarrHeaders = @{ 'X-Api-Key' = $envMap['PROWLARR_API_KEY'] }

    $radarrRoots = Invoke-RestWithRetry -Uri "http://${NasHost}:7878/api/v3/rootfolder" -Headers $radarrHeaders
    $sonarrRoots = Invoke-RestWithRetry -Uri "http://${NasHost}:8989/api/v3/rootfolder" -Headers $sonarrHeaders
    $lidarrRoots = Invoke-RestWithRetry -Uri "http://${NasHost}:8686/api/v1/rootfolder" -Headers $lidarrHeaders

    $radarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:7878/api/v3/downloadclient" -Headers $radarrHeaders
    $sonarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:8989/api/v3/downloadclient" -Headers $sonarrHeaders
    $lidarrClients = Invoke-RestWithRetry -Uri "http://${NasHost}:8686/api/v1/downloadclient" -Headers $lidarrHeaders

    $prowlarrApps = Invoke-RestWithRetry -Uri "http://${NasHost}:9696/api/v1/applications" -Headers $prowlarrHeaders
    $homepageJson = & curl.exe --http1.1 -sS -L -m 25 "http://${NasHost}:3000/api/services"

    $prowlarrAppJson = $prowlarrApps | ConvertTo-Json -Depth 12

    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'radarr-root'
        Ok = (@($radarrRoots.path) -contains '/movies')
        Detail = ((@($radarrRoots.path)) -join ', ')
    })
    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'sonarr-root'
        Ok = (@($sonarrRoots.path) -contains '/tv')
        Detail = ((@($sonarrRoots.path)) -join ', ')
    })
    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'lidarr-root'
        Ok = (@($lidarrRoots.path) -contains '/music')
        Detail = ((@($lidarrRoots.path)) -join ', ')
    })

    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'radarr-download-client'
        Ok = (Test-ClientHostPort -Clients $radarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081)
        Detail = 'expects gluetun:8081'
    })
    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'sonarr-download-client'
        Ok = (Test-ClientHostPort -Clients $sonarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081)
        Detail = 'expects gluetun:8081'
    })
    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'lidarr-download-client'
        Ok = (Test-ClientHostPort -Clients $lidarrClients -ExpectedHost 'gluetun' -ExpectedPort 8081)
        Detail = 'expects gluetun:8081'
    })

    $results.Add([pscustomobject]@{
        Category = 'prowlarr'
        Name = 'app-targets'
        Ok = ($prowlarrAppJson -match 'http://radarr:7878' -and $prowlarrAppJson -match 'http://sonarr:8989' -and $prowlarrAppJson -match 'http://lidarr:8686')
        Detail = 'expects radarr/sonarr/lidarr internal URLs'
    })

    $results.Add([pscustomobject]@{
        Category = 'homepage'
        Name = 'nas-links'
        Ok = ($homepageJson -match 'http://localhost:32400/web' -and
              $homepageJson -match 'http://localhost:5055' -and
              $homepageJson -match 'http://localhost:2283' -and
              $homepageJson -match 'http://localhost:7878' -and
              $homepageJson -match 'http://localhost:8989' -and
              $homepageJson -match 'http://localhost:8686' -and
              $homepageJson -match 'http://localhost:9696' -and
              $homepageJson -match 'http://localhost:8081' -and
              $homepageJson -match 'http://localhost:8082' -and
              $homepageJson -match 'http://localhost:8265' -and
              ($homepageJson -match 'http://127\.0\.0\.1:9080/admin/' -or $homepageJson -match 'http://localhost:9080/admin/'))
        Detail = 'core Harbor links should point to the localhost bridge'
    })
    $results.Add([pscustomobject]@{
        Category = 'homepage'
        Name = 'immich-link'
        Ok = ($homepageJson -match 'http://immich-server:2283' -and $homepageJson -match 'http://localhost:2283')
        Detail = 'Immich should stay NAS-local and bridge through localhost'
    })
}
catch {
    $results.Add([pscustomobject]@{
        Category = 'arr'
        Name = 'api-wiring'
        Ok = $false
        Detail = $_.Exception.Message
    })
}

$heartbeatChecks = @(
    @{ Name = 'download-orchestrator'; Path = "$dockerRoot/download-orchestrator/heartbeat" },
    @{ Name = 'indexer-guardian'; Path = "$dockerRoot/indexer-guardian/heartbeat" }
)

foreach ($check in $heartbeatChecks) {
    try {
        $heartbeat = Invoke-NasCommand -Command "test -f '$($check.Path)' && echo ok || echo missing"
        $results.Add([pscustomobject]@{
            Category = 'heartbeat'
            Name = $check.Name
            Ok = ($heartbeat.Trim() -eq 'ok')
            Detail = $heartbeat.Trim()
        })
    }
    catch {
        $results.Add([pscustomobject]@{
            Category = 'heartbeat'
            Name = $check.Name
            Ok = $false
            Detail = $_.Exception.Message
        })
    }
}

$results

