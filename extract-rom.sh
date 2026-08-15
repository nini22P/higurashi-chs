#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

log() { echo "[*] $*"; }
exec() {
    local cmd=$1
    shift
    if [ ! -f "$cmd" ] && [ -f "${cmd}.exe" ]; then
        cmd="${cmd}.exe"
    fi
    echo "+ $cmd $*"
    if [[ "$cmd" == *.exe ]] && command -v wine &>/dev/null; then
        wine "$cmd" "$@"
    else
        "$cmd" "$@"
    fi
}

extract_rom() {
    local game=$1
    for name in data patch append; do
        local target="raw/$game/$name"
        local rom="raw/$game/$name.rom"
        if [ -d "$target" ]; then
            continue
        fi
        if [ -f "$rom" ]; then
            log "Extracting $rom ..."
            exec bin/shin-tl.exe rom extract "$rom" "$target"
        else
            log "Missing $rom, skipping extraction."
        fi
    done
}

GAME="${1:-}"
case "$GAME" in
  hou) extract_rom "hou" ;;
  sui) extract_rom "sui" ;;
  *) echo "Usage: $0 [hou|sui]"; exit 1 ;;
esac

