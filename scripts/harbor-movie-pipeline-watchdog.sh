#!/bin/sh
set -eu

STACK_DIR=/volume1/docker/harbor/stacks/harbor-media-server
ENV_FILE="$STACK_DIR/.env.synology.local"
COMPOSE_FILE="$STACK_DIR/docker-compose.synology.private.yml"
DOCKER=/var/packages/ContainerManager/target/usr/bin/docker
COMPOSE_BIN=/var/packages/ContainerManager/target/usr/bin/docker-compose
LOG=/volume1/docker/harbor/appdata/update-guardian/status/movie-pipeline-watchdog.log
LOCKROOT=/volume1/docker/harbor/appdata/update-guardian/locks
LOCKDIR="$LOCKROOT/harbor-movie-pipeline-watchdog.lock"
PIDFILE="$LOCKDIR/pid"
CHECK_INTERVAL="${CHECK_INTERVAL:-20}"
MOVIE_SERVICES="gluetun qbittorrent radarr prowlarr flaresolverr clamav scanner"

if [ -x "$COMPOSE_BIN" ]; then
  COMPOSE="$COMPOSE_BIN --env-file $ENV_FILE -f $COMPOSE_FILE"
else
  COMPOSE="$DOCKER compose --env-file $ENV_FILE -f $COMPOSE_FILE"
fi

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
      log "Another movie pipeline watchdog is already running (pid=$pid). Exiting."
      return 1
    fi
  fi

  log 'Found stale movie pipeline watchdog lock. Removing it.'
  rm -rf "$LOCKDIR" >/dev/null 2>&1 || true
  mkdir "$LOCKDIR" 2>/dev/null || {
    log 'Unable to claim movie pipeline watchdog lock after stale-lock cleanup.'
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
      if $DOCKER version >/dev/null 2>&1; then
        return 0
      fi
      sleep 2
      i=$((i+1))
    done
    log 'Docker daemon failed to become ready.'
    return 1
  fi
}

container_running(){
  [ "$($DOCKER inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo missing)" = "running" ]
}

container_status(){
  $DOCKER inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo missing
}

container_oom_killed(){
  $DOCKER inspect --format '{{.State.OOMKilled}}' "$1" 2>/dev/null || echo false
}

container_healthy_or_running(){
  state="$($DOCKER inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo missing)"
  status="${state%%|*}"
  health="${state##*|}"
  [ "$status" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ] || [ "$health" = "starting" ]; }
}

container_health(){
  $DOCKER inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo none
}

remove_container(){
  svc="$1"
  status="$(container_status "$svc")"
  oom="$(container_oom_killed "$svc")"
  [ "$status" = "missing" ] && return 0
  log "Removing stale container: $svc (status=$status oom_killed=$oom)"
  $DOCKER rm -f "$svc" >/dev/null 2>&1 || true
}

cleanup_stale_container(){
  svc="$1"
  status="$(container_status "$svc")"
  case "$status" in
    exited|dead|created|restarting)
      remove_container "$svc"
      ;;
  esac
  if [ "$(container_health "$svc")" = "unhealthy" ]; then
    remove_container "$svc"
  fi
}

cleanup_all_stale_movie_services(){
  for svc in $MOVIE_SERVICES; do
    cleanup_stale_container "$svc"
  done
}

wait_for_http(){
  url="$1"
  timeout="${2:-120}"
  elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
    elapsed=$((elapsed+5))
  done
  return 1
}

start_service(){
  log "Ensuring service is up: $*"
  for svc in "$@"; do
    cleanup_stale_container "$svc"
  done
  (cd "$STACK_DIR" && $COMPOSE up -d "$@" >/dev/null 2>&1) || log "compose up failed for: $*"
}

start_service_no_deps(){
  log "Ensuring service is up without deps: $*"
  for svc in "$@"; do
    cleanup_stale_container "$svc"
  done
  (cd "$STACK_DIR" && $COMPOSE up -d --no-deps "$@" >/dev/null 2>&1) || log "compose up --no-deps failed for: $*"
}

recreate_service(){
  log "Recreating service: $*"
  for svc in "$@"; do
    remove_container "$svc"
  done
  start_service "$@"
}

recreate_service_no_deps(){
  log "Recreating service without deps: $*"
  for svc in "$@"; do
    remove_container "$svc"
  done
  start_service_no_deps "$@"
}

ensure_docker
log 'Movie pipeline watchdog started.'

while true; do
  ensure_docker || { sleep "$CHECK_INTERVAL"; continue; }
  cleanup_all_stale_movie_services

  if ! container_running gluetun; then
    if container_running qbittorrent; then
      log 'Gluetun is down; stopping qbittorrent to preserve VPN-only invariant.'
      $DOCKER stop qbittorrent >/dev/null 2>&1 || true
    fi
    start_service gluetun
    sleep 10
  fi

  if container_running gluetun && ! container_running qbittorrent; then
    start_service qbittorrent
    sleep 10
  fi

  if ! container_running radarr; then
    start_service radarr
  fi

  if ! container_running prowlarr; then
    start_service prowlarr
  fi

  if ! container_running flaresolverr; then
    start_service flaresolverr
  fi

  if ! container_running clamav; then
    start_service clamav
  fi

  if ! container_running scanner; then
    start_service_no_deps scanner
  fi

  if container_running qbittorrent && ! wait_for_http http://127.0.0.1:8081 20; then
    log 'qBittorrent process is up but WebUI is not responding; recreating qbittorrent.'
    recreate_service qbittorrent
  fi

  if container_running radarr && ! wait_for_http http://127.0.0.1:7878/ping 20; then
    log 'Radarr process is up but /ping is not responding; recreating radarr.'
    recreate_service radarr
  fi

  if container_running prowlarr && ! wait_for_http http://127.0.0.1:9696/ping 20; then
    log 'Prowlarr process is up but /ping is not responding; recreating prowlarr.'
    recreate_service prowlarr
  fi

  if container_running flaresolverr && ! wait_for_http http://127.0.0.1:8191/ 20; then
    log 'FlareSolverr process is up but root endpoint is not responding; recreating flaresolverr.'
    recreate_service flaresolverr
  fi

  if container_running scanner && [ "$(container_health scanner)" = "unhealthy" ]; then
    log 'Scanner is unhealthy; recreating scanner.'
    recreate_service_no_deps scanner
  fi

  sleep "$CHECK_INTERVAL"
done
