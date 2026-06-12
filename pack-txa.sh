#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

GAME="${1:-}"
case "$GAME" in
  hou) VERSION=2; TXA_SEARCH=(raw/hou/patch raw/hou/data) ;;
  sui) VERSION=0; TXA_SEARCH=(raw/sui/data) ;;
  *) echo "Usage: $0 [hou|sui]"; exit 1 ;;
esac

SRC_DIR="assets/txa-${GAME}"
BUILD_DIR="build/txa-${GAME}"
OUT_DIR="build/patch-${GAME}"

mkdir -p "$BUILD_DIR" "$OUT_DIR"

[ -d "$SRC_DIR" ] || {
  echo "[*] $SRC_DIR/ not found, skip"
  exit 0
}

if find "$SRC_DIR" -maxdepth 1 -name '*.png' -type f | read; then
  echo "[!] .png files must not be placed directly under $SRC_DIR/" >&2
  exit 1
fi

find_src() {
  local txa_path=$1
  local dir
  for dir in "${TXA_SEARCH[@]}"; do
    local f="${dir}/${txa_path}.txa"
    [[ -f "$f" ]] && { echo "$f"; return 0; }
  done
  return 1
}

resolve_txa_from_path() {
  local rel=$1
  IFS='/' read -ra parts <<< "$rel"

  local i j txa
  for ((i=${#parts[@]}-1; i>=1; i--)); do
    txa="${parts[0]}"
    for ((j=1; j<i; j++)); do
      txa+="/${parts[j]}"
    done

    if find_src "$txa" >/dev/null 2>&1; then
      echo "$txa"
      return 0
    fi
  done

  return 1
}

add_unique() {
  local val=$1
  local x
  for x in "${repack_list[@]}"; do
    [[ "$x" == "$val" ]] && return
  done
  repack_list+=("$val")
}

repack_list=()
error=0

while IFS= read -r -d '' file; do
  rel="${file#$SRC_DIR/}"

  if txa=$(resolve_txa_from_path "$rel"); then
    add_unique "$txa"
  else
    echo "[!] Cannot resolve source txa for: $rel" >&2
    error=1
  fi

done < <(find "$SRC_DIR" -name '*.png' -type f -print0 2>/dev/null)

((error)) && exit 1

if ((${#repack_list[@]} == 0)); then
  echo "[*] No TXA requires repacking under $SRC_DIR/"
  exit 0
fi

echo "[*] TXA to repack (${#repack_list[@]}): ${repack_list[*]}"

# rm -rf "$BUILD_DIR"

for txa in "${repack_list[@]}"; do
  src=$(find_src "$txa")
  echo "[v${VERSION}] Unpacking ${txa}.txa"
  python shin-tools/txa-tool.py unpack -i "$src" -o "$BUILD_DIR/$txa"
done

echo "[*] Coping files..."
cp -r "$SRC_DIR/." "$BUILD_DIR/"

echo "[*] Packing TXA..."
python shin-tools/txa-tool.py pack -i "$BUILD_DIR" -o "$OUT_DIR" -v "$VERSION"

echo "[*] Done. Output saved to $OUT_DIR/"