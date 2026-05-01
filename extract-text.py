#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import ast
import csv
import re
import struct
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

# =========================
# Plain-text script parsing
# =========================


def split_top_level_args(arg_text: str) -> List[str]:
    """Split function arguments by top-level commas (ignoring commas inside strings/brackets)."""
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    in_str = False
    escape = False

    for ch in arg_text:
        if in_str:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)

    if buf:
        parts.append("".join(buf).strip())
    return parts


def parse_quoted_string(token: str) -> str:
    """Parse a quoted string token (C/Python style), returning empty string on failure."""
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        try:
            return ast.literal_eval(token)
        except Exception:
            return token[1:-1]
    return ""


def extract_pairs_from_txt(text: str) -> Iterator[Tuple[str, str]]:
    """Extract original/translation pairs from OutputLine(...), using arg2 and arg4."""
    pattern = re.compile(r"OutputLine\s*\((.*?)\)\s*;", re.DOTALL)

    for match in pattern.finditer(text):
        args = split_top_level_args(match.group(1))
        if len(args) < 4:
            continue

        original_token = args[1].strip()
        translation_token = args[3].strip()
        if original_token == "NULL" or translation_token == "NULL":
            continue

        original = parse_quoted_string(original_token)
        translation = parse_quoted_string(translation_token)
        if original.strip() and translation.strip():
            yield original, translation


# =========================
# MG binary parsing
# =========================


class ParseError(Exception):
    pass


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def seek(self, pos: int) -> None:
        if pos < 0 or pos > len(self.data):
            raise ParseError(f"seek out of range: {pos}")
        self.pos = pos

    def read_u8(self) -> int:
        if self.pos + 1 > len(self.data):
            raise ParseError("unexpected EOF (u8)")
        v = self.data[self.pos]
        self.pos += 1
        return v

    def read_bool(self) -> bool:
        return self.read_u8() != 0

    def read_i16(self) -> int:
        if self.pos + 2 > len(self.data):
            raise ParseError("unexpected EOF (i16)")
        v = struct.unpack_from("<h", self.data, self.pos)[0]
        self.pos += 2
        return v

    def read_i32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise ParseError("unexpected EOF (i32)")
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_bytes(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise ParseError("unexpected EOF (bytes)")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def read_7bit_int(self) -> int:
        value = 0
        shift = 0
        for _ in range(5):
            b = self.read_u8()
            value |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return value
            shift += 7
        raise ParseError("invalid 7-bit int")

    def read_string(self) -> str:
        length = self.read_7bit_int()
        raw = self.read_bytes(length)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="ignore")


# Buriko command IDs
CMD_RETURN = 0
CMD_LINE = 1
CMD_OPERATION = 2

# Buriko value type IDs
TYPE_NULL = 1
TYPE_INT = 2
TYPE_STRING = 3
TYPE_BOOL = 4
TYPE_VARIABLE = 5
TYPE_OPERATION = 6
TYPE_MATH = 8

# Nested operation argc table used in value decoding
# (needed for reading OutputLine fifth parameter safely)
NESTED_OP_ARGC = {
    4: 1,  # GetLocalFlag
    5: 1,  # GetGlobalFlag
    111: 1,  # SetFontId
}

# OutputLine opcode differs across some chapters
OUTPUTLINE_OPS = {16, 17}


def _peek_i16(data: bytes, pos: int) -> Optional[int]:
    if pos < 0 or pos + 2 > len(data):
        return None
    return struct.unpack_from("<h", data, pos)[0]


def _read_reference(r: Reader) -> dict:
    t = r.read_i16()
    if t != TYPE_VARIABLE:
        raise ParseError(f"reference must start with TYPE_VARIABLE, got {t}")

    prop = r.read_string()
    member = _read_value(r)
    has_ref = r.read_bool()
    sub_ref = _read_reference(r) if has_ref else None
    return {"prop": prop, "member": member, "ref": sub_ref}


def _read_value(r: Reader) -> Any:
    t = r.read_i16()

    if t == TYPE_NULL:
        return None
    if t == TYPE_INT:
        return r.read_i32()
    if t == TYPE_STRING:
        return r.read_string()
    if t == TYPE_BOOL:
        return r.read_bool()

    if t == TYPE_VARIABLE:
        # Engine seeks back and reads as reference
        r.seek(r.pos - 2)
        return {"__var__": _read_reference(r)}

    if t == TYPE_MATH:
        _ = r.read_i16()  # math opcode
        a = _read_value(r)
        b = _read_value(r)
        return {"__math__": (a, b)}

    if t == TYPE_OPERATION:
        op = r.read_i16()
        argc = NESTED_OP_ARGC.get(op)
        if argc is None:
            raise ParseError(f"unsupported nested operation opcode: {op}")
        params = [_read_value(r) for _ in range(argc)]
        return {"__op__": op, "params": params}

    raise ParseError(f"unsupported value type: {t}")


def _read_mg_data_segment(file_bytes: bytes) -> bytes:
    """Read MGSC container header and return the command data segment."""
    r = Reader(file_bytes)

    if r.read_bytes(4) != b"MGSC":
        raise ParseError("invalid MGSC header")

    version = r.read_i32()
    if version != 1:
        raise ParseError(f"unsupported MG version: {version}")

    block_count = r.read_i32()
    line_count = r.read_i32()
    data_len = r.read_i32()

    for _ in range(block_count):
        _ = r.read_string()
        _ = r.read_i32()

    for _ in range(line_count):
        _ = r.read_i32()

    return r.read_bytes(data_len)


def extract_pairs_from_mg(file_bytes: bytes) -> Iterator[Tuple[str, str]]:
    """Extract original/translation pairs from compiled .mg by decoding OutputLine operation arguments."""
    seg = _read_mg_data_segment(file_bytes)

    i = 0
    n = len(seg)
    while i <= n - 4:
        cmd = _peek_i16(seg, i)
        op = _peek_i16(seg, i + 2)

        if cmd == CMD_OPERATION and op in OUTPUTLINE_OPS:
            r = Reader(seg, i + 4)
            try:
                _p1 = _read_value(r)
                p2 = _read_value(r)
                _p3 = _read_value(r)
                p4 = _read_value(r)
                _p5 = _read_value(r)
            except ParseError:
                i += 1
                continue

            if (
                isinstance(p2, str)
                and isinstance(p4, str)
                and p2.strip()
                and p4.strip()
            ):
                yield p2, p4

            i = r.pos
            continue

        i += 1


def iter_input_files(root: Path) -> List[Path]:
    files = list(root.rglob("*.txt")) + list(root.rglob("*.mg"))
    return sorted(set(files))


def extract_from_file(path: Path) -> Iterator[Tuple[str, str]]:
    suffix = path.suffix.lower()

    if suffix == ".txt":
        text = path.read_text(encoding="utf-8")
        yield from extract_pairs_from_txt(text)
        return

    if suffix == ".mg":
        data = path.read_bytes()
        yield from extract_pairs_from_mg(data)
        return


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract text from Higurashi .txt/.mg scripts"
    )
    parser.add_argument("input_dir", help="Input directory")
    parser.add_argument("output_csv", help="Output CSV path")
    args = parser.parse_args()

    root = Path(args.input_dir)
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Input directory is missing or not a directory: {root}")

    files = iter_input_files(root)
    rows: List[Tuple[str, str, str]] = []

    for p in files:
        try:
            for original, translation in extract_from_file(p):
                rows.append((p.name, original, translation))
        except ParseError:
            continue

    out_path = Path(args.output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "original", "translation"])
        writer.writerows(rows)

    print(f"Done: scanned {len(files)} files, extracted {len(rows)} rows -> {out_path}")


if __name__ == "__main__":
    main()
