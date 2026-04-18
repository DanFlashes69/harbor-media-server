#!/bin/sh
set -eu
DOCKER=/var/packages/ContainerManager/target/usr/bin/docker
STARTER=/volume1/docker/harbor/bin/harbor-staged-start.sh
LOCKROOT=/volume1/docker/harbor/appdata/update-guardian/locks
PIDFILE=$LOCKROOT/harbor-watchdog.pid
LOG=/volume1/docker/harbor/appdata/update-guardian/status/harbor-watchdog.log
LOCKDIR=$LOCKROOT/harbor-staged-start.lock
mkdir -p "$(dirname "$LOG")" "$LOCKROOT"
log(){ printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
is_running(){
  status=$($DOCKER inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo missing)
  [ "$status" = "running" ]
}
invoke_scope(){
  scope="$1"
  log "Invoking staged startup scope: $scope"
  START_SCOPE="$scope" ENABLE_SAB="${ENABLE_SAB:-1}" sh "$STARTER" || log "Staged startup scope failed: $scope"
}
while true; do
  if ! $DOCKER version >/dev/null 2>&1; then
    log 'Docker unavailable, attempting package start.'
    /usr/syno/bin/synopkg start ContainerManager >/dev/null 2>&1 || true
    sleep 20
  fi
  if $DOCKER version >/dev/null 2>&1; then
    if [ -d "$LOCKDIR" ]; then
      sleep 30
      continue
    fi
    if ! is_running homepage || ! is_running pihole || ! is_running update-status || ! is_running portainer; then
      invoke_scope frontdoor
      sleep 45
      continue
    fi
    if ! is_running radarr || ! is_running sonarr || ! is_running lidarr || ! is_running bazarr || ! is_running prowlarr || ! is_running overseerr; then
      invoke_scope arr
      sleep 60
      continue
    fi
    if ! is_running gluetun || ! is_running qbittorrent || ! is_running port-updater || ! is_running gluetun-namespace-guard; then
      invoke_scope downloader
      sleep 60
      continue
    fi
    if ! is_running plex || ! is_running tdarr || ! is_running cloudflared; then
      invoke_scope media
      sleep 60
      continue
    fi
    if ! is_running immich-postgres || ! is_running immich-redis || ! is_running immich-machine-learning || ! is_running immich-server; then
      invoke_scope photos
      sleep 60
      continue
    fi
    if ! is_running unpackerr || ! is_running download-orchestrator || ! is_running indexer-guardian || ! is_running recyclarr || ! is_running autoheal; then
      invoke_scope automation
      sleep 60
      continue
    fi
    if ! is_running clamav || ! is_running scanner; then
      invoke_scope security
      sleep 60
      continue
    fi
    if ! is_running watchtower; then
      invoke_scope optional
      sleep 60
      continue
    fi
  fi
  sleep 120
done
