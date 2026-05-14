import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import strip_all, has_japanese
from rapidfuzz import fuzz as rapidfuzz_fuzz
from collections import defaultdict


def verify_match(a: str, b: str) -> float:
    if not a or not b:
        return 0.0

    la, lb = len(a), len(b)
    short, long = (a, b) if la < lb else (b, a)

    if len(long) / max(len(short), 1) > 3:
        return 0.0

    if a == b:
        return 1.0

    if short in long:
        ratio = len(short) / len(long)
        is_prefix = long.startswith(short)
        if len(short) >= 3:
            min_ratio = 0.5 if is_prefix else 0.3
            if ratio >= min_ratio:
                return 0.9
        if len(short) == 2:
            min_ratio = 0.6 if is_prefix else 0.5
            if ratio >= min_ratio:
                return 0.85

    if la > 3 and lb > 3:
        short_len = min(la, lb)
        long_len = max(la, lb)
        len_ratio = short_len / long_len

        sim = rapidfuzz_fuzz.ratio(a, b) / 100.0

        if len_ratio < 0.6:
            return sim if sim >= 0.8 else 0.0
        if len_ratio >= 0.9:
            return sim if sim >= 0.85 else 0.0
        return sim if sim >= 0.7 else 0.0

    return 0.0


def build_fuzzy_index(index):
    """
    对翻译 index 的所有 key 建立 n-gram 倒排索引 + 短文本精确索引。
    返回 (gram_index, short_index, all_entries)

    all_entries: [(key_stripped, orig_key, trans_orig, trans_zh), ...]
    gram_index:  {gram: [entry_idx, ...]}
    short_index: {key_stripped: [entry_idx, ...]}
    """
    all_entries = []
    gram_index = defaultdict(list)
    short_index = defaultdict(list)

    for key, items in index.items():
        for trans_orig, trans_zh in items:
            joined = strip_all("".join(trans_orig))
            if not joined:
                continue

            entry_idx = len(all_entries)
            all_entries.append((joined, key, trans_orig, trans_zh))

            if len(joined) >= 4:
                seen = set()
                for pos in range(0, len(joined) - 3, 2):
                    gram = joined[pos:pos + 4]
                    if gram not in seen:
                        gram_index[gram].append(entry_idx)
                        seen.add(gram)
            else:
                short_index[joined].append(entry_idx)

    return gram_index, short_index, all_entries


def find_candidates(text, gram_index, short_index, all_entries, max_candidates=200):
    """
    用 n-gram 投票快速找出与 text 可能匹配的翻译条目。
    返回 [(entry_idx, vote_count), ...] 按投票降序排列。
    """
    key = strip_all(text)
    if not key:
        return []

    results = []

    # 短文本精确匹配
    if len(key) < 8:
        for idx in short_index.get(key, []):
            results.append((idx, 100))  # 精确匹配高优先级

    # n-gram 投票
    if len(key) >= 4:
        query_grams = set()
        for pos in range(0, len(key) - 3, 2):
            query_grams.add(key[pos:pos + 4])

        votes = defaultdict(int)
        for gram in query_grams:
            for idx in gram_index.get(gram, []):
                votes[idx] += 1

        if votes:
            max_votes = max(votes.values())
            min_votes = max(1, max_votes // 4)
            gram_cnt = len(query_grams)
            cap = max(max_candidates, 1000 // max(1, gram_cnt))

            voted = sorted(
                [(idx, v) for idx, v in votes.items() if v >= min_votes],
                key=lambda x: -x[1]
            )[:cap]
            results.extend(voted)

    # 去重，保留最高投票
    seen = {}
    for idx, v in results:
        if idx not in seen or v > seen[idx]:
            seen[idx] = v
    return sorted(seen.items(), key=lambda x: -x[1])


_CONCAT_FALLBACK_MAX_SCORE = 0.95
_CONCAT_MIN_COVERAGE = 0.8
_CONCAT_MIN_SPAN_LEN = 3
_CONCAT_PARTIAL_MIN = 90.0


def _try_concat_cover(matched_stripped, candidates, all_entries):
    """
    严格的"分段拼接覆盖"回退：
      - 用 rapidfuzz partial_ratio_alignment 找 entry_key 在 matched 中的最佳对齐窗口
      - partial_ratio 分数必须 >= _CONCAT_PARTIAL_MIN（短串自动退化为完全等同）
      - 每条 entry_key 长度 >= _CONCAT_MIN_SPAN_LEN
      - 至少 2 条候选，互不重叠
      - 总覆盖率 >= _CONCAT_MIN_COVERAGE
    返回拼接好的中文字符串，或 None。
    """
    if not matched_stripped:
        return None
    L = len(matched_stripped)
    if L < 2 * _CONCAT_MIN_SPAN_LEN:
        return None

    spans = []
    seen_pos = set()
    for entry_idx, _ in candidates:
        entry_key, _, _, trans_zh = all_entries[entry_idx]
        if not entry_key:
            continue
        ek_len = len(entry_key)
        if ek_len < _CONCAT_MIN_SPAN_LEN or ek_len >= L:
            continue
        align = rapidfuzz_fuzz.partial_ratio_alignment(
            entry_key, matched_stripped, score_cutoff=_CONCAT_PARTIAL_MIN
        )
        if align is None or align.score < _CONCAT_PARTIAL_MIN:
            continue
        s = align.dest_start
        e = align.dest_end
        if e - s < _CONCAT_MIN_SPAN_LEN:
            continue
        # 同位置的多条 entry 仅保留一份（避免重复译文堆叠）
        key_pos = (s, e)
        if key_pos in seen_pos:
            continue
        seen_pos.add(key_pos)
        spans.append((s, e, trans_zh))

    if len(spans) < 2:
        return None

    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    chosen = []
    cur_end = 0
    for s, e, tz in spans:
        if s >= cur_end:
            chosen.append((s, e, tz))
            cur_end = e

    if len(chosen) < 2:
        return None

    covered = sum(e - s for s, e, _ in chosen)
    if covered / L < _CONCAT_MIN_COVERAGE:
        return None

    return "".join("".join(tz) for _, _, tz in chosen)


def align_and_translate_fuzzy(orig_segs, index, window=8, max_span=4, max_candidates=300, _cache={}):
    cache_key = id(index)
    if cache_key not in _cache:
        _cache[cache_key] = build_fuzzy_index(index)
    gram_index, short_index, all_entries = _cache[cache_key]

    n = len(orig_segs)
    result: list = [None] * n
    src = [strip_all(x) for x in orig_segs]

    i = 0
    while i < n:
        cur = src[i]

        if not has_japanese(cur):
            i += 1
            continue

        best_align = None
        best_align_score = 0

        for j in range(i, min(i + window, n)):
            for span in range(1, min(max_span + 1, n - j + 1)):
                cand = "".join(src[j:j + span])
                if not cand:
                    continue
                score = verify_match(cur, cand)
                if score > best_align_score:
                    best_align_score = score
                    best_align = (j, span, cand)

        if not best_align:
            i += 1
            continue

        align_idx, align_span, matched = best_align

        # 阶段2：用 n-gram 索引快速查找匹配翻译
        candidates = find_candidates(matched, gram_index, short_index, all_entries, max_candidates)

        best_entry = None
        best_score = 0

        for entry_idx, _ in candidates:
            entry_key, orig_key, trans_orig, trans_zh = all_entries[entry_idx]
            score = verify_match(entry_key, strip_all(matched))
            if score > best_score:
                best_score = score
                best_entry = (trans_orig, trans_zh)

        # 严格回退：input 单段且原算法信心不足时，尝试拼接多条严格子串覆盖
        if align_span == 1 and best_score < _CONCAT_FALLBACK_MAX_SCORE:
            concat = _try_concat_cover(matched, candidates, all_entries)
            if concat:
                result[i] = concat
                i += 1
                continue

        if not best_entry:
            i += 1
            continue

        trans_orig, trans_zh = best_entry
        m = len(trans_orig)

        for k in range(m):
            if i + k < n:
                result[i + k] = trans_zh[k]

        # 根据匹配的跨度决定步进
        step = max(align_span, m)
        i += step

    return result