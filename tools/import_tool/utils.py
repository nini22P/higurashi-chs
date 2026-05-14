from collections import defaultdict
from functools import lru_cache
import re
import os
import pandas as pd

SEP = "⭕"

_RE_AT_WORD = re.compile(r'@\w+')
_RE_NON_CJK = re.compile(r'[^\w\u4e00-\u9fff\u3040-\u30ff]')
_RE_HUMAN_RUBY = re.compile(r'\[([^|\]]+)\|([^\]]+)\]')


@lru_cache(maxsize=65536)
def normalize(s: str) -> str:
    if not s:
        return ""
    s = _RE_HUMAN_RUBY.sub(r'\2', s)
    return s.replace("。」", "」").strip()


@lru_cache(maxsize=65536)
def strip_all(s: str) -> str:
    if not s:
        return ""
    s = _RE_HUMAN_RUBY.sub(r'\2', s)
    s = _RE_AT_WORD.sub('', s)
    s = _RE_NON_CJK.sub('', s)
    return s.strip()


def has_japanese(text: str) -> bool:
    return bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', text))


def load_translation(folder):
    index = defaultdict(list)

    for file in os.listdir(folder):
        if not file.endswith(".csv"):
            continue

        df = pd.read_csv(os.path.join(folder, file), dtype=str).fillna("")
        if "original" not in df.columns or "translation" not in df.columns:
            continue

        for text, trans in zip(df["original"], df["translation"]):
            if not text or not trans:
                continue

            orig_segs = [normalize(x) for x in text.split(SEP)]
            trans_segs = trans.split(SEP)

            if len(orig_segs) != len(trans_segs):
                continue

            index[orig_segs[0]].append((tuple(orig_segs), trans_segs))

    for k in index:
        index[k].sort(key=lambda x: -len(x[0]))

    return index



