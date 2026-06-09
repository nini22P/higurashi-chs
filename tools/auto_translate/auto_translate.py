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
from collections import defaultdict

# 确保 stdout 支持 UTF-8（Windows GBK 兼容）
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

EXTRACTED = "extract/extracted.txt"
TRANS_CSVS = [f"translate_cn/ep{i:02d}.csv" for i in range(1, 11)]
HIGU_CSV = "higurashi-hou.csv"
OUTPUT_CSV = "higurashi-hou-translated.csv"
SEPARATOR = "------"
FUZZY_THRESHOLD = 0.7

# 匹配所有 @annotation: 只允许游戏实际使用的标注字符（字母、数字、标点符号等）
# 明确列出允许字符而非反向排除，避免误吞引号等非日文字符
# @<…@> 和 @c$f22 作为整体标注（ruby 注音 / 字体大小）
ANNOT_RE = re.compile(r"@<[^@]*@>|@[a-zA-Z0-9_/.\|<>\[\]\$-]+")
# 只检测日文独有的假名（平假名/片假名），不包含中日共享汉字
JAPANESE_RE = re.compile(r'[ぁ-ゖゝゞゟァ-ヺーヽヾヿ]')

# 匹配 ruby 注音 @b注音.@<文本@> → 提取 @<…@> 内的实际文本
RUBY_RE = re.compile(r'@b([^@.]+)\.@<([^@>]+)@>')

# script-tool 的注解分割正则（参数型注解以 . 结尾，单字符注解）
CODE_REGEX = re.compile(r'(@[abcosuvwxz][^@\n\r.]*\.|@[-+/<>[\]ekrty{|}]|@[a-zA-Z])')


def strip_ruby(text: str) -> str:
    """将 @b注音.@<文本@> 替换为 文本，移除 ruby 注音保留实际文字。"""
    return RUBY_RE.sub(r'\2', text)


def to_human(text: str) -> str:
    """将 @b注音.@<文本@> 转换为 [注音|文本]（script-tool 兼容）。"""
    return RUBY_RE.sub(r'[\1|\2]', text)


def get_dialogue_units(content: str) -> list[str]:
    """仿 script-tool.get_segments：提取对话片段。

    按 CODE_REGEX 分割，跳过 @r 前角色名（如有），
    收集纯对话文本（不含 @annotation）。
    """
    parts = re.split(CODE_REGEX, content)
    # 找到 @r 位置，其前为角色名
    first_r = content.find('@r')
    if first_r >= 0:
        for i, p in enumerate(parts):
            if p == '@r':
                start = i + 1
                break
        else:
            start = 0
    else:
        start = 0

    segs = []
    for p in parts[start:]:
        if not p:
            continue
        if not re.match(CODE_REGEX, p) and p.strip():
            segs.append(p.strip())
    return segs


def split_by_annotations(content: str) -> list[str]:
    """
    按 CODE_REGEX 分割，将注解与后续对话配对为片段（script-tool 兼容）。
    角色名前缀（第一个 @r 之前）归入第一个分段。
    连续注解（如 @k@r）会被合并到同一片段前缀。
    """
    first_r = content.find('@r')
    name_prefix = content[:first_r] if first_r >= 0 else ''
    rest = content[first_r:] if first_r >= 0 else content

    parts = re.split(CODE_REGEX, rest)
    segments = []
    pending_codes = ''
    is_first = True

    # parts[0] = 第一个注解前的文本
    if parts[0].strip():
        seg = parts[0]
        if is_first and name_prefix:
            seg = name_prefix + seg
            is_first = False
        segments.append(seg)

    # 交替遍历 (code, non-code) 对
    i = 1
    while i < len(parts) - 1:
        code = parts[i]
        non_code = parts[i + 1]

        pending_codes += code

        if non_code.strip():
            seg = pending_codes + non_code
            if is_first and name_prefix:
                seg = name_prefix + seg
                is_first = False
            segments.append(seg)
            pending_codes = ''

        i += 2

    # 末尾残留的注解
    if pending_codes:
        if is_first and name_prefix:
            pending_codes = name_prefix + pending_codes
        segments.append(pending_codes)

    # 纯文字行（无 annotation）
    if not segments and content.strip():
        segments.append(content)

    return segments


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
    if prev < len(after_name):
        if not inserted:
            parts.append(combined)
        else:
            # 已有翻译插入（多块标注），保留后续未匹配的原文
            parts.append(after_name[prev:])
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
    解析 extracted.txt，用 script-tool 方式提取对话片段。
    返回: [(line_idx, unit_idx_in_line, dialogue_text)]
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
        # 去掉 ruby 后用 get_dialogue_units 分段（脚本工具方式）
        units = get_dialogue_units(strip_ruby(content))
        for unit_idx, dialogue in enumerate(units):
            if dialogue:
                segments.append((line_idx, unit_idx, dialogue))
    return segments


def build_lookup(entries: list) -> tuple[dict, dict, list]:
    """构建轻量级查找结构：精确匹配字典 + 前缀索引 + 短文本索引。

    Returns:
        exact_dict: {cleaned_text: entry_idx}
        prefix_dict: {6_char_prefix: [(entry_idx, cleaned_text)]}
        short_idx: {cleaned_text: [entry_idx]} for texts < 8 chars
    """
    exact_dict: dict[str, int] = {}
    prefix_dict: dict[str, list[tuple[int, str]]] = defaultdict(list)
    short_idx: dict[str, list[int]] = defaultdict(list)

    for ei, (orig, _) in enumerate(entries):
        key = strip_all(orig)
        if not key:
            continue
        exact_dict[key] = ei
        if len(key) < 8:
            short_idx[key].append(ei)
        prefix_dict[key[:6]].append((ei, key))

    return exact_dict, prefix_dict, short_idx


def match_segments(entries: list, segments: list,
                   label: str = "", do_combined: bool = True) -> tuple:
    """
    轻量匹配：精确匹配 → 前缀子串匹配 → 模糊匹配（长文本）。
    不用 4-gram 索引，内存占用低。
    """
    if label:
        print(f"\n--- 匹配{label} ---")

    exact_dict, prefix_dict, short_idx = build_lookup(entries)
    seg_matches: dict[int, list[int]] = defaultdict(list)

    for seg_idx, (_, _, dialogue) in enumerate(segments):
        dial_key = strip_all(dialogue)
        if not dial_key:
            continue

        # 1. Exact match
        if dial_key in exact_dict:
            seg_matches[seg_idx].append(exact_dict[dial_key])
            continue

        # 2. Short text exact via short_idx
        if len(dial_key) < 8:
            for ei in short_idx.get(dial_key, []):
                seg_matches[seg_idx].append(ei)
            if seg_matches[seg_idx]:
                continue

        # 3. Sliding prefix substring match
        found = False
        max_start = max(1, len(dial_key) - 5)
        for start in range(max_start):
            sub = dial_key[start:start + 6]
            if sub in prefix_dict:
                for ei, orig_key in prefix_dict[sub]:
                    if len(orig_key) >= 2 and len(dial_key) >= 2:
                        if orig_key in dial_key or dial_key in orig_key:
                            seg_matches[seg_idx].append(ei)
                            found = True
                            break
                if found:
                    break

        # 4. Fuzzy match for longer texts
        if not found and len(dial_key) >= 8:
            best_ei = None
            best_score = 0.0
            first_char = dial_key[0]
            for ei, orig_key in prefix_dict.get(first_char, []):
                if len(orig_key) < 4 or len(dial_key) < 4:
                    continue
                short_len = min(len(orig_key), len(dial_key))
                long_len = max(len(orig_key), len(dial_key))
                if long_len / short_len > 3:
                    continue
                score = SequenceMatcher(None, orig_key, dial_key).ratio()
                if score > best_score and score >= FUZZY_THRESHOLD:
                    best_score = score
                    best_ei = ei
            if best_ei is not None:
                seg_matches[seg_idx].append(best_ei)

    # Stats
    matched_set: set[int] = set()
    for idxs in seg_matches.values():
        matched_set.update(idxs)
    pct = len(matched_set) / len(entries) * 100 if entries else 0
    print(f"  {label}已匹配: {len(matched_set)}/{len(entries)} ({pct:.1f}%)")

    # Simple combined matching (adjacent units on same line)
    combined_final: dict[tuple[int, int], tuple[int, str]] = {}
    if do_combined and len(segments) > 1:
        combined_pairs = []
        for i in range(len(segments) - 1):
            l1, s1, d1 = segments[i]
            l2, s2, d2 = segments[i + 1]
            if l1 == l2 and s1 + 1 == s2 and i not in seg_matches and (i + 1) not in seg_matches:
                combined_pairs.append((l1, s1, d1 + d2))

        if combined_pairs:
            if label:
                print(f"  {label}尝试合并匹配 ({len(combined_pairs)} 组)...")
            for cs_idx, (l, s, combined_dialogue) in enumerate(combined_pairs):
                dial_key = strip_all(combined_dialogue)
                if dial_key in exact_dict:
                    ei = exact_dict[dial_key]
                    combined_final[(l, s)] = (ei, convert_outer_quotes(entries[ei][1]))
                    matched_set.add(ei)
                else:
                    for start in range(max(1, len(dial_key) - 5)):
                        sub = dial_key[start:start + 6]
                        if sub in prefix_dict:
                            for ei, orig_key in prefix_dict[sub]:
                                if len(orig_key) >= 3 and (orig_key in dial_key or dial_key in orig_key):
                                    combined_final[(l, s)] = (ei, convert_outer_quotes(entries[ei][1]))
                                    matched_set.add(ei)
                                    break
                            break

        if label and combined_pairs:
            print(f"  {label}合并匹配新增: {len(combined_final)} 组")

    print(f"  累计条目匹配: {len(matched_set)}/{len(entries)} ({len(matched_set)/len(entries)*100:.1f}%)")
    return seg_matches, combined_final, matched_set


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
        content = strip_ruby(content)
        dialogue = extract_dialogue(content)
        if dialogue:
            segments.append((line_idx, 0, dialogue))
    return segments


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


    # ── 匹配：按 @k 分段 ──
    print("\n解析分段（按 @k 分句）...")
    segments = build_segments(lines)
    print(f"  @k 片段数: {len(segments)}")

    seg_matches, combined_final, matched_set = match_segments(entries, segments, label="@k分段")

    # ── 匹配：整行全文本（不分段） ──
    print("\n生成全文本片段...")
    full_segments = build_fulltext_segments(lines)
    print(f"  全文本片段数: {len(full_segments)}")

    full_matches, _, _ = match_segments(entries, full_segments, label="全文本", do_combined=False)

    # 构建全文本匹配的 line_idx → translation 查找表
    fulltext_line_matches: dict[int, str] = {}
    for seg_idx, entry_idxs in full_matches.items():
        line_idx, _, dialogue = full_segments[seg_idx]
        dial_key = strip_all(dialogue)
        best_ei = -1
        best_score = 0.0
        for ei in entry_idxs:
            orig_key = strip_all(entries[ei][0])
            if not orig_key:
                continue
            if orig_key == dial_key:
                best_score = 1.0
                best_ei = ei
                break
            elif orig_key in dial_key or dial_key in orig_key:
                score = len(orig_key) / max(len(dial_key), 1)
                if score > best_score:
                    best_score = score
                    best_ei = ei
        if best_ei >= 0:
            fulltext_line_matches[line_idx] = convert_outer_quotes(entries[best_ei][1])

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
            if '@r' not in content:
                continue
            # 分段无匹配，尝试全文本
            ft_trans = fulltext_line_matches.get(line_idx)
            if ft_trans:
                clean_content = strip_ruby(content)
                trans_dict[index] = reconstruct_segment(clean_content, [ft_trans], name_map=name_map)
                translated_lines += 1
                translated_fulltext += 1
                if '@r' in content:
                    translated_dialogue_lines += 1
            continue

        stripped = strip_ruby(content)
        ann_segs = split_by_annotations(stripped)
        new_segs = []
        has_trans = False
        consumed = set()

        for unit_idx, ann_seg in enumerate(ann_segs):
            if unit_idx in consumed:
                continue

            # 跨段合并匹配优先
            combined_key = (line_idx, unit_idx)
            if combined_key in combined_final:
                best_ei, trans = combined_final[combined_key]
                if unit_idx + 1 < len(ann_segs):
                    merged = ann_seg + ann_segs[unit_idx + 1]
                    consumed.add(unit_idx + 1)
                else:
                    merged = ann_seg
                new_segs.append(reconstruct_segment(merged, [trans], name_map=name_map))
                has_trans = True
                continue

            eis = seg_m.get(unit_idx, [])
            if not eis:
                new_segs.append(ann_seg)  # 保留原文（ruby 已去除）
                continue

            # 选最佳翻译
            dial_key = strip_all(extract_dialogue(ann_seg))
            best_ei = -1
            best_score = 0.0
            for ei in eis:
                orig_key = strip_all(entries[ei][0])
                if not orig_key:
                    continue
                if orig_key == dial_key:
                    best_score = 1.0
                    best_ei = ei
                    break
                elif orig_key in dial_key or dial_key in orig_key:
                    score = len(orig_key) / max(len(dial_key), 1)
                    if score > best_score:
                        best_score = score
                        best_ei = ei
                else:
                    if len(orig_key) >= 5 and len(dial_key) >= 5:
                        short_len = min(len(orig_key), len(dial_key))
                        long_len = max(len(orig_key), len(dial_key))
                        if long_len / short_len <= 3:
                            score = SequenceMatcher(None, orig_key, dial_key).ratio()
                            if score >= FUZZY_THRESHOLD and score > best_score:
                                best_score = score
                                best_ei = ei

            if best_ei >= 0:
                trans = convert_outer_quotes(entries[best_ei][1])
                new_segs.append(reconstruct_segment(ann_seg, [trans], name_map=name_map))
                has_trans = True
            else:
                new_segs.append(ann_seg)

        if has_trans:
            trans_dict[index] = ''.join(new_segs)
            translated_lines += 1
            if '@r' in content:
                translated_dialogue_lines += 1
        elif '@r' in content:
            ft_trans = fulltext_line_matches.get(line_idx)
            if ft_trans:
                stripped = strip_ruby(content)
                trans_dict[index] = reconstruct_segment(stripped, [ft_trans], name_map=name_map)
                translated_lines += 1
                translated_fulltext += 1
                if '@r' in content:
                    translated_dialogue_lines += 1

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
