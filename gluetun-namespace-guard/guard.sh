#!/bin/sh
set -eu

watch_container="${WATCH_CONTAINER:-gluetun}"
dependent_containers="${DEPENDENT_CONTAINERS:-qbittorrent,port-updater,sabnzbd}"
poll_interval="${POLL_INTERVAL_SECONDS:-10}"
health_wait_seconds="${HEALTH_WAIT_SECONDS:-120}"
heartbeat_file="${HEARTBEAT_FILE:-/tmp/heartbeat}"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

current_started_at() {
  docker inspect -f '{{.State.StartedAt}}' "$watch_container" 2>/dev/null || true
}

current_health() {
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$watch_container" 2>/dev/null || true
}

wait_for_gluetun() {
  elapsed=0
  while [ "$elapsed" -lt "$health_wait_seconds" ]; do
    health="$(current_health)"
    if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

restart_dependents() {
  old_ifs="$IFS"
  IFS=','
  for container in $dependent_containers; do
    trimmed="$(printf '%s' "$container" | xargs)"
    if [ -n "$trimmed" ]; then
      log "Restarting dependent container: $trimmed"
      docker restart "$trimmed" >/dev/null
    fi
  done
  IFS="$old_ifs"
}

touch "$heartbeat_file"
last_started_at=""

log "Watching $watch_container for namespace changes"

while true; do
  started_at="$(current_started_at)"
  if [ -z "$started_at" ]; then
    log "Waiting for $watch_container to exist"
    sleep "$poll_interval"
    touch "$heartbeat_file"
    continue
  fi

  if [ -z "$last_started_at" ]; then
    last_started_at="$started_at"
    log "Initial startedAt for $watch_container: $last_started_at"
  elif [ "$started_at" != "$last_started_at" ]; then
    log "Detected $watch_container restart: $last_started_at -> $started_at"
    if wait_for_gluetun; then
      restart_dependents
    else
      log "Timed out waiting for $watch_container to become healthy"
    fi
    last_started_at="$started_at"
  fi

  touch "$heartbeat_file"
  sleep "$poll_interval"
done
