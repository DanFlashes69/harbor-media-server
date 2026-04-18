[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan'
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($NasHost)) {
    $NasHost = 'synology.example.lan'
}

$checks = @(
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

function Invoke-HttpCheck {
    param(
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

        [pscustomobject]@{
            Name = $Name
            Url = $Url
            StatusCode = $statusCode
            Ok = ($statusCode -ge 200 -and $statusCode -lt 400)
        }
    }
    catch {
        [pscustomobject]@{
            Name = $Name
            Url = $Url
            StatusCode = $null
            Ok = $false
        }
    }
    finally {
        Remove-Item -LiteralPath $tempPath -ErrorAction SilentlyContinue
    }
}

$results = foreach ($check in $checks) {
    try {
        Invoke-HttpCheck -Name $check.Name -Url $check.Url
    }
    catch {
        [pscustomobject]@{
            Name = $check.Name
            Url = $check.Url
            StatusCode = $null
            Ok = $false
        }
    }    
}

$results

