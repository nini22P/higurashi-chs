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
  输出: extracted-translated.txt
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
OUTPUT = "extract/extracted-translated.txt"
SEPARATOR = "------"
FUZZY_THRESHOLD = 0.7
CONTEXT_WINDOW = 3           # 行级上下文窗口：平局时参考前 N 行的选中条目

# 匹配所有 @annotation: 只允许游戏实际使用的标注字符（字母、数字、标点符号等）
# 明确列出允许字符而非反向排除，避免误吞引号等非日文字符
ANNOT_RE = re.compile(r"@[a-zA-Z0-9_/.\|<>\[\]-]+")


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


def reconstruct_segment(segment: str, translations: list[str]) -> str:
    """
    重构片段：保留角色名和 @annotation，对话部分替换为翻译。
    translations 按翻译文件条目顺序合并。
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


def build_segments(lines: list[str]) -> list[tuple[int, int, str]]:
    """
    解析 extracted.txt，按 @k 拆分，提取每段对话文本。
    返回: [(line_idx, seg_idx_in_line, dialogue_text)]
    """
    segments = []
    for line_idx, line in enumerate(lines):
        sp = line.find(SEPARATOR)
        if sp < 0:
            continue
        content = line[sp + len(SEPARATOR):].strip()
        for seg_idx, seg in enumerate(content.split("@k")):
            dialogue = extract_dialogue(seg)
            segments.append((line_idx, seg_idx, dialogue))
    return segments


def build_gram_index(segments: list) -> dict[str, list[int]]:
    """
    对对话文本建立 4-gram 倒排索引。
    短对话（< 4 字）直接用全文建索引。
    同一片段内相同 gram 只计一次，避免重复计数扭曲投票结果。
    """
    idx = defaultdict(list)
    for seg_idx, (_, _, dialogue) in enumerate(segments):
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


def main():
    print(f"加载翻译对照文件: {TRANS_CSVS}")
    entries, entry_sources = load_translations(TRANS_CSVS)
    print(f"  条目数: {len(entries)}")

    print(f"加载 {EXTRACTED}")
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    print(f"  行数: {len(lines)}")


    # ── 构建 @k 片段索引 ──
    print("\n解析 @k 片段...")
    segments = build_segments(lines)
    print(f"  @k 片段数: {len(segments)}")

    # ── 构建 4-gram 倒排索引 ──
    print("构建 4-gram 倒排索引...")
    gram_index = build_gram_index(segments)
    print(f"  唯一 gram 数: {len(gram_index)}")

    # ── 构建短对话精确索引（len < 8）──
    # 短对话用4-gram投票区分度低（尤其4字条目只有1个gram），
    # 且500候选上限会截掉大量候选（如そうです 有1283个片段匹配）。
    # 改用完整文本精确匹配，不走投票。
    print("构建短对话精确索引...")
    short_idx: dict[str, list[int]] = defaultdict(list)
    for seg_idx, (_, _, dialogue) in enumerate(segments):
        key = strip_all(dialogue)
        if key and len(key) < 8:
            short_idx[key].append(seg_idx)
    print(f"  唯一短键数: {len(short_idx)}")

    # ── 匹配每个 翻译 条目 ──
    print("\n匹配翻译条目...")
    seg_matches: dict[int, list[int]] = defaultdict(list)

    for ei, (orig, _) in enumerate(entries):
        orig_key = strip_all(orig)
        if not orig_key:
            continue

        # ── 短条目（< 8 字）精确匹配（绕过4-gram投票避免500上限截断）──
        if len(orig_key) < 8:
            for seg_idx in short_idx.get(orig_key, []):
                seg_matches[seg_idx].append(ei)

        # ── 所有条目（>= 4 字）4-gram 模糊匹配 ──
        if len(orig_key) >= 4:
            query_grams = set()
            for pos in range(0, len(orig_key) - 3, 2):
                query_grams.add(orig_key[pos:pos+4])

            # 投票找候选片段
            vote_count: dict[int, int] = defaultdict(int)
            for gram in query_grams:
                for seg_idx in gram_index.get(gram, []):
                    vote_count[seg_idx] += 1

            if not vote_count:
                continue

            # 动态候选阈值：保留 ≥ max/4 票的候选
            max_votes = max(vote_count.values())
            min_votes = max(1, max_votes // 4)
            # 动态上限：gram越少区分度越低，需要更大候选池防止截断
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

        if ei % 1000 == 0 and ei > 0:
            print(f"  进度: {ei}/{len(entries)}", flush=True)

    # 统计
    matched_set = set()
    for idxs in seg_matches.values():
        matched_set.update(idxs)
    pct = len(matched_set) / len(entries) * 100
    print(f"\n  已匹配: {len(matched_set)}/{len(entries)} ({pct:.1f}%)")

    # ── 跨 @k 片段合并匹配 ──
    combined_final: dict[tuple[int, int], tuple[int, str]] = {}
    print("\n尝试跨 @k 片段合并匹配...")
    unmatched = sorted(set(range(len(entries))) - matched_set)
    if unmatched and len(segments) > 1:
        # 构建相邻 @k 片段的合并对话
        combined_segs: list[tuple[int, int, str]] = []
        for i in range(len(segments) - 1):
            l1, s1, d1 = segments[i]
            l2, s2, d2 = segments[i + 1]
            if l1 == l2 and s1 + 1 == s2:
                combined_segs.append((l1, s1, d1 + d2))
        print(f"  合并片段数: {len(combined_segs)}")

        combined_gram = build_gram_index(combined_segs)
        combined_matches: dict[int, list[int]] = defaultdict(list)

        # 短对话精确索引（len < 8），避免4-gram投票截断
        combined_short_idx: dict[str, list[int]] = defaultdict(list)
        for cs_idx, (_, _, dialogue) in enumerate(combined_segs):
            key = strip_all(dialogue)
            if key and len(key) < 8:
                combined_short_idx[key].append(cs_idx)

        # 只对未匹配条目做合并匹配
        for ei in unmatched:
            orig_key = strip_all(entries[ei][0])
            if not orig_key:
                continue

            if len(orig_key) < 8:
                for cs_idx in combined_short_idx.get(orig_key, []):
                    combined_matches[cs_idx].append(ei)

            # 4-gram模糊匹配（含动态上限）
            if len(orig_key) >= 4:
                query_grams = set()
                for pos in range(0, len(orig_key) - 3, 2):
                    query_grams.add(orig_key[pos:pos+4])

                vote_count: dict[int, int] = defaultdict(int)
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

        pct2 = len(matched_set) / len(entries) * 100
        print(f"  合并匹配新增: {len(combined_final)} 组, "
              f"累计匹配: {len(matched_set)}/{len(entries)} ({pct2:.1f}%)")
    else:
        print("  无不匹配条目，跳过")

    # ── 重构翻译 ──
    print("\n重构翻译文本...")

    # 按 line_idx 组织匹配结果
    line_matches: dict[int, dict[int, list[int]]] = {}
    for seg_idx, entry_idxs in seg_matches.items():
        line_idx, seg_idx_in_line, _ = segments[seg_idx]
        line_matches.setdefault(line_idx, {})[seg_idx_in_line] = sorted(entry_idxs)

    output_lines = []
    translated_lines = 0
    dialogue_lines = 0
    translated_dialogue_lines = 0
    recent_context = deque(maxlen=CONTEXT_WINDOW)  # 前 N 行已选条目索引，用于跨行消歧

    for line_idx, line in enumerate(lines):
        sp = line.find(SEPARATOR)
        if sp < 0:
            output_lines.append(line)
            continue

        index = line[:sp].strip()
        content = line[sp + len(SEPARATOR):].strip()

        # 统计有 @r 的对话行总数
        if '@r' in content:
            dialogue_lines += 1

        seg_m = line_matches.get(line_idx, {})
        if not seg_m:
            # seg_m 为空时检查是否有合并匹配
            if combined_final and any(k[0] == line_idx for k in combined_final):
                pass  # 继续处理，下面的循环会处理合并匹配
            else:
                output_lines.append(line)
                continue

        segs = content.split("@k")
        new_segs = []
        has_trans = False
        selected_eis = []  # 本行最终选中的条目索引，供后续行参考

        consumed = set()
        for seg_idx, seg in enumerate(segs):
            if seg_idx in consumed:
                continue

            # 跨 @k 片段合并匹配优先
            combined_key = (line_idx, seg_idx)
            if combined_key in combined_final:
                best_ei, trans = combined_final[combined_key]
                if seg_idx + 1 < len(segs):
                    merged_raw = segs[seg_idx] + "@k" + segs[seg_idx + 1]
                    consumed.add(seg_idx + 1)
                else:
                    merged_raw = segs[seg_idx]
                new_segs.append(reconstruct_segment(merged_raw, [trans]))
                selected_eis.append(best_ei)
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
            dial_key = strip_all(raw_dialogue)

            # 二次验证 + 三级消歧: 得分 > 原文相似度 > CSV文件来源 > 同行索引接近度
            best_ei = None
            best_score = 0.0
            best_raw = 0.0
            for ei in eis:
                matched, score = verify_match(strip_all(entries[ei][0]), dial_key)
                if not matched:
                    continue

                raw_score = SequenceMatcher(None, entries[ei][0], raw_dialogue).ratio()

                if score > best_score:
                    best_score = score
                    best_raw = raw_score
                    best_ei = ei
                elif score == best_score:
                    if raw_score > best_raw:
                        best_raw = raw_score
                        best_ei = ei
                    elif raw_score == best_raw and ref_idx >= 0:
                        # 原文相似度也平局 → CSV文件来源消歧
                        if recent_context:
                            ctx_files = Counter()
                            for ctx in recent_context:
                                for e in ctx:
                                    ctx_files[entry_sources[e]] += 1
                            dominant = ctx_files.most_common(1)[0][0]
                            curr_file = entry_sources[ei]
                            best_file = entry_sources[best_ei]
                            if curr_file == dominant and best_file != dominant:
                                best_ei = ei
                            elif curr_file == best_file and abs(ei - ref_idx) < abs(best_ei - ref_idx):
                                best_ei = ei
                        elif abs(ei - ref_idx) < abs(best_ei - ref_idx):
                            best_ei = ei

            if best_ei is None:
                new_segs.append(seg)
                continue

            # 无 @r 的片段（如标题/标记）只接受原文完全一致的翻译，防止误翻
            if '@r' not in seg and strip_all(entries[best_ei][0]) != dial_key:
                new_segs.append(seg)
                continue

            translations = [convert_outer_quotes(entries[best_ei][1])]
            new_segs.append(reconstruct_segment(seg, translations))
            selected_eis.append(best_ei)
            has_trans = True

        if has_trans:
            output_lines.append(f"{index}{SEPARATOR}{'@k'.join(new_segs)}")
            translated_lines += 1
            if '@r' in content:
                translated_dialogue_lines += 1
            if selected_eis:
                recent_context.append(selected_eis)
        else:
            output_lines.append(line)

    # ── 输出 ──
    print(f"写入 {OUTPUT}...")
    os.makedirs("extract", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        for line in output_lines:
            f.write(line + "\n")

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
    if dialogue_lines:
        print(f"  对话行 (@r): {translated_dialogue_lines} / {dialogue_lines} ({translated_dialogue_lines/dialogue_lines*100:.1f}%)")
    print(f"  输出文件: {OUTPUT}")

    # ── 对比分析 ──
    compare_with_original()


def compare_with_original():
    """
    逐行对比 extracted.txt 与 extracted-translated.txt：
    - 相同行（未翻译）→ extract/untranslated.txt
    - 不同且翻译后仍含日文 → extract/has_japanese.txt
    格式: 同 extracted-translated.txt 的 行号------内容
    """
    # 只检测日文独有的假名（平假名/片假名），不包含中日共享汉字
    JAPANESE_RE = re.compile(r'[ぁ-ゖゝゞゟァ-ヺーヽヾヿ]')

    with open(EXTRACTED, "r", encoding="utf-8") as f:
        orig_lines = [line.rstrip("\n") for line in f if line.strip()]
    with open(OUTPUT, "r", encoding="utf-8") as f:
        trans_lines = [line.rstrip("\n") for line in f if line.strip()]

    unchanged = []
    has_japanese = []

    min_lines = min(len(orig_lines), len(trans_lines))
    for i in range(min_lines):
        # 提取行号（------ 前的数字）
        orig_idx = orig_lines[i].split(SEPARATOR, 1)[0].strip() if SEPARATOR in orig_lines[i] else str(i)
        orig_content = orig_lines[i].split(SEPARATOR, 1)[-1] if SEPARATOR in orig_lines[i] else orig_lines[i]
        trans_content = trans_lines[i].split(SEPARATOR, 1)[-1] if SEPARATOR in trans_lines[i] else trans_lines[i]

        if orig_content == trans_content:
            unchanged.append(f"{orig_idx}{SEPARATOR}{orig_content}")
        elif JAPANESE_RE.search(trans_content):
            has_japanese.append(f"{orig_idx}{SEPARATOR}{trans_content}")

    os.makedirs("extract", exist_ok=True)

    with open("extract/untranslated.txt", "w", encoding="utf-8") as f:
        for line in unchanged:
            f.write(line + "\n")

    with open("extract/has_japanese.txt", "w", encoding="utf-8") as f:
        for line in has_japanese:
            f.write(line + "\n")

    print(f"\n=== 逐行对比分析 ===")
    print(f"  总行数: {min_lines}")
    print(f"  未翻译行（原文==译文）: {len(unchanged)}")
    print(f"  翻译后仍含日文: {len(has_japanese)}")
    print(f"  输出: extract/untranslated.txt")
    print(f"  输出: extract/has_japanese.txt")


if __name__ == "__main__":
    main()
