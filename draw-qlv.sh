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

needs_unpack=0
while IFS= read -r qid; do
  qid="${qid%$'\r'}"
  [ -n "$qid" ] || continue
  if [ ! -f "$HOU_IN/$qid/$qid.png" ]; then
    needs_unpack=1
    break
  fi
done < <(python -c "
import csv
with open('$CSV', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if r['translation'].strip():
            print(r['file'])
")

if [ "$needs_unpack" -eq 1 ]; then
  python shin-tools/txa_tool.py unpack -i "$TXA_SRC" -o "$HOU_IN"
fi

python tools/draw-qlv.py --font "$FONT" --csv "$CSV" --hou-in "$HOU_IN" --hou-out "$HOU_OUT" --sui-out "$SUI_OUT"
