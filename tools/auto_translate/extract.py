#!/usr/bin/env python3
"""
提取脚本：从 higurashi-hou.csv 提取 index 和 s 列内容。
不进行翻译匹配，只做纯提取。
每行格式: INDEX------S_COLUMN_CONTENT

用法:
  python extract.py
  输出: extracted.txt
"""

import csv
import os

HIGU_CSV = "higurashi-hou.csv"
OUTPUT = "extract/extracted.txt"
SEPARATOR = "------"


def main():
    print(f"加载 {HIGU_CSV}...")
    with open(HIGU_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"  共 {len(rows)} 行")

    print(f"生成 {OUTPUT}...")
    os.makedirs("extract", exist_ok=True)
    count = 0
    with open(OUTPUT, "w", encoding="utf-8") as out:
        for row in rows:
            s = row.get("s", "").strip()
            if not s:
                continue
            index = row.get("index", "").strip()
            if not index:
                continue
            out.write(f"{index}{SEPARATOR}{s}\n")
            count += 1

    print(f"  写入 {count} 行")
    print(f"完成！输出文件: {OUTPUT}")
    print(f"提示：编辑此文件，将分隔符右侧的日文替换为中文翻译，")
    print(f"      然后用 import.py 导回到 CSV。")


if __name__ == "__main__":
    main()
