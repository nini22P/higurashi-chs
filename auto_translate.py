#!/usr/bin/env python3
"""
辅助翻译脚本：用 ep01/ep08/ep09/ep10 自动匹配并翻译 extracted.txt。

匹配策略（单遍倒排索引）：
1. 将 extracted.txt 按 @k 拆成片段
2. 从每个片段提取纯对话文本（去掉 @r 前的人名和所有 @annotation）
3. 对纯对话建立 4-gram 倒排索引
4. 对每个翻译条目，用 4-gram 查询 + 子串/模糊匹配验证
5. 重构输出：保留人名和 @annotation，只替换对话部分

关键规则：
- 第一个 @r 前面的是人名 → 保留不翻译
- 所有 @annotation（@r, @k, @vS20/...等）都是演出指令 → 匹配时忽略
- @k 是句子分隔符，按 @k 拆成独立片段分别匹配

用法:
  python auto_translate.py
  输入: extracted.txt (由 extract.py 生成)
        ep01.csv / ep08.csv / ep09.csv / ep10.csv (翻译对照文件)
  输出: higurashi-hou-translated.csv (含 temp/translated 列)
"""

import csv
import os
import re
import sys
from difflib import SequenceMatcher
from collections import defaultdict, deque, Counter

# 确保 stdout 支持 UTF-8（Windows GBK 兼容）
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

EXTRACTED = "extract/extracted.txt"
TRANS_CSVS = [f"translate_cn/ep{i:02d}.csv" for i in range(1, 11)]
HIGU_CSV = "higurashi-hou.csv"
OUTPUT_CSV = "higurashi-hou-translated.csv"
SEPARATOR = "------"
FUZZY_THRESHOLD = 0.7
CONTEXT_WINDOW = 3           # 行级上下文窗口：平局时参考前 N 行的选中条目

# 匹配所有 @annotation: 只允许游戏实际使用的标注字符（字母、数字、标点符号等）
# 明确列出允许字符而非反向排除，避免误吞引号等非日文字符
ANNOT_RE = re.compile(r"@[a-zA-Z0-9_/.\|<>\[\]-]+")
# 只检测日文独有的假名（平假名/片假名），不包含中日共享汉字
JAPANESE_RE = re.compile(r'[ぁ-ゖゝゞゟァ-ヺーヽヾヿ]')


def strip_punct(text: str) -> str:
    """去掉标点符号（仅用于匹配时忽略标点差异）"""
    return re.sub(r'[！？!?。、，「」""『』（）\(\)　\t\n\r・…—…ー〜～·･]', '', text)


def convert_outer_quotes(text: str) -> str:
    """将翻译文本最外层的引号替换为日式引号「」
    引号可能成对出现，也可能单独出现（跨 @k 片段配对时）。
    同时清理「」内部多余的外层""（如 「""内容""」 → 「内容」）。
    """
    # 左引号 → 「（ASCII 双引号或 Unicode 左弯引号）
    for q in ('"', '“'):
        if text.startswith(q):
            text = '「' + text[len(q):]
            break
    # 右引号 → 」 （ASCII 双引号或 Unicode 右弯引号）
    for q in ('"', '”'):
        if text.endswith(q):
            text = text[:-len(q)] + '」'
            break
    # 去除「」内多余的引号（CSV 中部分条目同时有「」和 ""，如「""内容""」）
    if text.startswith('「') and text.endswith('」'):
        inner = text[1:-1]
        cleaned = inner.lstrip('"').rstrip('"')
        if cleaned != inner:
            text = '「' + cleaned + '」'
    return text


def strip_all(text: str) -> str:
    """去掉所有干扰匹配的内容：标点 + @annotation"""
    cleaned = ANNOT_RE.sub("", text)
    return strip_punct(cleaned).strip()


def extract_dialogue(segment: str) -> str:
    """
    提取片段中的纯对话文本（用于匹配）。

    规则：
    - 第一个 @r 前面的是角色名 → 去掉
    - 所有 @annotation 都是演出指令 → 去掉
    - 剩下的就是纯对话文本
    """
    first_r = segment.find('@r')
    after_name = segment[first_r:] if first_r >= 0 else segment
    return ANNOT_RE.sub("", after_name).strip()


def split_by_annotations(content: str) -> list[str]:
    """
    按所有 @annotation 边界分段（不只是 @k）。

    每个分段自包含其前导注解，可直接用于 reconstruct_segment。
    角色名前缀（第一个 @r 之前）归入第一个分段。
    """
    first_r = content.find('@r')
    if first_r >= 0:
        name_prefix = content[:first_r]
        rest = content[first_r:]
    else:
        name_prefix = ''
        rest = content

    segments = []
    last_end = 0
    pending_annot = ''
    is_first = True

    for m in ANNOT_RE.finditer(rest):
        if m.start() > last_end:
            dialogue = rest[last_end:m.start()]
            seg_raw = pending_annot + dialogue
            if seg_raw.strip():
                if is_first and name_prefix:
                    seg_raw = name_prefix + seg_raw
                    is_first = False
                segments.append(seg_raw)
                is_first = False
            pending_annot = ''
        pending_annot += m.group()
        last_end = m.end()

    if last_end < len(rest):
        dialogue = rest[last_end:]
        seg_raw = pending_annot + dialogue
        if seg_raw.strip():
            if is_first and name_prefix:
                seg_raw = name_prefix + seg_raw
            segments.append(seg_raw)

    # 没有任何 annotation 的纯文字行
    if not segments and content.strip():
        segments.append(content)

    return segments


def reconstruct_segment(segment: str, translations: list[str],
                        name_map: dict[str, str] = None) -> str:
    """
    重构片段：保留角色名和 @annotation，对话部分替换为翻译。
    translations 按翻译文件条目顺序合并。
    name_map: 角色名翻译字典（name-translated.csv），做精确替换。
    """
    combined = "".join(translations)
    first_r = segment.find('@r')
    if first_r < 0:
        # 没有 @r，但可能有其他 @annotation（如 @vS01/...）
        name = ""
        after_name = segment
    else:
        name = segment[:first_r]            # 角色名
        after_name = segment[first_r:]

    # 角色名翻译：精确匹配 name-translated.csv
    if name and name_map:
        clean_name = ANNOT_RE.sub("", name).strip()
        if clean_name and clean_name in name_map:
            translated = name_map[clean_name]
            if translated:
                name = name.replace(clean_name, translated, 1)

    # 找出 after_name 中所有 @annotation 的位置
    spans = [(m.start(), m.end()) for m in ANNOT_RE.finditer(after_name)]

    if not spans:
        return name + combined

    # 拼接：注解保留，非注解替换为翻译
    parts = [name]
    prev = 0
    inserted = False
    for s, e in spans:
        if s > prev:
            # 注解前有对话文本 → 插入翻译（仅一次）
            if not inserted:
                parts.append(combined)
                inserted = True
        parts.append(after_name[s:e])
        prev = e
    if prev < len(after_name) and not inserted:
        parts.append(combined)
    return "".join(parts)


def load_translations(paths: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """加载多个 ep CSV → ([(original, translation)], [source_csv_name])"""
    entries = []
    entry_sources = []
    for path in paths:
        csv_name = path.replace("\\", "/").rsplit("/", 1)[-1]
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                entries.append((row["original"].strip(), row["translation"].strip()))
                entry_sources.append(csv_name)
    return entries, entry_sources


def load_name_map(path: str) -> dict[str, str]:
    """加载 name-translated.csv 角色名翻译字典。"""
    name_map = {}
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            translated = row["translated"].strip()
            if name and translated:
                name_map[name] = translated
    print(f"  角色名条目: {len(name_map)}")
    return name_map


def build_segments(lines: list[str]) -> list[tuple[int, int, str]]:
    """
    解析 extracted.txt，按 annotation 边界拆分，提取每段对话文本。
    返回: [(line_idx, seg_idx_in_line, dialogue_text)]
    """
    total = len(lines)
    print(f"  解析 {total} 行...", flush=True)
    segments = []
    for line_idx, line in enumerate(lines):
        if line_idx > 0 and line_idx % 50000 == 0:
            print(f"    解析进度: {line_idx}/{total}", flush=True)
        sp = line.find(SEPARATOR)
        if sp < 0:
            continue
        content = line[sp + len(SEPARATOR):].strip()
        for seg_idx, seg in enumerate(split_by_annotations(content)):
            dialogue = extract_dialogue(seg)
            if dialogue:  # 跳过空段
                segments.append((line_idx, seg_idx, dialogue))
    return segments


def build_gram_index(segments: list) -> dict[str, list[int]]:
    """
    对对话文本建立 4-gram 倒排索引。
    短对话（< 4 字）直接用全文建索引。
    同一片段内相同 gram 只计一次，避免重复计数扭曲投票结果。
    """
    total = len(segments)
    print(f"  构建 4-gram 索引（共 {total} 片段）...", flush=True)
    idx = defaultdict(list)
    for seg_idx, (_, _, dialogue) in enumerate(segments):
        if seg_idx > 0 and seg_idx % 100000 == 0:
            print(f"    索引进度: {seg_idx}/{total}", flush=True)
        key = strip_all(dialogue)
        if not key:
            continue
        if len(key) >= 4:
            seen = set()
            for pos in range(0, len(key) - 3, 2):
                gram = key[pos:pos+4]
                if gram not in seen:
                    idx[gram].append(seg_idx)
                    seen.add(gram)
        else:
            idx[key].append(seg_idx)
    print(f"    索引完成: {len(idx)} 个唯一 gram")
    return idx


def verify_match(orig_key: str, dial_key: str) -> tuple[bool, float]:
    """验证翻译条目是否匹配片段对话。返回 (是否匹配, 分数)"""
    if not orig_key or not dial_key:
        return False, 0.0

    # 子串匹配：适用于因标点/注释差异导致的局部匹配
    shorter, longer = (orig_key, dial_key) if len(orig_key) <= len(dial_key) else (dial_key, orig_key)
    if shorter in longer:
        if shorter == longer:
            return True, 1.0  # 完全一致，优先选用
        shorter_len = len(shorter)
        is_prefix = longer.startswith(shorter)
        if shorter_len >= 3:
            ratio = shorter_len / max(len(longer), 1)
            # 前缀子串（如 遊びに行く 匹配 遊びに行ってくるね）容易误匹配动词词干，需更高覆盖度
            min_ratio = 0.6 if is_prefix else 0.3
            if ratio >= min_ratio:
                return True, 0.9  # 子串匹配，分数略低于完全匹配
        # 2 字子串匹配：要求覆盖较长文本至少 50%，前缀匹配需 60%
        if shorter_len == 2:
            ratio = shorter_len / max(len(longer), 1)
            min_ratio = 0.6 if is_prefix else 0.5
            if ratio >= min_ratio:
                return True, 0.85
        # 比例不足阈值 → 降级到模糊匹配

    if len(orig_key) > 3 and len(dial_key) > 3:
        # 长度比保护：模糊匹配时双方向长度差异不超 3 倍
        short_len = min(len(orig_key), len(dial_key))
        long_len = max(len(orig_key), len(dial_key))
        if long_len / short_len > 3:
            return False, 0.0
        score = SequenceMatcher(None, orig_key, dial_key).ratio()
        # 长度差异大的模糊匹配（如 遊びに行く 匹配 遊びに行ってくるね）容易误匹配，
        # SequenceMatcher 会跳过中间字符给出虚高分数，需更高阈值
        min_score = 0.8 if short_len / long_len < 0.6 else FUZZY_THRESHOLD
        # 近等长字符串（长度比 >= 0.9）：单个假名差异（如 おっかしいぃ vs おっかしいな）
        # 就能被 SequenceMatcher 以长公共前缀给出虚高分数，需更高阈值
        if short_len / long_len >= 0.9:
            min_score = max(min_score, 0.85)
        if score >= min_score:
            return True, score
    return False, 0.0


def build_fulltext_segments(lines: list[str]) -> list[tuple[int, int, str]]:
    """每行只生成一个片段：整行所有对话合并，所有 @annotation 剥离。"""
    total = len(lines)
    print(f"  提取 {total} 行全文本对话...", flush=True)
    segments = []
    for line_idx, line in enumerate(lines):
        if line_idx > 0 and line_idx % 50000 == 0:
            print(f"    提取进度: {line_idx}/{total}", flush=True)
        sp = line.find(SEPARATOR)
        if sp < 0:
            continue
        content = line[sp + len(SEPARATOR):].strip()
        dialogue = extract_dialogue(content)
        if dialogue:
            segments.append((line_idx, 0, dialogue))
    return segments


def match_segments(entries: list, segments: list,
                   label: str = "", do_combined: bool = True) -> tuple:
    """
    对 segment 集合运行完整匹配管道（4-gram + 短文本精确 + 跨段合并）。

    Returns:
        seg_matches:   dict[int, list[int]]  segment_idx → [entry_idx, ...]
        combined_final: dict[tuple[int,int], tuple[int,str]]
        matched_set:   set[int]
    """
    if label:
        print(f"\n--- 匹配{label} ---")

    # ── 4-gram 倒排索引 ──
    gram_index = build_gram_index(segments)

    # ── 短对话精确索引（len < 8）──
    short_idx: dict[str, list[int]] = defaultdict(list)
    for seg_idx, (_, _, dialogue) in enumerate(segments):
        key = strip_all(dialogue)
        if key and len(key) < 8:
            short_idx[key].append(seg_idx)

    # ── 匹配 ──
    seg_matches: dict[int, list[int]] = defaultdict(list)

    for ei, (orig, _) in enumerate(entries):
        orig_key = strip_all(orig)
        if not orig_key:
            continue

        if len(orig_key) < 8:
            for seg_idx in short_idx.get(orig_key, []):
                seg_matches[seg_idx].append(ei)

        if len(orig_key) >= 4:
            query_grams = set()
            for pos in range(0, len(orig_key) - 3, 2):
                query_grams.add(orig_key[pos:pos+4])

            vote_count: dict[int, int] = defaultdict(int)
            for gram in query_grams:
                for seg_idx in gram_index.get(gram, []):
                    vote_count[seg_idx] += 1

            if not vote_count:
                continue

            max_votes = max(vote_count.values())
            min_votes = max(1, max_votes // 4)
            gram_cnt = len(query_grams)
            dynamic_cap = max(500, 2000 // max(1, gram_cnt))
            candidates = sorted(
                [(s, v) for s, v in vote_count.items() if v >= min_votes],
                key=lambda x: -x[1]
            )[:dynamic_cap]

            for seg_idx, _ in candidates:
                _, _, dialogue = segments[seg_idx]
                dial_key = strip_all(dialogue)
                matched, _ = verify_match(orig_key, dial_key)
                if matched:
                    seg_matches[seg_idx].append(ei)
                elif orig_key in dial_key and len(orig_key) >= 2:
                    seg_matches[seg_idx].append(ei)

        if label and ei % 1000 == 0 and ei > 0:
            print(f"  {label}进度: {ei}/{len(entries)}", flush=True)

    # 统计
    matched_set: set[int] = set()
    for idxs in seg_matches.values():
        matched_set.update(idxs)
    pct = len(matched_set) / len(entries) * 100
    print(f"  {label}已匹配: {len(matched_set)}/{len(entries)} ({pct:.1f}%)")

    # ── 跨段合并匹配 ──
    combined_final: dict[tuple[int, int], tuple[int, str]] = {}
    if do_combined and len(segments) > 1:
        combined_segs: list[tuple[int, int, str]] = []
        for i in range(len(segments) - 1):
            l1, s1, d1 = segments[i]
            l2, s2, d2 = segments[i + 1]
            if l1 == l2 and s1 + 1 == s2:
                combined_segs.append((l1, s1, d1 + d2))

        if combined_segs:
            if label:
                print(f"  {label}尝试合并匹配...")

            combined_gram = build_gram_index(combined_segs)
            combined_matches: dict[int, list[int]] = defaultdict(list)

            combined_short_idx: dict[str, list[int]] = defaultdict(list)
            for cs_idx, (_, _, dialogue) in enumerate(combined_segs):
                key = strip_all(dialogue)
                if key and len(key) < 8:
                    combined_short_idx[key].append(cs_idx)

            unmatched = sorted(set(range(len(entries))) - matched_set)
            for ei in unmatched:
                orig_key = strip_all(entries[ei][0])
                if not orig_key:
                    continue

                if len(orig_key) < 8:
                    for cs_idx in combined_short_idx.get(orig_key, []):
                        combined_matches[cs_idx].append(ei)

                if len(orig_key) >= 4:
                    query_grams = set()
                    for pos in range(0, len(orig_key) - 3, 2):
                        query_grams.add(orig_key[pos:pos+4])

                    vote_count = defaultdict(int)
                    for gram in query_grams:
                        for cs_idx in combined_gram.get(gram, []):
                            vote_count[cs_idx] += 1

                    if not vote_count:
                        continue

                    max_votes = max(vote_count.values())
                    min_votes = max(1, max_votes // 4)
                    gram_cnt = len(query_grams)
                    dynamic_cap = max(500, 2000 // max(1, gram_cnt))
                    candidates = sorted(
                        [(cs, v) for cs, v in vote_count.items() if v >= min_votes],
                        key=lambda x: -x[1]
                    )[:dynamic_cap]

                    for cs_idx, _ in candidates:
                        _, _, dialogue = combined_segs[cs_idx]
                        dial_key = strip_all(dialogue)
                        matched, _ = verify_match(orig_key, dial_key)
                        if matched:
                            combined_matches[cs_idx].append(ei)

            for cs_idx, entry_idxs in combined_matches.items():
                l, s, combined_dialogue = combined_segs[cs_idx]
                dial_key = strip_all(combined_dialogue)
                best_ei = None
                best_score = 0.0
                for ei in entry_idxs:
                    _, score = verify_match(strip_all(entries[ei][0]), dial_key)
                    if score > best_score:
                        best_score = score
                        best_ei = ei
                if best_ei is not None:
                    combined_final[(l, s)] = (best_ei, convert_outer_quotes(entries[best_ei][1]))
                    matched_set.add(best_ei)

            print(f"  {label}合并匹配新增: {len(combined_final)} 组, "
                  f"累计匹配: {len(matched_set)}/{len(entries)} ({len(matched_set)/len(entries)*100:.1f}%)")

    return seg_matches, combined_final, matched_set


def main():
    print(f"加载翻译对照文件: {TRANS_CSVS}")
    entries, entry_sources = load_translations(TRANS_CSVS)
    print(f"  条目数: {len(entries)}")

    print(f"加载 name-translated.csv ...")
    name_map = load_name_map("name-translated.csv")

    print(f"加载 {EXTRACTED}")
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    print(f"  行数: {len(lines)}")


    # ── 匹配：按 annotation 边界分段 ──
    print("\n解析分段（按所有 @annotation 边界）...")
    segments = build_segments(lines)
    print(f"  片段数: {len(segments)}")

    seg_matches, combined_final, matched_set = match_segments(entries, segments, label="分段")

    # ── 匹配：整行全文本（不分段） ──
    print("\n生成全文本片段...")
    full_segments = build_fulltext_segments(lines)
    print(f"  全文本片段数: {len(full_segments)}")

    full_matches, _, _ = match_segments(entries, full_segments, label="全文本", do_combined=False)

    # 构建全文本匹配的 line_idx → (entry_idx, score, translation) 查找表
    fulltext_line_matches: dict[int, tuple[int, float, str]] = {}
    for seg_idx, entry_idxs in full_matches.items():
        line_idx, _, dialogue = full_segments[seg_idx]
        dial_key = strip_all(dialogue)
        best_ei = None
        best_score = 0.0
        for ei in entry_idxs:
            _, score = verify_match(strip_all(entries[ei][0]), dial_key)
            if score > best_score:
                best_score = score
                best_ei = ei
        if best_ei is not None:
            fulltext_line_matches[line_idx] = (
                best_ei, best_score, convert_outer_quotes(entries[best_ei][1]))

    # ── 重构翻译 ──
    print("\n重构翻译文本...")

    # 按 line_idx 组织匹配结果
    line_matches: dict[int, dict[int, list[int]]] = {}
    for seg_idx, entry_idxs in seg_matches.items():
        line_idx, seg_idx_in_line, _ = segments[seg_idx]
        line_matches.setdefault(line_idx, {})[seg_idx_in_line] = sorted(entry_idxs)

    trans_dict: dict[str, str] = {}
    translated_lines = 0
    translated_fulltext = 0
    dialogue_lines = 0
    translated_dialogue_lines = 0
    recent_context = deque(maxlen=CONTEXT_WINDOW)  # 前 N 行已选条目索引，用于跨行消歧

    for line_idx, line in enumerate(lines):
        sp = line.find(SEPARATOR)
        if sp < 0:
            continue

        index = line[:sp].strip()
        content = line[sp + len(SEPARATOR):].strip()

        # 统计有 @r 的对话行总数
        if '@r' in content:
            dialogue_lines += 1

        seg_m = line_matches.get(line_idx, {})
        if not seg_m and not any(k[0] == line_idx for k in combined_final):
            # 非对话行（无 @r）不进行全文本匹配
            if '@r' not in content:
                continue
            # 如果全文本匹配可用，尝试用它
            ft_info = fulltext_line_matches.get(line_idx)
            if ft_info:
                ft_ei, ft_score, ft_trans = ft_info
                if ft_score >= FUZZY_THRESHOLD:
                    trans_dict[index] = reconstruct_segment(content, [ft_trans], name_map=name_map)
                    translated_lines += 1
                    if '@r' in content:
                        translated_dialogue_lines += 1
                    translated_fulltext += 1
                    continue
            continue

        segs = split_by_annotations(content)
        new_segs = []
        has_trans = False
        selected_eis = []  # 本行最终选中的条目索引，供后续行参考
        # 分段得分汇总（用于与全文本对比）
        seg_match_scores: list[float] = []
        # 分段覆盖率：已匹配对话字符数 / 总对话字符数
        total_dial_len = 0
        total_matched_len = 0

        consumed = set()
        for seg_idx, seg in enumerate(segs):
            if seg_idx in consumed:
                continue

            # 跨段合并匹配优先
            combined_key = (line_idx, seg_idx)
            if combined_key in combined_final:
                best_ei, trans = combined_final[combined_key]
                if seg_idx + 1 < len(segs):
                    merged_raw = segs[seg_idx] + segs[seg_idx + 1]
                    consumed.add(seg_idx + 1)
                else:
                    merged_raw = segs[seg_idx]
                new_segs.append(reconstruct_segment(merged_raw, [trans], name_map=name_map))
                selected_eis.append(best_ei)
                seg_match_scores.append(1.0)
                has_trans = True
                continue

            eis = seg_m.get(seg_idx, [])
            if not eis:
                new_segs.append(seg)
                continue

            # 上下文消歧：用本行其他片段 + 前 CONTEXT_WINDOW 行已选条目的中位数做参考
            ref_candidates = []
            for s_idx in range(len(segs)):
                if s_idx != seg_idx:
                    ref_candidates.extend(seg_m.get(s_idx, []))
            for prev_eis in recent_context:
                ref_candidates.extend(prev_eis)
            if len(ref_candidates) > 1:
                sorted_ref = sorted(ref_candidates)
                ref_idx = sorted_ref[len(sorted_ref) // 2]
            else:
                ref_idx = ref_candidates[0] if ref_candidates else -1

            raw_dialogue = extract_dialogue(seg)
            total_dial_len += len(raw_dialogue)
            dial_key = strip_all(raw_dialogue)

            # ── 收集所有通过校验的匹配条目及其位置 ──
            verified = []     # (pos, entry_orig, translated, score, raw_score, ei)
            fallback_matches = []  # (score, translated, ei) 模糊匹配非子串，作整段候选
            for ei in eis:
                e_orig = entries[ei][0]
                e_key = strip_all(e_orig)
                if not e_key:
                    continue
                e_trans = convert_outer_quotes(entries[ei][1])

                # 短 key（< 2 字）：按优先级分三层匹配
                if len(e_key) < 2:
                    # ① 最高：带标点的全文精确匹配
                    if e_orig == raw_dialogue:
                        verified.append((0, e_orig, e_trans, 1.0, 1.0, ei))
                    # ② 其次：带标点的子串匹配（可定位多条目组合）
                    elif e_orig in raw_dialogue:
                        pos = raw_dialogue.find(e_orig)
                        _, score = verify_match(e_key, dial_key)
                        score = max(score, 0.5)
                        raw_score = SequenceMatcher(None, e_orig, raw_dialogue).ratio()
                        verified.append((pos, e_orig, e_trans, score, raw_score, ei))
                    else:
                        # ③ 最后：忽略标点的模糊匹配
                        _, score = verify_match(e_key, dial_key)
                        if score >= FUZZY_THRESHOLD:
                            fallback_matches.append((score, e_trans, ei))
                    continue

                if e_key in dial_key:
                    # 子串匹配 → 可定位到具体位置，参与多条目组合
                    pos = raw_dialogue.find(e_orig)
                    if pos < 0:
                        e_stripped = e_orig.strip()
                        pos = raw_dialogue.find(e_stripped)
                        if pos >= 0:
                            e_orig = e_stripped
                        else:
                            continue
                    _, score = verify_match(e_key, dial_key)
                    score = max(score, 0.5)
                    raw_score = SequenceMatcher(None, e_orig, raw_dialogue).ratio()
                    verified.append((pos, e_orig, e_trans, score, raw_score, ei))
                else:
                    _, score = verify_match(e_key, dial_key)
                    if score >= FUZZY_THRESHOLD:
                        fallback_matches.append((score, e_trans, ei))

            if not verified:
                if fallback_matches:
                    fallback_matches.sort(key=lambda x: -x[0])
                    best_trans = fallback_matches[0][1]
                    best_ei = fallback_matches[0][2]
                    if '@r' not in seg:
                        exact_fb = [f for f in fallback_matches if strip_all(entries[f[2]][0]) == dial_key]
                        if exact_fb:
                            best_trans = exact_fb[0][1]
                            best_ei = exact_fb[0][2]
                        else:
                            new_segs.append(seg)
                            continue
                    new_segs.append(reconstruct_segment(seg, [best_trans], name_map=name_map))
                    selected_eis.append(best_ei)
                    seg_match_scores.append(fallback_matches[0][0])
                    has_trans = True
                    continue
                else:
                    new_segs.append(seg)
                    continue

            # ── 按位置排序，消除重叠 ──
            verified.sort(key=lambda x: (x[0], -x[3]))
            chosen = []
            for v in verified:
                v_pos, v_orig = v[0], v[1]
                v_end = v_pos + len(v_orig)
                for c in chosen:
                    c_pos, c_orig = c[0], c[1]
                    c_end = c_pos + len(c_orig)
                    if not (v_end <= c_pos or v_pos >= c_end):
                        break
                else:
                    chosen.append(v)

            # 无 @r 的片段只接受原文完全一致的翻译
            if '@r' not in seg:
                exact = [c for c in chosen if strip_all(c[1]) == dial_key]
                if exact:
                    chosen = [exact[0]]
                else:
                    new_segs.append(seg)
                    continue

            # ── 按位置拼接翻译 ──
            chosen.sort(key=lambda x: x[0])
            new_text = ""
            cursor = 0
            for pos, e_orig, e_trans, score, raw_score, ei in chosen:
                if pos > cursor:
                    new_text += raw_dialogue[cursor:pos]
                new_text += e_trans
                cursor = pos + len(e_orig)
            if cursor < len(raw_dialogue):
                new_text += raw_dialogue[cursor:]

            new_segs.append(reconstruct_segment(seg, [new_text], name_map=name_map))
            selected_eis.extend([ei for _, _, _, _, _, ei in chosen])
            seg_match_scores.extend([s for _, _, _, s, _, _ in chosen])
            total_matched_len += sum(len(e_orig) for _, e_orig, _, _, _, _ in chosen)
            has_trans = True

        # ── 与全文本匹配比较得分（带覆盖率加权）──
        ft_info = fulltext_line_matches.get(line_idx)
        if ft_info and has_trans and '@r' in content:
            ft_ei, ft_score, ft_trans = ft_info
            avg_seg_score = sum(seg_match_scores) / len(seg_match_scores) if seg_match_scores else 0.0
            seg_covg = total_matched_len / total_dial_len if total_dial_len > 0 else 0
            # 分段覆盖率 >= 50% 时，全文本需要显著更好（1.3x）才能替代
            # 分段覆盖率 < 50% 时，全文本略好（1.05x）即用
            covg_factor = 1.05 if seg_covg < 0.5 else 1.3
            if ft_score >= FUZZY_THRESHOLD and ft_score > avg_seg_score * covg_factor:
                trans_dict[index] = reconstruct_segment(content, [ft_trans], name_map=name_map)
                translated_lines += 1
                translated_fulltext += 1
                if '@r' in content:
                    translated_dialogue_lines += 1
                continue

        if has_trans:
            trans_dict[index] = ''.join(new_segs)
            translated_lines += 1
            if '@r' in content:
                translated_dialogue_lines += 1
            if selected_eis:
                recent_context.append(selected_eis)
        else:
            # 非对话行（无 @r）不进行全文本匹配
            if '@r' not in content:
                continue
            # 分段无匹配，尝试全文本
            ft_info = fulltext_line_matches.get(line_idx)
            if ft_info:
                ft_ei, ft_score, ft_trans = ft_info
                if ft_score >= FUZZY_THRESHOLD:
                    trans_dict[index] = reconstruct_segment(content, [ft_trans], name_map=name_map)
                    translated_lines += 1
                    translated_fulltext += 1
                    if '@r' in content:
                        translated_dialogue_lines += 1
                    continue

    # ── 输出 CSV ──
    print(f"加载原始 CSV: {HIGU_CSV}")
    with open(HIGU_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    print(f"  {len(rows)} 行")

    # 确保 temp 和 translated 列存在
    if "temp" not in fieldnames:
        fieldnames = list(fieldnames) + ["temp"]
    if "translated" not in fieldnames:
        fieldnames = list(fieldnames) + ["translated"]

    print(f"写入 {OUTPUT_CSV}...")
    matched_csv = 0
    trans_csv = 0
    for row in rows:
        index = row.get("index", "").strip()
        if not index or index not in trans_dict:
            row["temp"] = ""
            row["translated"] = ""
            continue

        result = trans_dict[index]
        original_s = row.get("s", "").strip()
        if result == original_s:
            # 未翻译（与原文相同）
            row["temp"] = ""
            row["translated"] = ""
        elif JAPANESE_RE.search(result):
            # 部分翻译：仍有日文 → 放入 temp
            row["temp"] = result
            row["translated"] = ""
        else:
            # 完全翻译：无日文 → 放入 translated
            row["temp"] = ""
            row["translated"] = result
        matched_csv += 1

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV 匹配: {matched_csv} 行")
    print(f"  其中含翻译: {trans_csv} 行")

    remaining = sorted(set(range(len(entries))) - matched_set)
    print(f"\n=== 统计 ===")
    print(f"  总条目: {len(entries)}")
    print(f"  已匹配: {len(matched_set)} ({len(matched_set)/len(entries)*100:.1f}%)")
    print(f"  未匹配: {len(remaining)}")
    if remaining:
        print(f"  未匹配示例 (前10):")
        for ei in remaining[:10]:
            try:
                print(f"    [{ei}] {entries[ei][0][:60]}")
            except UnicodeEncodeError:
                print(f"    [{ei}] (encoding error)")
    print(f"  翻译行数: {translated_lines} / {len(lines)} ({translated_lines/len(lines)*100:.1f}%)")
    print(f"    其中全文本匹配: {translated_fulltext} 行")
    if dialogue_lines:
        print(f"  对话行 (@r): {translated_dialogue_lines} / {dialogue_lines} ({translated_dialogue_lines/dialogue_lines*100:.1f}%)")
    print(f"  输出文件: {OUTPUT_CSV}")

    # ── 最终总结 ──
    total = len(lines)
    print(f"\n{'='*40}")
    print(f"  翻译完成!")
    print(f"  共 {total} 行, 已翻译 {translated_lines} 行 ({translated_lines/total*100:.1f}%)")
    if dialogue_lines:
        print(f"  对话行: {translated_dialogue_lines}/{dialogue_lines} ({translated_dialogue_lines/dialogue_lines*100:.1f}%)")
    print(f"  全文本匹配: {translated_fulltext} 行")
    print(f"  条目匹配率: {len(matched_set)}/{len(entries)} ({len(matched_set)/len(entries)*100:.1f}%)")
    print(f"{'='*40}")
    if sys.platform == "win32":
        os.system("pause")
    else:
        input("按 Enter 键关闭...")


if __name__ == "__main__":
    main()
