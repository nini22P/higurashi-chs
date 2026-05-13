import re
import json
import csv
import os


RUBY_REGEX = r'@b([^@.]+)\.@<([^@>]+)@>'
CODE_REGEX = r'(@[abcosuvwxz][^@\n\r.]*\.|@[-+/<>[\]ekrty{|}]|@[a-zA-Z])'
CSV_CONFIGS = [
    {
        "input": "main.csv",
        "original_cols": ["s"],
        "translation_cols": ["translated"],
    },
]

CRITICAL_PAIRS = []


def to_human(text):
    return re.sub(RUBY_REGEX, r'[\1|\2]', text)


def has_name_box(parts):
    if '@r' not in parts:
        return False
    idx = parts.index('@r')
    if idx == 0:
        return False
    return bool(parts[idx - 1] and parts[idx - 1].strip())


def check_ruby_syntax(text):
    errors = []

    # mismatched @< @>
    opens = [m.start() for m in re.finditer(r'@<', text)]
    closes = [m.start() for m in re.finditer(r'@>', text)]
    depth = 0
    for m in re.finditer(r'@<|@>', text):
        if m.group() == '@<':
            depth += 1
        else:
            depth -= 1
        if depth < 0:
            errors.append(f"多余的 @> 在位置 {m.start()}")
            depth = 0
    if depth > 0:
        errors.append(f"缺少 {depth} 个 @> 闭合标记")

    # @b without proper ruby
    for m in re.finditer(r'@b([^@.]*)\.(?:@<([^@>]*)@>)?', text):
        full = m.group()
        key = m.group(1)
        has_ruby = m.group(2) is not None
        if not has_ruby:
            errors.append(f"@b{key}. 缺少对应 @<...@>")
        elif not m.group(2):
            errors.append(f"@b{key}.@<> 内 rubi 为空")

    # @< without preceding @b
    last_atb = -1
    for m in re.finditer(r'@<([^@>]*)@>', text):
        prev = text[m.start() - 30:m.start()]
        atb_pos = prev.rfind('@b')
        dot_pos = prev.rfind('.')
        if atb_pos == -1 or dot_pos == -1 or dot_pos < atb_pos:
            errors.append(f"孤立 @<{m.group(1)}@> 缺少前面 @b")

    return errors


def get_name_and_segments(text):
    parts = re.split(CODE_REGEX, to_human(str(text)))
    name_seg = ""
    if has_name_box(parts):
        name_seg = parts[parts.index('@r') - 1].strip()
    segments = []
    start = parts.index('@r') + 1 if name_seg else 0
    for p in parts[start:]:
        if not p:
            continue
        if not re.match(CODE_REGEX, p) and p.strip():
            segments.append(p.strip())
    return name_seg, segments, parts


def load_name_dict(path="higurashi-hou.csv"):
    if not os.path.exists(path):
        return {}
    name_dict = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("type", "").strip() != "name":
                continue
            n = row.get("text", "").strip()
            t = row.get("translated", "").strip()
            if n and t:
                name_dict[n] = t
    return name_dict


def check_critical_strings(rows, config):
    path = config["input"]
    print("--- 关键字符串对应关系检查开始 ---")
    parsed_pairs = [(json.loads(jp_str), json.loads(cn_str)) for jp_str, cn_str in CRITICAL_PAIRS]
    found = False
    for i, row in enumerate(rows):
        row_num = i + 2
        for col in config["translation_cols"]:
            t_text = row.get(col, '')
            for jp_str, cn_str in parsed_pairs:
                if jp_str in row.get('s', ''):
                    if cn_str not in t_text:
                        print(f"{path}:{row_num}: ❌ 缺失关键译文: {cn_str}")
                        found = True
    if not found:
        print("✅ 关键字符串检查通过。")
    print("--- 检查结束 ---\n")


def check_row(rows, config, name_dict):
    path = config["input"]
    found_error = False

    for org_col in config["original_cols"]:
        for tgt_col in config["translation_cols"]:
            for i, row in enumerate(rows):
                row_num = i + 2
                s_text = row.get(org_col, '')
                t_text = row.get(tgt_col, '')
                if not s_text or not t_text:
                    continue

                ruby_errors = check_ruby_syntax(t_text)
                for err in ruby_errors:
                    print(f"{path}:{row_num}: ❌ 译文 ruby 语法错误: {err}")
                    found_error = True

                orig_name, orig_segs, orig_parts = get_name_and_segments(s_text)
                trans_name, trans_segs, trans_parts = get_name_and_segments(t_text)

                if orig_name and trans_name:
                    expected = name_dict.get(orig_name)
                    if expected and trans_name != expected:
                        print(f"{path}:{row_num}: ❌ 人名翻译错误: '{orig_name}' → '{trans_name}', 应为 '{expected}'")
                        found_error = True

                orig_codes = [p for p in orig_parts if re.match(CODE_REGEX, p)]
                trans_codes = [p for p in trans_parts if re.match(CODE_REGEX, p)]
                if orig_codes != trans_codes:
                    print(f"{path}:{row_num}: ⚠️ 控制符不匹配")
                    print(f"   原文控制符: {orig_codes}")
                    print(f"   译文控制符: {trans_codes}")
                    found_error = True

                if len(orig_segs) != len(trans_segs):
                    print(f"{path}:{row_num}: ⚠️ 段数不匹配 ({len(orig_segs)} vs {len(trans_segs)})")
                    found_error = True

    if not found_error:
        print("✅ 行检查通过。")


def main():
    name_dict = load_name_dict()
    print(f"已加载 {len(name_dict)} 个人名映射")

    for config in CSV_CONFIGS:
        path = config["input"]
        if not os.path.exists(path):
            print(f"CSV 文件不存在，跳过: {path}")
            continue

        print(f"\n检查 CSV: {path}")
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        check_critical_strings(rows, config)
        check_row(rows, config, name_dict)


if __name__ == "__main__":
    main()
