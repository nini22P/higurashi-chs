import argparse
import pandas as pd
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import *
from matcher_exact import align_and_translate
from matcher_fuzzy import align_and_translate_fuzzy

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_import = subparsers.add_parser("import")
    parser_import.add_argument("target_csv")
    parser_import.add_argument("translate_folder")
    parser_import.add_argument("name_csv")
    parser_import.add_argument("--fuzzy", action="store_true")

    args = parser.parse_args()

    df = pd.read_csv(args.target_csv, dtype=str).fillna("")
    print("Loading translations")
    index = load_translation(args.translate_folder)
    print("Loading names")
    name_dict = load_names(args.name_csv)

    exact_total = 0
    exact_matched = 0

    fuzzy_total = 0
    fuzzy_matched = 0

    blocks = split_by_saveinfo(df) if args.fuzzy else [list(df.index)]

    target_block = None

    if args.fuzzy:
        blocks = [b for b in blocks if should_fuzzy_process_block(df, b)]
        target_block = find_first_need_fuzzy_block(df, blocks)

        if not target_block:
            print("No fuzzy-needed block found.")
            return

        start_row = df.at[target_block[0], "index"]
        end_row = df.at[target_block[-1], "index"]

        print("Block Range")
        print(f"Start : {args.target_csv}:{start_row}")
        print(f"End   : {args.target_csv}:{end_row}")
        print(f"Count : {len(target_block)}\n")


    rows_to_process = target_block if args.fuzzy else df.index

    for i in rows_to_process:
        row_index = int(df.at[i, "index"] or 0)

        if row_index < MIN_INDEX:
            continue

        text = df.at[i, "s"]
        if not text:
            continue

        name, orig_segs = extract_segments_and_name(text)
        if not orig_segs:
            continue

        exact_total += 1

        translated_segs = align_and_translate(orig_segs, index)

        if any(translated_segs):
            df.at[i, "translated"] = rebuild_text(text, translated_segs, name_dict)
            exact_matched += 1

    if args.fuzzy and target_block:
        print("\nRunning fuzzy matching...\n")

        for idx in target_block:
            row_index = int(df.at[idx, "index"] or 0)

            if row_index < MIN_INDEX:
                continue
            if df.at[idx, "translated"]:
                continue

            text = df.at[idx, "s"]
            if not text:
                continue

            name, orig_segs = extract_segments_and_name(text)
            if not orig_segs:
                continue

            fuzzy_total += 1

            translated_segs = align_and_translate_fuzzy(orig_segs, index)

            if any(translated_segs):
                df.at[idx, "translated"] = rebuild_text(
                    text, translated_segs, name_dict
                )
                fuzzy_matched += 1

    df.to_csv(args.target_csv, index=False, encoding="utf-8")

    print("Translation Stats")

    print(f"[Exact]")
    print(f"  total   : {exact_total}")
    print(f"  matched : {exact_matched}")
    if exact_total:
        print(f"  rate    : {exact_matched/exact_total*100:.2f}%")

    if args.fuzzy:
        print(f"\n[Fuzzy]")
        print(f"  total   : {fuzzy_total}")
        print(f"  matched : {fuzzy_matched}")
        if fuzzy_total:
            print(f"  rate    : {fuzzy_matched/fuzzy_total*100:.2f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()