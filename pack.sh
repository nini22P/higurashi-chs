#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RAW_DIR="$ROOT/raw"
BUILD_DIR="$ROOT/build"
BIN_DIR="$ROOT/bin"
FONT_URL="https://github.com/Warren2060/ChillRound/releases/download/v3.200/ChillRoundF_v3.200.zip"
FONT_DIR="$BUILD_DIR/ChillRoundF_v3.200"
FONT_PATH="$FONT_DIR/ChillRoundFBold.ttf"
FONT_ZIP="$BUILD_DIR/font.zip"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac
case "$OS" in
    linux) OS="linux" ;;
    darwin) OS="darwin" ;;
    mingw*|cygwin*|msys*) OS="windows" ;;
    *) echo "Unsupported OS: $OS"; exit 1 ;;
esac
echo "Platform detected: $OS/$ARCH"

declare -A TOOLS=(
    ["shin-tl"]="DCNick3/shin-translation-tools"
    ["fnt4-tool"]="nini22P/fnt4-tool"
)

get_asset_name() {
    local tool=$1
    local os=$2
    local arch=$3
    case "$tool" in
        shin-tl)
            if [ "$os" = "windows" ]; then
                echo "shin-tl-x86_64-pc-windows-msvc.zip"
            elif [ "$os" = "linux" ] && [ "$arch" = "x86_64" ]; then
                echo "shin-tl-x86_64-unknown-linux-gnu.tar.xz"
            elif [ "$os" = "linux" ] && [ "$arch" = "aarch64" ]; then
                echo "shin-tl-aarch64-unknown-linux-gnu.tar.xz"
            elif [ "$os" = "darwin" ] && [ "$arch" = "x86_64" ]; then
                echo "shin-tl-x86_64-apple-darwin.tar.xz"
            elif [ "$os" = "darwin" ] && [ "$arch" = "aarch64" ]; then
                echo "shin-tl-aarch64-apple-darwin.tar.xz"
            fi
            ;;
        fnt4-tool)
            if [ "$os" = "windows" ]; then
                echo "fnt4-tool-windows-${arch}.zip"
            elif [ "$os" = "linux" ]; then
                echo "fnt4-tool-linux-${arch}.zip"
            elif [ "$os" = "darwin" ]; then
                echo "fnt4-tool-macos-${arch}.zip"
            fi
            ;;
    esac
}

TOOL_NAMES=("shin-tl" "fnt4-tool")

log() { echo "[*] $*"; }
err() { echo "[!] $*" >&2; exit 1; }

for cmd in curl unzip tar python; do
    if ! command -v "$cmd" &>/dev/null; then
        if [ "$cmd" = "python" ] && command -v python3 &>/dev/null; then
            alias python=python3
        else
            err "Missing required command: $cmd"
        fi
    fi
done

github_latest_asset_url() {
    local repo=$1
    local asset_name=$2
    local api_url="https://api.github.com/repos/$repo/releases/latest"
    local asset_url
    asset_url=$(curl -sL "$api_url" | python -c "
import sys, json
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    if asset.get('name') == '$asset_name':
        print(asset['browser_download_url'])
        break
")
    if [ -z "$asset_url" ]; then
        err "Asset '$asset_name' not found in latest release of $repo"
    fi
    echo "$asset_url"
}

ensure_tool() {
    local tool=$1
    local repo=${TOOLS[$tool]}
    local exe_name="$tool"
    [ "$OS" = "windows" ] && exe_name="${tool}.exe"
    local dest_exe="$BIN_DIR/$exe_name"

    if [ -f "$dest_exe" ]; then
        log "Tool already installed: $dest_exe"
        return 0
    fi

    local asset_name
    asset_name=$(get_asset_name "$tool" "$OS" "$ARCH")
    if [ -z "$asset_name" ]; then
        err "No asset defined for $tool on $OS/$ARCH"
    fi

    log "Downloading $tool from GitHub..."
    local download_url
    download_url=$(github_latest_asset_url "$repo" "$asset_name")

    local tmp_dir
    tmp_dir=$(mktemp -d)
    pushd "$tmp_dir" >/dev/null

    local archive_name="$asset_name"
    curl -sL "$download_url" -o "$archive_name"

    if [[ "$archive_name" == *.zip ]]; then
        unzip -q "$archive_name"
    elif [[ "$archive_name" == *.tar.xz ]]; then
        tar -xf "$archive_name"
    else
        err "Unknown archive type: $archive_name"
    fi

    local found
    found=$(find . -type f -name "$exe_name" -o -name "$tool" | head -1)
    if [ -z "$found" ]; then
        err "Executable not found in archive"
    fi
    mkdir -p "$BIN_DIR"
    cp "$found" "$dest_exe"
    popd >/dev/null
    rm -rf "$tmp_dir"

    if [ "$OS" != "windows" ]; then
        chmod +x "$dest_exe"
    fi
    log "Installed $tool -> $dest_exe"
}

download_font() {
    if [ -f "$FONT_PATH" ]; then
        log "Font already exists: $FONT_PATH"
        return
    fi
    log "Downloading font..."
    mkdir -p "$BUILD_DIR"
    curl -sL "$FONT_URL" -o "$FONT_ZIP"
    unzip -q "$FONT_ZIP" -d "$BUILD_DIR"
    rm "$FONT_ZIP"
}

extract_raw_roms() {
    for name in data patch append; do
        target="$RAW_DIR/$name"
        rom="$RAW_DIR/$name.rom"
        if [ -d "$target" ]; then
            continue
        fi
        if [ -f "$rom" ]; then
            log "Extracting $rom ..."
            "$BIN_DIR/shin-tl" rom extract "$rom" "$target"
        else
            log "Missing $rom, skipping extraction."
        fi
    done
}

prepare_patch_dir() {
    if [ ! -d "$BUILD_DIR/patch" ]; then
        cp -r "$RAW_DIR/patch" "$BUILD_DIR/patch"
    fi
}

run_cmd() {
    local cmd=$1
    shift
    if [ "$OS" = "windows" ] && [ ! -f "$cmd" ] && [ -f "${cmd}.exe" ]; then
        cmd="${cmd}.exe"
    fi
    echo "+ $cmd $*"
    "$cmd" "$@"
}

main() {
    mkdir -p "$RAW_DIR" "$BUILD_DIR" "$BUILD_DIR/romfs" "$BIN_DIR"

    for tool in "${TOOL_NAMES[@]}"; do
        ensure_tool "$tool"
    done

    download_font

    extract_raw_roms

    prepare_patch_dir

    run_cmd python "$ROOT/shin-tools/script-tool.py" import --main main.csv, --text higurashi-hou.csv --suffix hou,sui
    run_cmd python "$ROOT/shin-tools/mapping-tool.py" mapping-config.json

    run_cmd "$BIN_DIR/shin-tl" snr rewrite higurashi-hou-v2 "$RAW_DIR/patch/main.snr" "$BUILD_DIR/main-mapped.csv" "$BUILD_DIR/patch/main.snr"
    run_cmd "$BIN_DIR/fnt4-tool" rebuild "$RAW_DIR/data/newrodin.fnt" "$BUILD_DIR/patch/newrodin.fnt" "$FONT_PATH" -s 102 --letter-spacing 2 -c "$BUILD_DIR/mapping.toml"

    run_cmd "$BIN_DIR/shin-tl" rom create --rom-version higurashi-hou-v2 "$BUILD_DIR/patch" "$BUILD_DIR/romfs/patch.rom"

    log "Build Complete!"
    read -p "Press ENTER to exit..."
}

main "$@"