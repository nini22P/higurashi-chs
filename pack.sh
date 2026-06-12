#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

pip install --user -r shin-tools/requirements.txt

log() { echo "[*] $*"; }
err() { echo "[!] $*" >&2; exit 1; }

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

extract_raw_roms() {
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

pack_hou() {
    mkdir -p "build/romfs" "bin"

    extract_raw_roms "hou"

    rm -rf "build/patch-hou"
    cp -r "raw/hou/patch" "build/patch-hou"

    if [ ! -f "build/main-hou.csv" ]; then
        log "Extracting text from main.snr..."
        exec bin/shin-tl.exe snr read higurashi-hou-v2 raw/hou/patch/main.snr build/main-hou.csv
    fi

    python shin-tools/script-tool.py import --main "build/main-hou.csv," --text higurashi-hou.csv --format "escaped,unescaped" --suffix "hou,sui"
    python tools/split-binary-csv.py binary.csv hou -o build/exefs.csv
    python shin-tools/mapping-tool.py mapping-config-hou.json

    exec bin/fnt4-tool.exe rebuild raw/hou/data/newrodin.fnt build/patch-hou/newrodin.fnt assets/font/ResourceHanRoundedCN-Medium.ttf -s 144 --letter-spacing 2 -c build/mapping-hou.toml
    exec bin/shin-tl.exe snr rewrite higurashi-hou-v2 raw/hou/patch/main.snr build/main-hou-mapped.csv build/patch-hou/main.snr

    # ./pack-txa.sh hou
    # python shin-tools/pic-tool.py pack -i assets/pic-hou -o build/patch-hou/picture -v 2

    exec bin/shin-tl.exe rom create --rom-version higurashi-hou-v2 build/patch-hou build/romfs/patch.rom

    log "Patching exefs..."
    mkdir -p "build/exefs"
    cp -f "assets/exefs/main" "build/exefs/main"
    exec bin/nx2elf.exe build/exefs/main
    python shin-tools/patch-tool.py -b build/exefs/main.elf -c build/exefs-mapped.csv
    exec bin/elf2nso.exe build/exefs/main.elf build/exefs/main
    rm -f build/exefs/main.elf

    log "Complete!"
    log "Saved to: build/romfs/"
    log "Saved to: build/exefs/"
}

pack_sui() {
    rm -rf "build/repatch"
    mkdir -p "build" "bin"
    cp -r "assets/repatch" "build"

    extract_raw_roms "sui"

    rm -rf "build/patch-sui"
    mkdir -p "build/patch-sui"

    if [ ! -f "build/main-sui.csv" ]; then
        log "Extracting text from main.snr..."
        exec bin/shin-tl.exe snr read higurashi-sui raw/sui/data/main.snr build/main-sui.csv
    fi

    python shin-tools/script-tool.py import --main ",build/main-sui.csv" --text higurashi-hou.csv --format "escaped,unescaped" --suffix "hou,sui"
    python tools/split-binary-csv.py binary.csv sui -o build/eboot-utf-16le.csv
    python shin-tools/mapping-tool.py mapping-config-sui.json

    exec bin/fnt4-tool.exe rebuild raw/sui/data/gothic.fnt build/patch-sui/gothic.fnt assets/font/ResourceHanRoundedCN-Medium.ttf -s 40 --letter-spacing 2 -c build/mapping-sui.toml
    exec bin/shin-tl.exe snr rewrite higurashi-sui raw/sui/data/main.snr build/main-sui-mapped.csv build/patch-sui/main.snr

    # ./pack-txa.sh sui
    # python shin-tools/pic-tool.py pack -i assets/pic-sui -o build/patch-sui/picture -v 0

    exec bin/shin-tl.exe rom create --rom-version higurashi-sui build/patch-sui build/repatch/PCSG00517/patch.rom

    log "Patching eboot..."
    exec bin/vita-unmake-fself.exe build/repatch/PCSG00517/eboot.bin
    python shin-tools/patch-tool.py -b build/repatch/PCSG00517/eboot.bin.elf -c eboot-utf-8.csv -e utf-8
    python shin-tools/patch-tool.py -b build/repatch/PCSG00517/eboot.bin.elf -c build/eboot-utf-16le-mapped.csv -e utf-16le
    exec bin/vita-make-fself.exe build/repatch/PCSG00517/eboot.bin.elf build/repatch/PCSG00517/eboot.bin
    printf '\x05\x02\xce\x1c\x10\x00\x00\x21' | dd of=build/repatch/PCSG00517/eboot.bin bs=1 seek=128 count=8 conv=notrunc
    rm -f build/repatch/PCSG00517/eboot.bin.elf
    
    log "Complete!"
    log "Saved to: build/repatch/"
}

case "${1:-}" in
    hou) pack_hou ;;
    sui) pack_sui ;;
    *) echo "Usage: $0 [hou|sui]"; exit 0 ;;
esac

read -p "Press ENTER to exit..."