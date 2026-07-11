#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

FONT="assets/font/NotoSansCJKsc-Black.otf"
CSV="qlv.csv"
TXA_SRC="raw/hou/data/quiz"
HOU_IN="build/txa-hou-orig/quiz"
HOU_OUT="assets/txa-hou/quiz"
SUI_OUT="assets/txa-sui/quiz"

mkdir -p "$HOU_IN" "$HOU_OUT"

python -c "
import csv, os
with open('$CSV', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if r['translation'].strip():
            print(r['file'])
" | while IFS= read -r qid; do
  qid="${qid%$'\r'}"
  [ -n "$qid" ] || continue
  png="$HOU_IN/$qid/$qid.png"
  if [ ! -f "$png" ]; then
    mkdir -p "$HOU_IN/$qid"
    python shin-tools/txa_tool.py unpack -i "$TXA_SRC/$qid.txa" -o "$HOU_IN/$qid"
  fi
done

python tools/draw-qlv.py --font "$FONT" --csv "$CSV" --hou-in "$HOU_IN" --hou-out "$HOU_OUT" --sui-out "$SUI_OUT"
