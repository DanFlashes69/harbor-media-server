#!/bin/bash

set -euo pipefail

LOG="${LOG:-/logs/retro-media-clamscan.log}"
QUARANTINE_ROOT="${QUARANTINE_ROOT:-/quarantine/retro}"
SCAN_TARGETS="${SCAN_TARGETS:-/scan/media /scan/downloads}"

mkdir -p "$(dirname "$LOG")" "$QUARANTINE_ROOT"

log() {
    local level="$1"
    shift
    printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$*" | tee -a "$LOG"
}

quarantine_file() {
    local filepath="$1"
    local result="$2"
    local relative destination

    relative="${filepath#/scan/}"
    if [ "$relative" = "$filepath" ]; then
        relative=$(basename "$filepath")
    fi

    destination="${QUARANTINE_ROOT}/${relative}"
    mkdir -p "$(dirname "$destination")"
    mv -f "$filepath" "$destination"
    log "THREAT" "$filepath -> $destination :: $result"
}

scan_one() {
    local filepath="$1"
    local result exit_code

    set +e
    result=$(clamdscan --stream --no-summary "$filepath" 2>&1)
    exit_code=$?
    set -e

    case "$exit_code" in
        0)
            ;;
        1)
            quarantine_file "$filepath" "$result"
            ;;
        2)
            log "WARN" "$filepath :: $result"
            ;;
    esac
}

: > "$LOG"
log "INFO" "Retro ClamAV scan started"
log "INFO" "Targets: ${SCAN_TARGETS}"

for target in $SCAN_TARGETS; do
    if [ -d "$target" ]; then
        while IFS= read -r -d '' filepath; do
            scan_one "$filepath"
        done < <(find "$target" -type f -print0)
    fi
done

log "INFO" "Retro ClamAV scan completed"
