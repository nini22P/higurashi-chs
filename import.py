#!/usr/bin/env python3
"""
导入脚本：
1. 读取提取出来的翻译文件 (extracted.txt)
2. 读取原始 CSV (higurashi-hou.csv)
3. 按 index 匹配，将翻译写入 translated 列
4. 输出合并后的 CSV

用法:
  python import.py
  输入: extracted.txt (由 extract.py 生成，用户编辑翻译后)
        higurashi-hou.csv
  输出: higurashi-hou-translated.csv
"""

import csv
import sys

EXTRACTED = "extract/extracted-translated.txt"
HIGU_CSV = "higurashi-hou.csv"
OUTPUT_CSV = "higurashi-hou-translated.csv"
SEPARATOR = "------"


def load_translated(path: str) -> dict[str, str]:
    """
    读取翻译后的提取文件。
    每行格式: index------翻译内容
    返回 {index: 翻译内容}
    """
    result = {}
    line_count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            idx = line.find(SEPARATOR)
            if idx == -1:
                print(f"  警告: 第 {line_no} 行缺少分隔符 '{SEPARATOR}'，跳过")
                continue

            index = line[:idx].strip()
            content = line[idx + len(SEPARATOR):].strip()

            if not index:
                print(f"  警告: 第 {line_no} 行索引为空，跳过")
                continue

            result[index] = content
            line_count += 1

    print(f"  读取 {line_count} 行翻译")
    return result


def main():
    print(f"加载翻译文件: {EXTRACTED}")
    trans_map = load_translated(EXTRACTED)
    print(f"  共 {len(trans_map)} 条翻译")

    print(f"加载原始 CSV: {HIGU_CSV}")
    with open(HIGU_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"  共 {len(rows)} 行")

    if "translated" not in fieldnames:
        fieldnames = list(fieldnames) + ["translated"]

    # 按 index 匹配并填入翻译
    matched = 0
    unmatched_indices = []

    for row in rows:
        index = row.get("index", "").strip()
        if not index:
            continue

        if index in trans_map:
            if row.get("s") != trans_map[index]:
                row["translated"] = trans_map[index]
            matched += 1
            del trans_map[index]  # 标记为已使用

    # 未匹配的翻译（提取文件里有但 CSV 里找不到对应 index）
    unmatched_in_extract = list(trans_map.keys())

    print(f"\n统计:")
    print(f"  匹配成功的行: {matched}")
    print(f"  提取文件中未使用的翻译: {len(unmatched_in_extract)}")

    if unmatched_in_extract:
        print(f"  前 5 个未使用的 index: {unmatched_in_extract[:5]}")

    print(f"\n写入输出: {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"完成！输出文件: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
