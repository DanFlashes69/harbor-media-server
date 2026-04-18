#!/bin/bash
# ============================================================================
#  Harbor Media Server — Security Scanner
#  Safe-mode design:
#    1. Quarantine obviously dangerous file extensions
#    2. Optionally validate media headers after files are stable
#    3. Scan stable files with ClamAV
#
#  Important safety rules:
#    - Never delete media automatically
#    - Never mark a file as clean if ClamAV had a transport/runtime error
#    - Never scan files that are too new or still changing size
# ============================================================================

set -euo pipefail

SCAN_DIR="${SCAN_DIR:-/downloads}"
QUARANTINE_DIR="${QUARANTINE_DIR:-/quarantine}"
LOG_DIR="${LOG_DIR:-/logs}"
CLAMAV_HOST="${CLAMAV_HOST:-clamav}"
CLAMAV_PORT="${CLAMAV_PORT:-3310}"
LOCAL_CLAMAV_DB_DIR="${LOCAL_CLAMAV_DB_DIR:-/var/lib/clamav}"
CLAMAV_READY_RETRIES="${CLAMAV_READY_RETRIES:-12}"
FULL_SCAN_INTERVAL="${FULL_SCAN_INTERVAL:-21600}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
MIN_FILE_AGE_SECONDS="${MIN_FILE_AGE_SECONDS:-900}"
ENABLE_MEDIA_HEADER_VALIDATION="${ENABLE_MEDIA_HEADER_VALIDATION:-false}"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-60}"

SCAN_LOG="${LOG_DIR}/scan.log"
SCANNED_DB="${LOG_DIR}/scanned_files.db"
PENDING_DB="${LOG_DIR}/pending_files.db"
HEARTBEAT_FILE="${LOG_DIR}/scanner-heartbeat"

DANGEROUS_EXTENSIONS="exe|bat|cmd|com|scr|pif|vbs|vbe|js|jse|wsf|wsh|ps1|ps2|psc1|psc2|msi|msp|mst|cpl|hta|inf|ins|isp|reg|rgs|sct|shb|shs|ws|wsc|lnk|dll|sys|drv|ocx|cpl"

log() {
    local level="$1"
    shift
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $*" | tee -a "$SCAN_LOG"
}

mkdir -p "$SCAN_DIR" "$QUARANTINE_DIR" "$LOG_DIR"
touch "$SCANNED_DB" "$PENDING_DB"
touch "$HEARTBEAT_FILE"

log "INFO" "=== Harbor Media Server Security Scanner Started ==="
log "INFO" "Scan directory: $SCAN_DIR"
log "INFO" "Quarantine directory: $QUARANTINE_DIR"
log "INFO" "Poll interval: ${POLL_INTERVAL}s | Full re-scan interval: ${FULL_SCAN_INTERVAL}s"
log "INFO" "Minimum file age before scan: ${MIN_FILE_AGE_SECONDS}s"
log "INFO" "Media header validation enabled: ${ENABLE_MEDIA_HEADER_VALIDATION}"
log "INFO" "Heartbeat interval: ${HEARTBEAT_INTERVAL_SECONDS}s"

shutdown_requested=0
heartbeat_pid=""

on_shutdown() {
    shutdown_requested=1
    log "INFO" "Scanner shutdown requested; exiting loop."
    if [ -n "$heartbeat_pid" ] && kill -0 "$heartbeat_pid" 2>/dev/null; then
        kill "$heartbeat_pid" 2>/dev/null || true
    fi
}

trap on_shutdown INT TERM

heartbeat_refresher() {
    while [ "$shutdown_requested" -eq 0 ]; do
        touch "$HEARTBEAT_FILE"
        sleep "$HEARTBEAT_INTERVAL_SECONDS"
    done
}

heartbeat_refresher &
heartbeat_pid=$!

wait_for_clamav() {
    log "INFO" "Waiting for ClamAV daemon at ${CLAMAV_HOST}:${CLAMAV_PORT}..."
    local retries=0
    while ! nc -z "$CLAMAV_HOST" "$CLAMAV_PORT" 2>/dev/null; do
        retries=$((retries + 1))
        if [ "$retries" -ge "$CLAMAV_READY_RETRIES" ]; then
            log "WARN" "ClamAV daemon not reachable after ${CLAMAV_READY_RETRIES} attempts. Scanner will use fallback scanning when possible and retry on the next loop."
            return 1
        fi
        sleep 5
    done
    log "INFO" "ClamAV daemon is ready!"
    return 0
}

is_clamav_daemon_ready() {
    nc -z "$CLAMAV_HOST" "$CLAMAV_PORT" 2>/dev/null
}

has_local_clamav_db() {
    [ -d "$LOCAL_CLAMAV_DB_DIR" ] && \
    find "$LOCAL_CLAMAV_DB_DIR" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' -o -name '*.cud' \) | grep -q .
}

get_fingerprint() {
    local filepath="$1"
    local filesize filemod
    filesize=$(stat -c%s "$filepath" 2>/dev/null || echo "0")
    filemod=$(stat -c%Y "$filepath" 2>/dev/null || echo "0")
    echo "${filepath}|${filesize}|${filemod}"
}

is_already_scanned() {
    local filepath="$1"
    local fingerprint
    fingerprint=$(get_fingerprint "$filepath")
    grep -qF "$fingerprint" "$SCANNED_DB" 2>/dev/null
}

mark_as_scanned() {
    local filepath="$1"
    get_fingerprint "$filepath" >> "$SCANNED_DB"
}

clear_pending_state() {
    local filepath="$1"
    local tmp
    tmp="${PENDING_DB}.tmp"
    grep -vF "${filepath}|" "$PENDING_DB" > "$tmp" 2>/dev/null || true
    mv "$tmp" "$PENDING_DB"
}

is_file_stable() {
    local filepath="$1"
    local fingerprint last_modified now age

    case "$filepath" in
        "$SCAN_DIR"/_omega_eicar/*|"$SCAN_DIR"/_scanner_test/*|"$SCAN_DIR"/_scanner_live_test/*)
            clear_pending_state "$filepath"
            return 0
            ;;
    esac

    last_modified=$(stat -c%Y "$filepath" 2>/dev/null || echo "0")
    now=$(date +%s)
    age=$((now - last_modified))

    if [ "$age" -lt "$MIN_FILE_AGE_SECONDS" ]; then
        return 1
    fi

    fingerprint=$(get_fingerprint "$filepath")

    if grep -qF "$fingerprint" "$PENDING_DB" 2>/dev/null; then
        return 0
    fi

    clear_pending_state "$filepath"
    echo "$fingerprint" >> "$PENDING_DB"
    return 1
}

should_skip_file() {
    local filepath="$1"
    local filename
    filename=$(basename "$filepath")

    case "$filepath" in
        "$QUARANTINE_DIR"/*) return 0 ;;
        "$SCAN_DIR"/incomplete/*) return 0 ;;
        "$SCAN_DIR"/.arr-recycle/*) return 0 ;;
    esac

    case "$filename" in
        *.part|*.!qB|*.tmp|*.temp|*.partial|*.crdownload|*.aria2|*.bc!|*.DS_Store)
            return 0
            ;;
    esac

    return 1
}

check_dangerous_extension() {
    local filepath="$1"
    local filename ext
    filename=$(basename "$filepath")
    ext="${filename##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    if echo "$ext" | grep -qiE "^(${DANGEROUS_EXTENSIONS})$"; then
        return 1
    fi

    return 0
}

validate_media_header() {
    local filepath="$1"
    local filename ext header
    filename=$(basename "$filepath")
    ext="${filename##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    case "$ext" in
        mkv)
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "1a45dfa3" ] && return 0
            ;;
        mp4|m4v|m4a)
            header=$(xxd -l 12 -p "$filepath" 2>/dev/null || true)
            echo "$header" | grep -qi "667479706" && return 0
            ;;
        avi)
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "52494646" ] && return 0
            ;;
        mp3)
            header=$(xxd -l 3 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "494433" ] && return 0
            header=$(xxd -l 2 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "fffb" ] || [ "$header" = "fff3" ] || [ "$header" = "ffe3" ] && return 0
            ;;
        flac)
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "664c6143" ] && return 0
            ;;
        jpg|jpeg)
            header=$(xxd -l 2 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "ffd8" ] && return 0
            ;;
        png)
            header=$(xxd -l 4 -p "$filepath" 2>/dev/null || true)
            [ "$header" = "89504e47" ] && return 0
            ;;
        *)
            return 0
            ;;
    esac

    return 1
}

scan_file_with_clamav() {
    local filepath="$1"
    local result exit_code

    if is_clamav_daemon_ready; then
        set +e
        result=$(clamdscan --stream --no-summary "$filepath" 2>&1)
        exit_code=$?
        set -e
    elif has_local_clamav_db; then
        log "WARN" "ClamAV daemon unavailable, falling back to local signature scan for $filepath"
        set +e
        result=$(clamscan --database="$LOCAL_CLAMAV_DB_DIR" --no-summary "$filepath" 2>&1)
        exit_code=$?
        set -e
    else
        log "WARN" "ClamAV daemon unavailable and no local signature database present for $filepath"
        return 2
    fi

    if [ "$exit_code" -eq 0 ]; then
        return 0
    fi

    if [ "$exit_code" -eq 1 ]; then
        log "THREAT" "ClamAV DETECTED: $result"
        return 1
    fi

    log "WARN" "ClamAV transport/runtime error while scanning $filepath: $result"
    return 2
}

quarantine_file() {
    local filepath="$1"
    local reason="$2"
    local relative destination

    relative="${filepath#$SCAN_DIR/}"
    if [ "$relative" = "$filepath" ]; then
        relative=$(basename "$filepath")
    fi

    destination="${QUARANTINE_DIR}/${relative}"
    mkdir -p "$(dirname "$destination")"

    log "DANGER" "=========================================="
    log "DANGER" "SUSPICIOUS FILE QUARANTINED"
    log "DANGER" "File: $filepath"
    log "DANGER" "Reason: $reason"
    log "DANGER" "Action: MOVED TO QUARANTINE"
    log "DANGER" "Destination: $destination"
    log "DANGER" "=========================================="

    if mv -f "$filepath" "$destination"; then
        clear_pending_state "$filepath"
        return 0
    fi

    log "ERROR" "Failed to move $filepath into quarantine"
    return 1
}

scan_file() {
    local filepath="$1"
    [ ! -f "$filepath" ] && return
    should_skip_file "$filepath" && return 0
    is_already_scanned "$filepath" && return 0
    is_file_stable "$filepath" || return 0

    if ! check_dangerous_extension "$filepath"; then
        quarantine_file "$filepath" "Dangerous file extension: ${filepath##*.}"
        return 0
    fi

    if [ "$ENABLE_MEDIA_HEADER_VALIDATION" = "true" ]; then
        if ! validate_media_header "$filepath"; then
            quarantine_file "$filepath" "Media header mismatch"
            return 0
        fi
    fi

    local scan_result=0
    scan_file_with_clamav "$filepath" || scan_result=$?
    case "$scan_result" in
        0)
            mark_as_scanned "$filepath"
            clear_pending_state "$filepath"
            ;;
        1)
            quarantine_file "$filepath" "ClamAV virus detection"
            ;;
        2)
            ;;
    esac

    return 0
}

scan_file_stream() {
    while IFS= read -r -d '' filepath; do
        if ! scan_file "$filepath"; then
            log "WARN" "Scanner skipped a file after an unexpected scan error: $filepath"
        fi
    done
}

run_scan_iteration() {
    touch "$HEARTBEAT_FILE"
    NOW=$(date +%s)

    if [ $((NOW - LAST_FULL_SCAN)) -ge "$FULL_SCAN_INTERVAL" ]; then
        log "INFO" "Starting periodic full re-scan..."
        : > "$SCANNED_DB"
        : > "$PENDING_DB"
        LAST_FULL_SCAN=$NOW
    fi

    scan_file_stream < <(
        find "$SCAN_DIR" -type f \
            \( -path "$SCAN_DIR/_omega_eicar/*" -o -path "$SCAN_DIR/_scanner_test/*" -o -path "$SCAN_DIR/_scanner_live_test/*" \) \
            -print0 2>/dev/null
    )

    scan_file_stream < <(
        find "$SCAN_DIR" -type f -mmin -60 \
            ! -path "$SCAN_DIR/_omega_eicar/*" \
            ! -path "$SCAN_DIR/_scanner_test/*" \
            ! -path "$SCAN_DIR/_scanner_live_test/*" \
            -print0 2>/dev/null
    )

    scan_file_stream < <(
        find "$SCAN_DIR" -type f \
            ! -mmin -60 \
            ! -path "$SCAN_DIR/_omega_eicar/*" \
            ! -path "$SCAN_DIR/_scanner_test/*" \
            ! -path "$SCAN_DIR/_scanner_live_test/*" \
            -print0 2>/dev/null
    )

    touch "$HEARTBEAT_FILE"
}

wait_for_clamav || true
LAST_FULL_SCAN=$(date +%s)

while true; do
    set +e
    run_scan_iteration
    iteration_status=$?
    set -e
    if [ "$iteration_status" -ne 0 ]; then
        log "WARN" "Scanner loop hit a transient failure (exit ${iteration_status}); continuing."
    fi
    if [ "$shutdown_requested" -eq 1 ]; then
        break
    fi
    sleep "$POLL_INTERVAL"
done

if [ -n "$heartbeat_pid" ] && kill -0 "$heartbeat_pid" 2>/dev/null; then
    kill "$heartbeat_pid" 2>/dev/null || true
fi
