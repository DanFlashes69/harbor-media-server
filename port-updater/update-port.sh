#!/bin/bash
QBIT_HOST="${QBIT_HOST:-localhost}"
QBIT_PORT="${QBIT_PORT:-8081}"
QBIT_USER="${QBIT_USER:-}"
QBIT_PASS="${QBIT_PASS:-}"
GLUETUN_PORT_FILE="${GLUETUN_PORT_FILE:-/tmp/gluetun/forwarded_port}"
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"
COOKIE_FILE="/tmp/qbit_cookie"
QBIT_CONFIG_FILE="${QBIT_CONFIG_FILE:-/qbit-config/qBittorrent/qBittorrent.conf}"
QBIT_CONTAINER_NAME="${QBIT_CONTAINER_NAME:-qbittorrent}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

qbit_login() {
    if [ -n "$QBIT_USER" ] && [ -n "$QBIT_PASS" ]; then
        rm -f "$COOKIE_FILE"
        RESPONSE=$(curl -s -c "$COOKIE_FILE" -d "username=${QBIT_USER}&password=${QBIT_PASS}" "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/auth/login" 2>&1)
        if [ "$RESPONSE" = "Ok." ]; then
            log "Authenticated with qBittorrent"
            return 0
        else
            log "ERROR: qBittorrent auth failed: $RESPONSE"
            return 1
        fi
    fi
    return 0
}

get_forwarded_port() { [ -f "$GLUETUN_PORT_FILE" ] && cat "$GLUETUN_PORT_FILE" || echo ""; }

get_qbit_port() {
    curl -s -b "$COOKIE_FILE" "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/app/preferences" 2>/dev/null | grep -o '"listen_port":[0-9]*' | cut -d: -f2
}

set_qbit_config_port() {
    local port="$1"

    if [ ! -f "$QBIT_CONFIG_FILE" ]; then
        log "ERROR: qBittorrent config file not found at $QBIT_CONFIG_FILE"
        return 1
    fi

    if grep -q '^Session\\Port=' "$QBIT_CONFIG_FILE"; then
        sed -i "s/^Session\\\\Port=.*/Session\\\\Port=${port}/" "$QBIT_CONFIG_FILE"
    else
        printf '\nSession\\Port=%s\n' "$port" >> "$QBIT_CONFIG_FILE"
    fi

    if grep -q '^Connection\\PortRangeMin=' "$QBIT_CONFIG_FILE"; then
        sed -i "s/^Connection\\\\PortRangeMin=.*/Connection\\\\PortRangeMin=${port}/" "$QBIT_CONFIG_FILE"
    else
        printf 'Connection\\PortRangeMin=%s\n' "$port" >> "$QBIT_CONFIG_FILE"
    fi

    log "Wrote forwarded port ${port} to $QBIT_CONFIG_FILE"
}

stop_qbit_container() {
    log "Stopping qBittorrent container ${QBIT_CONTAINER_NAME}..."
    docker stop "$QBIT_CONTAINER_NAME" >/dev/null
    log "qBittorrent container has stopped"
}

start_qbit_container() {
    log "Starting qBittorrent container ${QBIT_CONTAINER_NAME}..."
    docker start "$QBIT_CONTAINER_NAME" >/dev/null
    log "Waiting for qBittorrent to restart..."
    while ! curl -s "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/app/version" >/dev/null 2>&1; do
        sleep 3
    done
    log "qBittorrent is back online"
    qbit_login
}

log "Port updater starting - qBit=${QBIT_HOST}:${QBIT_PORT}, interval=${CHECK_INTERVAL}s"
while ! curl -s "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/app/version" > /dev/null 2>&1; do
    log "Waiting for qBittorrent..."
    sleep 10
done
log "qBittorrent is ready"
qbit_login

while true; do
    FORWARDED_PORT=$(get_forwarded_port)
    if [ -z "$FORWARDED_PORT" ] || [ "$FORWARDED_PORT" = "0" ]; then
        log "No forwarded port yet..."
        sleep "$CHECK_INTERVAL"
        continue
    fi

    CURRENT=$(get_qbit_port)
    if [ -z "$CURRENT" ]; then
        log "WARNING: unable to read qBittorrent listen port, re-authing"
        qbit_login
        CURRENT=$(get_qbit_port)
    fi

    if [ "$FORWARDED_PORT" != "$CURRENT" ]; then
        log "Sync needed: VPN=$FORWARDED_PORT, qBit=$CURRENT"
        stop_qbit_container
        set_qbit_config_port "$FORWARDED_PORT" || { sleep "$CHECK_INTERVAL"; continue; }
        start_qbit_container
        VERIFY=$(get_qbit_port)
        if [ "$VERIFY" = "$FORWARDED_PORT" ]; then
            log "SUCCESS: port updated to $FORWARDED_PORT"
        else
            log "WARNING: verify shows $VERIFY, retrying restart"
            stop_qbit_container
            set_qbit_config_port "$FORWARDED_PORT" || { sleep "$CHECK_INTERVAL"; continue; }
            start_qbit_container
            VERIFY=$(get_qbit_port)
            if [ "$VERIFY" = "$FORWARDED_PORT" ]; then
                log "SUCCESS: port updated to $FORWARDED_PORT after retry"
            else
                log "ERROR: qBittorrent port still out of sync (VPN=$FORWARDED_PORT, qBit=$VERIFY)"
            fi
        fi
    else
        log "In sync: $FORWARDED_PORT"
    fi

    sleep "$CHECK_INTERVAL"
done
