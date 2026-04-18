[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$MediaDriveLetter = 'M',
    [string]$NodeName = 'PcGpuOverflowNode'
)

$ErrorActionPreference = 'Stop'

$driveName = $MediaDriveLetter.TrimEnd(':')
$driveRoot = "$driveName`:"
$remoteMedia = "\\$NasHost\media"

if (-not (Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue)) {
    New-PSDrive -Name $driveName -PSProvider FileSystem -Root $remoteMedia -Persist | Out-Null
}

$env:TDARR_SERVER_HOST = $NasHost
$env:TDARR_MEDIA_ROOT = $driveRoot
$env:TDARR_NODE_NAME = $NodeName

$nodeConfigPath = 'D:\docker\tdarr\configs\Tdarr_Node_Config.json'
if (Test-Path -LiteralPath $nodeConfigPath) {
    $nodeConfig = Get-Content -LiteralPath $nodeConfigPath -Raw | ConvertFrom-Json
    $nodeConfig.serverURL = "http://$NasHost:8266"
    $nodeConfig.serverIP = '0.0.0.0'
    $nodeConfig.serverPort = '8266'
    $nodeConfig.nodeName = $NodeName
    $nodeConfig.startPaused = $false
    $nodeConfig.nodeType = 'mapped'
    $nodeConfig.pathTranslators = @(
        @{
            server = '/media'
            node = '/media'
        }
    )
    $nodeConfig | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $nodeConfigPath -Encoding utf8
}

docker rm -f tdarr 2>$null | Out-Null
docker compose -f (Join-Path $PSScriptRoot '..\docker-compose.pc-worker.private.yml') up -d tdarr-node

$startupTaskScript = Join-Path $PSScriptRoot 'Install-TdarrPcWorkerStartupTask.ps1'
if (Test-Path -LiteralPath $startupTaskScript) {
    & $startupTaskScript -NasHost $NasHost -MediaDriveLetter $MediaDriveLetter -NodeName $NodeName
}

