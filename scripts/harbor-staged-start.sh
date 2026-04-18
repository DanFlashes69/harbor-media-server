#!/bin/sh
set -eu
STACK_DIR=/volume1/docker/harbor/stacks/harbor-media-server
ENV_FILE="$STACK_DIR/.env.synology.local"
ENV_LINK="$STACK_DIR/.env"
COMPOSE_FILE="$STACK_DIR/docker-compose.synology.private.yml"
DOCKER=/var/packages/ContainerManager/target/usr/bin/docker
COMPOSE_BIN=/var/packages/ContainerManager/target/usr/bin/docker-compose
START_OPTIONAL="${START_OPTIONAL:-1}"
START_SCOPE="${START_SCOPE:-full}"
ENABLE_SAB="${ENABLE_SAB:-1}"
DOWNLOADER_BASE_WAIT_SECONDS="${DOWNLOADER_BASE_WAIT_SECONDS:-180}"
DOWNLOADER_CLIENT_WAIT_SECONDS="${DOWNLOADER_CLIENT_WAIT_SECONDS:-180}"
if [ -x "$COMPOSE_BIN" ]; then
  COMPOSE="$COMPOSE_BIN --env-file $ENV_FILE -f $COMPOSE_FILE"
else
  COMPOSE="$DOCKER compose --env-file $ENV_FILE -f $COMPOSE_FILE"
fi
LOG=/volume1/docker/harbor/appdata/update-guardian/status/harbor-startup.log
LOCKROOT=/volume1/docker/harbor/appdata/update-guardian/locks
LOCKDIR="$LOCKROOT/harbor-staged-start.lock"
PIDFILE="$LOCKDIR/pid"
mkdir -p "$(dirname "$LOG")" "$LOCKROOT"
log(){ printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
claim_lock(){
  if mkdir "$LOCKDIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$PIDFILE"
    return 0
  fi

  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      log "Another staged startup is already running (pid=$pid). Exiting."
      return 1
    fi
  fi

  log 'Found stale staged-start lock. Removing it.'
  rm -rf "$LOCKDIR" >/dev/null 2>&1 || true
  mkdir "$LOCKDIR" 2>/dev/null || {
    log 'Unable to claim staged-start lock after stale-lock cleanup.'
    return 1
  }
  printf '%s\n' "$$" > "$PIDFILE"
  return 0
}
cleanup_lock(){
  rm -f "$PIDFILE" >/dev/null 2>&1 || true
  rmdir "$LOCKDIR" >/dev/null 2>&1 || true
}
claim_lock || exit 0
trap 'cleanup_lock' EXIT INT TERM
ensure_docker(){
  if ! $DOCKER version >/dev/null 2>&1; then
    /usr/syno/bin/synopkg start ContainerManager >/dev/null 2>&1 || true
    i=0
    while [ $i -lt 60 ]; do
      if $DOCKER version >/dev/null 2>&1; then return 0; fi
      sleep 2; i=$((i+1))
    done
    log 'Docker daemon failed to become ready.'
    return 1
  fi
}
prepare_env(){ [ -f "$ENV_FILE" ] && cp -f "$ENV_FILE" "$ENV_LINK"; }
# Preserve the restart policy declared in compose. A previous version mutated
# healthy services to restart=no during staged bring-up, which made reboot
# recovery brittle on the NAS.
set_restart_no(){ :; }
container_state(){
  $DOCKER inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo missing
}
container_status(){
  $DOCKER inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo missing
}
container_oom_killed(){
  $DOCKER inspect --format '{{.State.OOMKilled}}' "$1" 2>/dev/null || echo false
}
is_service_ready(){
  state="$(container_state "$1")"
  status="${state%%|*}"
  health="${state##*|}"
  [ "$status" = "running" ] || return 1
  [ "$health" = "healthy" ] || [ "$health" = "none" ]
}
remove_stale_service(){
  svc="$1"
  status="$(container_status "$svc")"
  case "$status" in
    missing|running) return 0 ;;
    exited|dead|created|restarting)
      log "Removing stale container before startup: $svc (status=$status oom_killed=$(container_oom_killed "$svc"))"
      $DOCKER rm -f "$svc" >/dev/null 2>&1 || true
      return 0
      ;;
  esac
}
recreate_if_needed(){
  for svc in "$@"; do
    remove_stale_service "$svc"
    if is_service_ready "$svc"; then
      continue
    fi
    $DOCKER rm -f "$svc" >/dev/null 2>&1 || true
  done
}
health_of(){
  $DOCKER inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || echo missing
}
wait_wave(){
  timeout="$1"; shift
  elapsed=0
  while [ $elapsed -lt "$timeout" ]; do
    ok=1
    for svc in "$@"; do
      state=$(health_of "$svc")
      case "$state" in
        healthy|running) : ;;
        *) ok=0; break ;;
      esac
    done
    [ $ok -eq 1 ] && return 0
    sleep 5
    elapsed=$((elapsed+5))
  done
  return 1
}
wait_service(){
  svc="$1"; timeout="$2"
  elapsed=0
  while [ $elapsed -lt "$timeout" ]; do
    state=$(health_of "$svc")
    case "$state" in
      healthy|running) return 0 ;;
    esac
    sleep 5
    elapsed=$((elapsed+5))
  done
  return 1
}
start_wave(){
  label="$1"; timeout="$2"; shift 2
  log "Starting wave: $label -> $*"
  ensure_docker
  prepare_env
  set_restart_no "$@"
  recreate_if_needed "$@"
  $COMPOSE up -d "$@" >/dev/null
  if wait_wave "$timeout" "$@"; then
    log "Wave healthy: $label"
  else
    log "Wave not fully healthy yet: $label"
  fi
}
start_wave_async(){
  label="$1"; shift
  log "Starting wave async: $label -> $*"
  ensure_docker
  prepare_env
  set_restart_no "$@"
  recreate_if_needed "$@"
  $COMPOSE up -d "$@" >/dev/null
}
start_downloader_wave(){
  log "Starting wave: downloader-base -> gluetun"
  ensure_docker
  prepare_env
  set_restart_no gluetun gluetun-namespace-guard qbittorrent port-updater sabnzbd
  if [ "$ENABLE_SAB" = "1" ]; then
    $DOCKER rm -f gluetun gluetun-namespace-guard qbittorrent port-updater sabnzbd >/dev/null 2>&1 || true
  else
    $DOCKER rm -f gluetun gluetun-namespace-guard qbittorrent port-updater >/dev/null 2>&1 || true
  fi
  $COMPOSE up -d gluetun >/dev/null
  if wait_service gluetun "$DOWNLOADER_BASE_WAIT_SECONDS"; then
    log "Wave healthy: downloader-base"
  else
    log "Wave not fully healthy yet: downloader-base"
  fi

  if [ "$ENABLE_SAB" = "1" ]; then
    log "Starting wave: downloader-clients -> qbittorrent port-updater sabnzbd gluetun-namespace-guard"
    recreate_if_needed qbittorrent port-updater sabnzbd gluetun-namespace-guard
    $COMPOSE up -d qbittorrent port-updater sabnzbd gluetun-namespace-guard >/dev/null
    wait_set="qbittorrent port-updater sabnzbd gluetun-namespace-guard"
  else
    log "Starting wave: downloader-clients -> qbittorrent port-updater gluetun-namespace-guard"
    recreate_if_needed qbittorrent port-updater gluetun-namespace-guard
    $COMPOSE up -d qbittorrent port-updater gluetun-namespace-guard >/dev/null
    wait_set="qbittorrent port-updater gluetun-namespace-guard"
  fi
  if wait_wave "$DOWNLOADER_CLIENT_WAIT_SECONDS" $wait_set; then
    log "Wave healthy: downloader-clients"
  else
    log "Wave not fully healthy yet: downloader-clients"
  fi
}
start_minimal_movie_downloader_wave(){
  log "Starting wave: downloader-base -> gluetun"
  ensure_docker
  prepare_env
  set_restart_no gluetun qbittorrent
  $DOCKER rm -f gluetun qbittorrent >/dev/null 2>&1 || true
  $COMPOSE up -d gluetun >/dev/null
  if wait_service gluetun "$DOWNLOADER_BASE_WAIT_SECONDS"; then
    log "Wave healthy: downloader-base"
  else
    log "Wave not fully healthy yet: downloader-base"
  fi

  log "Starting wave: downloader-client -> qbittorrent"
  recreate_if_needed qbittorrent
  $COMPOSE up -d qbittorrent >/dev/null
  if wait_wave "$DOWNLOADER_CLIENT_WAIT_SECONDS" qbittorrent; then
    log "Wave healthy: downloader-client"
  else
    log "Wave not fully healthy yet: downloader-client"
  fi
}
start_photo_wave(){
  start_wave photos-core 300 immich-postgres immich-redis
  start_wave photos-app 900 immich-machine-learning immich-server
}
ensure_docker
case "$START_SCOPE" in
  frontdoor)
    start_wave frontdoor 180 homepage update-status pihole portainer
    ;;
  arr)
    start_wave_async antibot flaresolverr
    start_wave arr 900 radarr sonarr lidarr bazarr prowlarr overseerr
    ;;
  automation)
    start_wave automation 900 unpackerr download-orchestrator indexer-guardian recyclarr autoheal
    ;;
  movie-pipeline)
    start_wave_async antibot flaresolverr
    start_wave movie-arr 360 radarr prowlarr
    start_minimal_movie_downloader_wave
    start_wave_async antivirus clamav
    start_wave_async scanner scanner
    ;;
  security)
    start_wave antivirus 1800 clamav
    start_wave scanner 300 scanner
    start_wave antibot 600 flaresolverr
    ;;
  downloader)
    start_downloader_wave
    ;;
  media)
    start_wave media 900 plex tdarr cloudflared
    ;;
  photos)
    start_photo_wave
    ;;
  optional)
    start_wave maintenance 120 watchtower
    ;;
  core)
    start_wave frontdoor 180 homepage update-status pihole portainer
    start_wave_async antibot flaresolverr
    start_wave arr 900 radarr sonarr lidarr bazarr prowlarr overseerr
    start_downloader_wave
    start_wave media 900 plex tdarr cloudflared
    start_photo_wave
    start_wave automation 900 unpackerr download-orchestrator indexer-guardian recyclarr autoheal
    start_wave antivirus 1800 clamav
    start_wave scanner 300 scanner
    ;;
  full|*)
    start_wave frontdoor 180 homepage update-status pihole portainer
    start_wave_async antibot flaresolverr
    start_wave arr 900 radarr sonarr lidarr bazarr prowlarr overseerr
    start_downloader_wave
    start_wave media 900 plex tdarr cloudflared
    start_photo_wave
    start_wave automation 900 unpackerr download-orchestrator indexer-guardian recyclarr autoheal
    start_wave antivirus 1800 clamav
    start_wave scanner 300 scanner
    if [ "$START_OPTIONAL" = "1" ]; then
      start_wave maintenance 120 watchtower
    fi
    ;;
esac
log 'Harbor staged startup pass complete.'
