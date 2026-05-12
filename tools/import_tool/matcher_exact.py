import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import normalize

_OVERRIDE_MARGIN = 2


def align_and_translate(orig_segs, index, max_candidates=6, lookahead=2):
    n = len(orig_segs)
    result = [None] * n
    norm_orig = [normalize(x) for x in orig_segs]

    i = 0
    while i < n:
        key = norm_orig[i]

        if key not in index:
            i += 1
            continue

        candidates = []
        for trans_orig, trans_zh in index[key]:
            m = len(trans_orig)
            if i + m > n:
                continue
            if tuple(norm_orig[i:i + m]) != trans_orig:
                continue
            candidates.append((trans_orig, trans_zh))
            if len(candidates) >= max_candidates:
                break

        if not candidates:
            i += 1
            continue

        chosen = _choose_candidate(candidates, norm_orig, i, n, index, lookahead)

        trans_orig, trans_zh = chosen
        m = len(trans_orig)

        for k in range(m):
            result[i + k] = trans_zh[k]

        i += m

    return result


def _choose_candidate(candidates, norm_orig, i, n, index, lookahead):
    if len(candidates) == 1:
        return candidates[0]

    default = candidates[0]
    default_m = len(default[0])
    default_score = _lookahead_score(norm_orig, i + default_m, n, index, lookahead)

    best = default
    best_m = default_m
    best_score = default_score

    for cand in candidates[1:]:
        m = len(cand[0])
        if m == best_m:
            continue
        score = _lookahead_score(norm_orig, i + m, n, index, lookahead)
        if score >= best_score + _OVERRIDE_MARGIN:
            best = cand
            best_m = m
            best_score = score

    return best


def _lookahead_score(norm_orig, start, n, index, lookahead):
    if start >= n:
        return lookahead

    score = 0
    j = start
    steps = 0
    while j < n and steps < lookahead:
        nk = norm_orig[j]
        if nk in index:
            ok = False
            for trans_orig, _ in index[nk]:
                m = len(trans_orig)
                if j + m <= n and tuple(norm_orig[j:j + m]) == trans_orig:
                    ok = True
                    break
            score += 1 if ok else -2
        j += 1
        steps += 1
    return score