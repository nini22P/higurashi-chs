#!/usr/bin/env python3
"""Split binary.csv by platform for patch-tool.py consumption."""
import csv
import argparse
import os

OUT_FIELDS = ['offset', 'length', 'text', 'translation']


def main():
    parser = argparse.ArgumentParser(description='Split binary.csv by platform')
    parser.add_argument('csv', help='binary.csv path')
    parser.add_argument('platform', choices=['hou', 'sui'],
                        help='target platform')
    parser.add_argument('-o', '--output', required=True,
                        help='output CSV path')
    args = parser.parse_args()

    offset_col = f'offset_{args.platform}'
    length_col = f'length_{args.platform}'

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    rows = []
    with open(args.csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            offsets = row.get(offset_col, '').strip()
            length = row.get(length_col, '').strip()
            text = row.get('text', '')
            translation = row.get('translation', '').strip()

            if not offsets or not length:
                continue

            for off in offsets.split('|'):
                off = off.strip()
                if not off:
                    continue
                rows.append({
                    'offset': int(off, 16),
                    'length': length,
                    'text': text,
                    'translation': translation,
                })

    rows.sort(key=lambda r: r['offset'])

    with open(args.output, 'w', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=OUT_FIELDS)
        writer.writeheader()
        for r in rows:
            r['offset'] = hex(r['offset'])
            writer.writerow(r)

    print(f'Wrote {len(rows)} rows to {args.output}')


if __name__ == '__main__':
    main()
