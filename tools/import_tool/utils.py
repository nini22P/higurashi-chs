from rapidfuzz import fuzz as rapidfuzz_fuzz
from collections import defaultdict
from functools import lru_cache
import re
import os
import pandas as pd

MIN_INDEX = 2952

SEP = "::"

_RE_RUBY = re.compile(r'@b([^@.]+)\.@<([^@>]+)@>')
_RE_CODE = re.compile(r'(@[abcosuvwxz][^@\n\r.]*\.|@[-+/<>[\]ekrty{|}]|@[a-zA-Z])')
_RE_TO_GAME = re.compile(r'\[([^|\]]+)\|([^\]]+)\]')

@lru_cache(maxsize=65536)
def normalize(s: str) -> str:
    if not s:
        return ""
    return s.replace("。」", "」").strip()


def to_human(text):
    return _RE_RUBY.sub(r'[\1|\2]', text)


def to_game(text):
    return _RE_TO_GAME.sub(r'@b\1.@<\2@>', text)


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return rapidfuzz_fuzz.ratio(a, b) / 100.0


_RE_AT_WORD = re.compile(r'@\w+')
_RE_NON_CJK = re.compile(r'[^\w\u4e00-\u9fff\u3040-\u30ff]')

@lru_cache(maxsize=65536)
def strip_all(s: str) -> str:
    if not s:
        return ""
    s = _RE_AT_WORD.sub('', s)
    s = _RE_NON_CJK.sub('', s)
    return s.strip()

def has_name(parts):
    if '@r' not in parts:
        return False
    idx = parts.index('@r')
    if idx == 0:
        return False
    return bool(parts[idx - 1].strip())

def has_japanese(text: str) -> bool:
    return bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', text))

def extract_segments_and_name(text):
    parts = _RE_CODE.split(to_human(str(text)))

    name = ""
    if has_name(parts):
        name = parts[parts.index('@r') - 1].strip()

    segs = []
    start = parts.index('@r') + 1 if name else 0

    for p in parts[start:]:
        if not p:
            continue
        if not _RE_CODE.match(p) and p.strip():
            segs.append(p.strip())

    return name, segs

def rebuild_text(orig_text, translated_segs, name_dict):
    parts = _RE_CODE.split(to_human(orig_text))
    result = []

    seg_idx = 0
    start = 0

    if has_name(parts):
        r_idx = parts.index('@r')

        result.extend(parts[:r_idx-1])

        orig_name = parts[r_idx-1]
        stripped = orig_name.strip()
        new_name = name_dict.get(stripped, stripped)

        result.append(orig_name.replace(stripped, to_game(new_name)))
        result.append(parts[r_idx])

        start = r_idx + 1

    for p in parts[start:]:
        if not p:
            continue

        if _RE_CODE.match(p):
            result.append(p)
        elif p.strip():
            if seg_idx < len(translated_segs) and translated_segs[seg_idx]:
                result.append(p.replace(p.strip(), to_game(translated_segs[seg_idx])))
            else:
                result.append(to_game(p))
            seg_idx += 1
        else:
            result.append(p)

    return "".join(result)

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

def load_names(path):
    if not path:
        return {}

    df = pd.read_csv(path, dtype=str).fillna("")
    if "text" not in df.columns or "translation" not in df.columns:
        return {}
        
    return {
        text.strip(): trans.strip()
        for text, trans in zip(df["text"], df["translation"])
        if text and trans
    }


def split_by_saveinfo(df, min_index=MIN_INDEX):
    saveinfo_indices = []
    valid_indices = []
    
    indices = df.index
    row_indices = df.get("index", pd.Series(["0"] * len(df)))
    sources = df.get("source", pd.Series([""] * len(df)))

    for idx, row_idx_val, source_val in zip(indices, row_indices, sources):
        row_index = int(row_idx_val or 0)
        if row_index < min_index:
            continue
            
        valid_indices.append(idx)
        source = str(source_val).lower()
        if "saveinfo" in source:
            saveinfo_indices.append(idx)

    if not saveinfo_indices:
        return [valid_indices]

    anchors = []
    group = [saveinfo_indices[0]]

    for i in range(1, len(saveinfo_indices)):
        if saveinfo_indices[i] == saveinfo_indices[i - 1] + 1:
            group.append(saveinfo_indices[i])
        else:
            anchors.append(group)
            group = [saveinfo_indices[i]]

    anchors.append(group)

    blocks = []
    start = valid_indices[0] if valid_indices else 0

    for group in anchors:
        end = group[0]
        block = list(range(start, end))
        if block:
            blocks.append(block)
        start = group[-1] + 1

    if valid_indices and start <= valid_indices[-1]:
        blocks.append(list(range(start, valid_indices[-1] + 1)))

    return blocks


def should_fuzzy_process_block(df, block):
    has_any = False
    has_empty = False

    for idx in block:
        text = df.at[idx, "translated"]

        if text and str(text).strip():
            has_any = True
        else:
            has_empty = True

        if has_any and has_empty:
            return True

    return False


def find_first_need_fuzzy_block(df, blocks):
    for block in blocks:
        for idx in block:
            if df.at[idx, "translated"]:
                continue

            text = df.at[idx, "s"]
            if not text:
                continue

            _, segs = extract_segments_and_name(text)
            if segs:
                return block
    return None