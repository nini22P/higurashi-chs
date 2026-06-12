#!/usr/bin/env python3
"""One-time merge: exefs.csv + eboot-utf-16le.csv → binary.csv."""
import csv

FIELDS = ['offset_hou', 'length_hou', 'offset_sui', 'length_sui', 'text', 'translation']


def load(path):
    entries = {}
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get('text', '').strip().replace('\r\n', '\n')
            if not t:
                continue
            if t not in entries:
                entries[t] = {
                    'offsets': [],
                    'length': row.get('length', ''),
                    'translation': row.get('translation', '').strip(),
                }
            entries[t]['offsets'].append(row['offset'])
    return entries


def main():
    hou = load('exefs.csv')
    sui = load('eboot-utf-16le.csv')

    with open('binary.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for text in sorted(set(hou) | set(sui)):
            row = {'text': text, 'translation': ''}

            if text in hou:
                e = hou[text]
                row['offset_hou'] = '|'.join(e['offsets'])
                row['length_hou'] = e['length']
                if e['translation']:
                    row['translation'] = e['translation']

            if text in sui:
                e = sui[text]
                row['offset_sui'] = '|'.join(e['offsets'])
                row['length_sui'] = e['length']
                if e['translation'] and not row['translation']:
                    row['translation'] = e['translation']

            w.writerow(row)

    print(f'Done: {len(set(hou) | set(sui))} rows -> binary.csv')


if __name__ == '__main__':
    main()
