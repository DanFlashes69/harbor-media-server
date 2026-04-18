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

function Invoke-NasCommand {
    param([string]$Command)

    $commandB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Command))

    $python = @"
import paramiko
import base64
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

$bootScript = @'
#!/bin/sh

DOCKER=/var/packages/ContainerManager/target/usr/bin/docker
STARTER=/volume1/docker/harbor/bin/harbor-staged-start.sh
WATCHDOG_RC=/usr/local/etc/rc.d/S99harbor-watchdog.sh
LOG=/volume1/docker/harbor/appdata/boot/harbor-staged-start.log

case "$1" in
  start|restart)
    mkdir -p /volume1/docker/harbor/appdata/boot
    (
      export HOME=/tmp
      log_dir="/volume1/docker/harbor/appdata/boot"
      lock_root="/volume1/docker/harbor/appdata/update-guardian/locks"

      mkdir -p /volume1/@fake_home_link/harboradmin /dev/net "$log_dir"
      chown harboradmin:users /var/services/homes/harboradmin 2>/dev/null || true
      [ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
      chmod 666 /dev/net/tun

      /usr/syno/bin/synopkg stop SynoFinder >/dev/null 2>&1 || true
      /usr/syno/bin/synopkg start ContainerManager >/dev/null 2>&1 || true

      tries=0
      until $DOCKER info >/dev/null 2>&1; do
        tries=$((tries + 1))
        if [ $tries -ge 60 ]; then
          exit 1
        fi
        sleep 5
      done

      mkdir -p "$lock_root"
      rm -rf "$lock_root/harbor-staged-start.lock" >/dev/null 2>&1 || true
      if [ -f "$lock_root/harbor-watchdog.pid" ]; then
        kill "$(cat "$lock_root/harbor-watchdog.pid")" 2>/dev/null || true
        rm -f "$lock_root/harbor-watchdog.pid"
      fi

      START_SCOPE=full START_OPTIONAL=1 ENABLE_SAB=1 sh "$STARTER"
      sh "$WATCHDOG_RC" restart >/dev/null 2>&1 || true
    ) >>"$LOG" 2>&1 &
    ;;
  stop)
    sh "$WATCHDOG_RC" stop >/dev/null 2>&1 || true
    ;;
esac

exit 0
'@

$watchdogScriptPath = Join-Path $PSScriptRoot 'S99harbor-watchdog.sh'
$watchdogScript = Get-Content -LiteralPath $watchdogScriptPath -Raw

$installCmd = @"
sudo -S mkdir -p /usr/local/etc/rc.d && \
sudo -S mkdir -p /volume1/@fake_home_link/harboradmin && \
sudo -S chown harboradmin:users /var/services/homes/harboradmin && \
cat <<'EOF' | sudo -S tee /usr/local/etc/rc.d/S99harbor-stack.sh >/dev/null
$bootScript
EOF
sudo -S chmod 755 /usr/local/etc/rc.d/S99harbor-stack.sh && \
cat <<'EOF' | sudo -S tee /usr/local/etc/rc.d/S99harbor-watchdog.sh >/dev/null
$watchdogScript
EOF
sudo -S chmod 755 /usr/local/etc/rc.d/S99harbor-watchdog.sh
"@

Invoke-NasCommand -Command $installCmd

