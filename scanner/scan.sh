#!/bin/bash
# ============================================================================
#  Harbor Media Server — Security Scanner
#  Three-layer protection:
#    1. Dangerous file extension blocking (.exe, .bat, .ps1, etc.)
#    2. Media file header validation (checks magic bytes)
#    3. ClamAV antivirus scanning
#
#  Polls the download directory every 30 seconds.
#  Full re-scan every 6 hours (configurable via FULL_SCAN_INTERVAL).
#  Automatically deletes threats and optionally removes torrents from qBit.
# ============================================================================

set -euo pipefail

# --- Configuration from environment variables ---
SCAN_DIR="${SCAN_DIR:-/downloads}"
QUARANTINE_DIR="${QUARANTINE_DIR:-/quarantine}"
LOG_DIR="${LOG_DIR:-/logs}"
CLAMAV_HOST="${CLAMAV_HOST:-clamav}"
CLAMAV_PORT="${CLAMAV_PORT:-3310}"
QBIT_HOST="${QBIT_HOST:-gluetun}"
QBIT_PORT="${QBIT_PORT:-8081}"
QBIT_USER="${QBIT_USER:-}"
QBIT_PASS="${QBIT_PASS:-}"
FULL_SCAN_INTERVAL="${FULL_SCAN_INTERVAL:-21600}"
POLL_INTERVAL=30

# --- File paths ---
SCAN_LOG="${LOG_DIR}/scan.log"
SCANNED_DB="${LOG_DIR}/scanned_files.db"

# --- Dangerous extensions ---
DANGEROUS_EXTENSIONS="exe|bat|cmd|com|scr|pif|vbs|vbe|js|jse|wsf|wsh|ps1|ps2|psc1|psc2|msi|msp|mst|cpl|hta|inf|ins|isp|reg|rgs|sct|shb|shs|ws|wsc|lnk|dll|sys|drv|ocx|cpl"

# --- Logging ---
log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" | tee -a "$SCAN_LOG"
}

# --- Initialize ---
mkdir -p "$QUARANTINE_DIR" "$LOG_DIR"
touch "$SCANNED_DB"

log "INFO" "=== Harbor Media Server Security Scanner Started ==="
log "INFO" "Scan directory: $SCAN_DIR"
log "INFO" "Poll interval: ${POLL_INTERVAL}s | Full re-scan interval: ${FULL_SCAN_INTERVAL}s"

# --- Wait for ClamAV daemon to be ready ---
wait_for_clamav() {
    log "INFO" "Waiting for ClamAV daemon at ${CLAMAV_HOST}:${CLAMAV_PORT}..."
    local retries=0
    while ! nc -z "$CLAMAV_HOST" "$CLAMAV_PORT" 2>/dev/null; do
        retries=$((retries + 1))
        if [ $retries -ge 60 ]; then
            log "ERROR" "ClamAV daemon not available after 60 attempts. Continuing without AV..."
            return 1
        fi
        sleep 5
    done
    log "INFO" "ClamAV daemon is ready!"
    return 0
}

# --- Check if file was already scanned ---
is_already_scanned() {
    local filepath="$1"
    local filesize filemod fingerprint
    filesize=$(stat -c%s "$filepath" 2>/dev/null || echo "0")
    filemod=$(stat -c%Y "$filepath" 2>/dev/null || echo "0")
    fingerprint="${filepath}|${filesize}|${filemod}"
    grep -qF "$fingerprint" "$SCANNED_DB" 2>/dev/null
}

mark_as_scanned() {
    local filepath="$1"
    local filesize filemod fingerprint
    filesize=$(stat -c%s "$filepath" 2>/dev/null || echo "0")
    filemod=$(stat -c%Y "$filepath" 2>/dev/null || echo "0")
    fingerprint="${filepath}|${filesize}|${filemod}"
    echo "$fingerprint" >> "$SCANNED_DB"
}

# --- Layer 1: Dangerous extension check ---
check_dangerous_extension() {
    local filepath="$1"
    local filename
    filename=$(basename "$filepath")
    local ext="${filename##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    if echo "$ext" | grep -qiE "^(${DANGEROUS_EXTENSIONS})$"; then
        return 1
    fi
    return 0
}

# --- Layer 2: Media header validation ---
validate_media_header() {
    local filepath="$1"
    local filename
    filename=$(basename "$filepath")
    local ext="${filename##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    case "$ext" in
        mkv)
            local header
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null)
            [ "$header" = "1a45dfa3" ] && return 0
            ;;
        mp4|m4v|m4a)
            local header
            header=$(xxd -l 12 -p "$filepath" 2>/dev/null)
            echo "$header" | grep -qi "667479706" && return 0
            ;;
        avi)
            local header
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null)
            [ "$header" = "52494646" ] && return 0
            ;;
        mp3)
            local header
            header=$(xxd -l 3 -p "$filepath" 2>/dev/null)
            [ "$header" = "494433" ] && return 0
            header=$(xxd -l 2 -p "$filepath" 2>/dev/null)
            [ "$header" = "fffb" ] || [ "$header" = "fff3" ] || [ "$header" = "ffe3" ] && return 0
            ;;
        flac)
            local header
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null)
            [ "$header" = "664c6143" ] && return 0
            ;;
        jpg|jpeg)
            local header
            header=$(xxd -l 2 -p "$filepath" 2>/dev/null)
            [ "$header" = "ffd8" ] && return 0
            ;;
        png)
            local header
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null)
            [ "$header" = "89504e47" ] && return 0
            ;;
        *)
            return 0
            ;;
    esac

    return 1
}

# --- Layer 3: ClamAV scan ---
scan_file_with_clamav() {
    local filepath="$1"
    local result
    result=$(clamdscan --stream --no-summary "$filepath" 2>&1)
    local exit_code=$?

    if [ $exit_code -eq 1 ]; then
        log "THREAT" "ClamAV DETECTED: $result"
        return 1
    elif [ $exit_code -eq 2 ]; then
        log "ERROR" "ClamAV error scanning $filepath: $result"
        return 0
    fi
    return 0
}

# --- Delete torrent from qBittorrent if threat found ---
delete_torrent() {
    local filepath="$1"
    [ -z "$QBIT_HOST" ] && return

    local cookie
    cookie=$(curl -s -c - "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/auth/login" \
        -d "username=${QBIT_USER}&password=${QBIT_PASS}" 2>/dev/null | grep -oP 'SID\s+\K\S+')

    if [ -n "$cookie" ]; then
        local torrents
        torrents=$(curl -s -b "SID=$cookie" \
            "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/torrents/info" 2>/dev/null)

        local hash
        hash=$(echo "$torrents" | jq -r ".[] | select(.content_path != null) | select(.content_path | contains(\"$(basename "$(dirname "$filepath")")\")) | .hash" 2>/dev/null | head -1)

        if [ -n "$hash" ] && [ "$hash" != "null" ]; then
            curl -s -b "SID=$cookie" \
                "http://${QBIT_HOST}:${QBIT_PORT}/api/v2/torrents/delete" \
                -d "hashes=${hash}&deleteFiles=true" 2>/dev/null
            log "ACTION" "Deleted torrent $hash associated with threat"
        fi
    fi
}

# --- Handle threat ---
handle_threat() {
    local filepath="$1"
    local reason="$2"

    log "DANGER" "=========================================="
    log "DANGER" "DANGEROUS FILE DETECTED!"
    log "DANGER" "File: $filepath"
    log "DANGER" "Reason: $reason"
    log "DANGER" "Action: DELETED"
    log "DANGER" "=========================================="

    rm -f "$filepath"
    delete_torrent "$filepath"
}

# --- Main scan function ---
scan_file() {
    local filepath="$1"
    [ ! -f "$filepath" ] && return
    is_already_scanned "$filepath" && return

    local filename
    filename=$(basename "$filepath")

    if ! check_dangerous_extension "$filepath"; then
        handle_threat "$filepath" "Dangerous file extension: ${filename##*.}"
        return
    fi

    if ! validate_media_header "$filepath"; then
        handle_threat "$filepath" "Media header mismatch — possible disguised executable"
        return
    fi

    if ! scan_file_with_clamav "$filepath"; then
        handle_threat "$filepath" "ClamAV virus detection"
        return
    fi

    mark_as_scanned "$filepath"
}

# === MAIN LOOP ===
wait_for_clamav

LAST_FULL_SCAN=$(date +%s)

while true; do
    NOW=$(date +%s)
    if [ $((NOW - LAST_FULL_SCAN)) -ge "$FULL_SCAN_INTERVAL" ]; then
        log "INFO" "Starting periodic full re-scan..."
        rm -f "$SCANNED_DB"
        touch "$SCANNED_DB"
        LAST_FULL_SCAN=$NOW
    fi

    FILE_COUNT=0
    while IFS= read -r -d '' filepath; do
        scan_file "$filepath"
        FILE_COUNT=$((FILE_COUNT + 1))
    done < <(find "$SCAN_DIR" -type f -print0 2>/dev/null)

    sleep "$POLL_INTERVAL"
done
