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


_LDQ = chr(0x201C)
_RDQ = chr(0x201D)
_LSQ = chr(0x2018)
_RSQ = chr(0x2019)


def _process_inner_quotes(text: str) -> str:
    chars = list(text)
    stack = []
    pairs = []
    orphans = []

    for i, ch in enumerate(chars):
        if ch == '「':
            stack.append((i, '「'))
        elif ch == '」':
            if stack and stack[-1][1] == '「':
                open_pos, _ = stack.pop()
                pairs.append((open_pos, i))
            else:
                orphans.append(i)
        elif ch in (_LDQ, chr(0x201B)):
            stack.append((i, _LDQ))
        elif ch == _RDQ:
            if stack and stack[-1][1] in (_LDQ, '"'):
                open_pos, _ = stack.pop()
                pairs.append((open_pos, i))
            else:
                orphans.append(i)
        elif ch == '"':
            if stack and stack[-1][1] in ('"', _LDQ):
                open_pos, _ = stack.pop()
                pairs.append((open_pos, i))
            else:
                stack.append((i, '"'))
        elif ch == "'":
            if stack and stack[-1][1] in ("'", '"', _LDQ):
                open_pos, _ = stack.pop()
                pairs.append((open_pos, i))
            else:
                stack.append((i, "'"))

    for pos, _ in stack:
        orphans.append(pos)

    for open_pos, close_pos in pairs:
        if chars[open_pos] and chars[close_pos]:
            chars[open_pos] = _LDQ
            chars[close_pos] = _RDQ

    result = ''.join(c for c in chars if c)
    result = result.replace(_LSQ, _LDQ).replace(_RSQ, _RDQ)
    return result


def adjust_quotes(orig: str, trans: str) -> str:
    if not orig or not trans:
        return trans

    n_lead = 0
    while n_lead < len(orig) and orig[n_lead] == '「':
        n_lead += 1
    n_trail = 0
    while n_trail < len(orig) - n_lead and orig[-1 - n_trail] == '」':
        n_trail += 1

    if n_lead or n_trail:
        all_quotes = {'「', '」', '"', _LDQ, _RDQ, "'", _LSQ, _RSQ}
        stripped = trans
        while stripped and stripped[0] in all_quotes:
            stripped = stripped[1:]
        while stripped and stripped[-1] in all_quotes:
            stripped = stripped[:-1]

        inner = _process_inner_quotes(stripped)
        result = '「' * n_lead + inner + '」' * n_trail
    else:
        result = _process_inner_quotes(trans)

    return result.replace('。」', '」').replace('、」', '」').replace('，」', '」')

