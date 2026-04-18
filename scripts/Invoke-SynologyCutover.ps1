[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$NasUser = 'harboradmin',
    [string]$NasPassword = 'change_me',
    [switch]$SkipPcStop,
    [switch]$MirrorData,
    [switch]$SkipDataSync
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($NasHost)) {
    $NasHost = 'synology.example.lan'
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$logRoot = Join-Path $repoRoot 'synology-sync-logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

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

$pcContainers = @(
    'gluetun',
    'qbittorrent',
    'port-updater',
    'sabnzbd',
    'gluetun-namespace-guard',
    'download-orchestrator',
    'indexer-guardian',
    'radarr',
    'sonarr',
    'lidarr',
    'bazarr',
    'prowlarr',
    'flaresolverr',
    'plex',
    'pihole',
    'overseerr',
    'clamav',
    'scanner',
    'unpackerr',
    'homepage',
    'update-status',
    'portainer',
    'recyclarr',
    'watchtower',
    'autoheal',
    'cloudflared',
    'tdarr',
    'tdarr-node',
    'immich-server',
    'immich-redis',
    'immich-postgres',
    'immich-machine-learning'
)

function Invoke-NasCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Command
    )

    $commandB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Command))

    $python = @"
import paramiko
import base64
host = r'$NasHost'
user = r'$NasUser'
password = r'$NasPassword'
command = base64.b64decode(r'$commandB64').decode('utf-8')
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
print(err, end='')
client.close()
raise SystemExit(exit_code)
"@

    $python | python -
}

$envMap = Import-DotEnv -Path (Join-Path $repoRoot '.env.synology.local')
$dockerRoot = $envMap['DOCKER_ROOT']

if (-not $SkipPcStop) {
    $running = docker ps --format '{{.Names}}' | Where-Object { $_ -in $pcContainers }
    if ($running) {
        docker stop $running | Out-Null
    }
}

$appdataLog = Join-Path $logRoot 'final-appdata.log'
$stackLog = Join-Path $logRoot 'final-stack.log'

robocopy D:\docker "\\$NasHost\docker\harbor\appdata" /MIR /Z /FFT /R:1 /W:1 /MT:16 /COPY:DAT /DCOPY:DAT `
    /XD D:\docker\plex\transcode D:\docker\tdarr\transcode_cache `
    /XF D:\docker\.env D:\docker\docker-compose.yml D:\docker\docker-compose.yml.bak D:\docker\qbittorrent\config\qBittorrent\ipc-socket `
    /NP /LOG:$appdataLog | Out-Null

robocopy D:\harbor-media-server "\\$NasHost\docker\harbor\stacks\harbor-media-server" /MIR /Z /FFT /R:1 /W:1 /MT:16 /COPY:DAT /DCOPY:DAT `
    /XD D:\harbor-media-server\.git D:\harbor-media-server\backups D:\harbor-media-server\synology-sync-logs D:\harbor-media-server\_backup_20260325_220344 `
    /XF D:\harbor-media-server\.env `
    /NP /LOG:$stackLog | Out-Null

if (-not $SkipDataSync) {
    $deltaArgs = @{
        NasHost = $NasHost
        NasUser = $NasUser
        NasPassword = $NasPassword
    }
    if ($MirrorData) {
        $deltaArgs.Mirror = $true
    }

    & (Join-Path $PSScriptRoot 'Invoke-SynologyDeltaSync.ps1') @deltaArgs | Out-Null

    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -ieq 'robocopy.exe' -and
            $_.CommandLine -match [regex]::Escape("\\$NasHost\")
        } |
        ForEach-Object {
            try {
                Wait-Process -Id $_.ProcessId -ErrorAction Stop
            }
            catch {
                # The robocopy process can exit between enumeration and wait.
                # Treat that as success and continue the cutover.
            }
        }
}

$resetStateCmd = @"
for file in \
  '$dockerRoot/download-orchestrator/runtime-state.json' \
  '$dockerRoot/download-orchestrator/snapshot.json' \
  '$dockerRoot/download-orchestrator/orphan-report.json' \
  '$dockerRoot/download-orchestrator/qbit-preferences.json' \
  '$dockerRoot/download-orchestrator/heartbeat' \
  '$dockerRoot/indexer-guardian/runtime-state.json' \
  '$dockerRoot/indexer-guardian/snapshot.json' \
  '$dockerRoot/indexer-guardian/heartbeat'
do
  rm -f "\$file"
done
"@

Invoke-NasCommand -Command $resetStateCmd

$tunSetupCmd = @'
sudo -S mkdir -p /usr/local/etc/rc.d /dev/net && \
cat <<'EOF' | sudo tee /usr/local/etc/rc.d/S99harbor-tun.sh >/dev/null
#!/bin/sh
case "\$1" in
  start|restart)
    mkdir -p /dev/net
    [ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
    chmod 666 /dev/net/tun
    ;;
  stop)
    ;;
esac
exit 0
EOF
sudo -S chmod 755 /usr/local/etc/rc.d/S99harbor-tun.sh && \
sudo -S /usr/local/etc/rc.d/S99harbor-tun.sh start
'@

Invoke-NasCommand -Command $tunSetupCmd

$piholeRewriteCmd = @"
if [ -f '$dockerRoot/pihole/etc-pihole/pihole.toml' ]; then
  sudo -S sed -i 's/192\\.168\\.1\\.17 pihole\\.lan/$NasHost pihole.lan/g' '$dockerRoot/pihole/etc-pihole/pihole.toml'
fi
"@

Invoke-NasCommand -Command $piholeRewriteCmd

$archiveLegacyRootCmd = @"
mkdir -p '$dockerRoot/boot/legacy-pc-root'
for file in '$dockerRoot/.env' '$dockerRoot/docker-compose.yml' '$dockerRoot/docker-compose.yml.bak'
do
  if [ -f "\$file" ]; then
    mv "\$file" '$dockerRoot/boot/legacy-pc-root/' 2>/dev/null || rm -f "\$file"
  fi
done
"@

Invoke-NasCommand -Command $archiveLegacyRootCmd

$nasWorkdir = '/volume1/docker/harbor/stacks/harbor-media-server'
$composeCmd = @"
cd $nasWorkdir && \
sudo -S /var/packages/ContainerManager/target/usr/bin/docker-compose \
  --env-file .env.synology.local \
  -f docker-compose.synology.private.yml up -d
"@

Invoke-NasCommand -Command $composeCmd

