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

    args = parser.parse_args()

    df = pd.read_csv(args.target_csv, dtype=str).fillna("")
    print("Loading translations")
    index = load_translation(args.translate_folder)

    total_rows = 0
    exact_rows = 0
    fuzzy_rows = 0
    unmatched_rows = 0

    msgset_rows = [i for i in df.index if df.at[i, "type"] == "msgset"]

    for i in msgset_rows:
        text = df.at[i, "text"]
        if not text:
            continue
        orig_segs = text.split(SEP)
        orig_segs = [s for s in orig_segs if s]
        if not orig_segs:
            continue

        total_rows += 1

        exact_segs = align_and_translate(orig_segs, index)
        fuzzy_segs = align_and_translate_fuzzy(orig_segs, index)
        has_fuzzy = any(f and not e for e, f in zip(exact_segs, fuzzy_segs))
        has_exact = any(exact_segs)

        if has_fuzzy:
            fuzzy_rows += 1
            combined = [f if (f and not e) else e for e, f in zip(exact_segs, fuzzy_segs)]
            adjusted = [adjust_quotes(o, c or o) for o, c in zip(orig_segs, combined)]
            df.at[i, "translated"] = ""
            df.at[i, "temp"] = SEP.join(adjusted)
        elif has_exact:
            adjusted = [adjust_quotes(o, t or o) for o, t in zip(orig_segs, exact_segs)]
            all_matched = all(exact_segs)
            if all_matched:
                exact_rows += 1
                df.at[i, "translated"] = SEP.join(adjusted)
            else:
                df.at[i, "translated"] = ""
                df.at[i, "temp"] = SEP.join(adjusted)
        else:
            unmatched_rows += 1

    df.to_csv(args.target_csv, index=False, encoding="utf-8")

    print("Translation Stats")
    print(f"  total       : {total_rows}")
    print(f"  exact       : {exact_rows}")
    print(f"  fuzzy       : {fuzzy_rows}")
    print(f"  unmatched   : {unmatched_rows}")

    print("\nDone.")


if __name__ == "__main__":
    main()
