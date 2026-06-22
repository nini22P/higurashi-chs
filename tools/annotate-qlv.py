import csv, re, struct, sys, io
import lief

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ELF_PATH = "assets/exefs/main.elf"
CSV_PATH = "binary.csv"
R_AARCH64_RELATIVE = 0x403


def get_qlv_label(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("ascii", errors="replace")


def main():
    elf = lief.parse(ELF_PATH)
    rodata = next(s for s in elf.sections if s.name == ".rodata")
    rela = next(s for s in elf.sections if s.name == ".rela.dyn")

    rodata_va = rodata.virtual_address
    rodata_off = rodata.file_offset

    data = bytes(rela.content)
    entries: list = []
    for i in range(len(data) // 24):
        r_off, r_info, r_add = struct.unpack_from("<QQQ", data, i * 24)
        if (r_info & 0xFFFFFFFF) == R_AARCH64_RELATIVE:
            entries.append((r_off, r_add))
    entries.sort()

    rodata_bytes = bytes(rodata.content)
    qlv_vas: dict = {}
    for m in re.finditer(rb"qlv\d+_\d+\x00", rodata_bytes):
        va = rodata_va + m.start()
        label = get_qlv_label(m.group())
        qlv_vas[va] = label

    va_to_qlvs: dict = {}
    for idx, (r_off, r_add) in enumerate(entries):
        if r_add not in qlv_vas:
            continue
        qlv_name = qlv_vas[r_add]
        for j in range(1, 5):
            if idx + j >= len(entries):
                break
            answer_va = entries[idx + j][1]
            slot = chr(64 + j)  # 1→A, 2→B, 3→C, 4→D
            va_to_qlvs.setdefault(answer_va, set()).add(f"{qlv_name}_{slot}")

    print(f"Found {len(va_to_qlvs)} unique answer VAs across {len(qlv_vas)} QLV groups", file=sys.stderr)

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys()) if rows else []
    updated = 0
    for row in rows:
        oh = row.get("offset_hou", "").strip()
        if not oh:
            continue
        try:
            file_off = int(oh, 16)
        except ValueError:
            continue
        va = file_off - rodata_off + rodata_va
        qlv_set = va_to_qlvs.get(va)
        if qlv_set:
            row["note"] = "|".join(sorted(qlv_set))
            updated += 1

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Annotated {updated} rows in {CSV_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
