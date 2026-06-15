import csv, os, sys, struct
import lief


class Relocator:
    def __init__(self, elf, csv_path: str):
        self.elf = elf
        self.csv_path = csv_path
        self.encoding = "utf-16le"
        self.rx_seg = self._find_rx_seg()
        if self.rx_seg is None:
            raise ValueError("No RX LOAD segment found in ELF")

    def _find_rx_seg(self):
        for seg in self.elf.segments:
            t = str(seg.type)
            if t.endswith("LOAD"):
                if int(seg.flags) & 1:
                    return seg
        return None

    def file_off_to_va(self, file_off: int) -> int:
        return self.rx_seg.virtual_address + (file_off - self.rx_seg.file_offset)

    def find_overflows(self):
        ovs = []
        with open(self.csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                off_str = row.get("offset", "").strip()
                len_str = row.get("length", "").strip()
                trans = row.get("translation", "")
                if not off_str or not len_str or not trans:
                    continue
                try:
                    offset = int(off_str, 16)
                    maxlen = int(len_str)
                except ValueError:
                    continue
                enc = trans.encode(self.encoding, errors="strict")
                if len(enc) > maxlen:
                    ovs.append(dict(offset=offset, maxlen=maxlen,
                                    actuallen=len(enc), text=row.get("text", ""),
                                    translation=trans, encoded=enc))
        return ovs

    def find_u32_refs(self, seg_bytes: bytes, seg_va: int, str_va: int) -> list:
        """Find all 4-byte aligned u32 values matching str_va."""
        refs = []
        for i in range(0, len(seg_bytes) - 3, 4):
            val = struct.unpack_from("<I", seg_bytes, i)[0]
            if val == str_va:
                refs.append((seg_va + i, i))
        return refs

    def run(self):
        ovs = self.find_overflows()
        print(f"  Overflow entries: {len(ovs)}")
        if not ovs:
            return True

        seg_va = self.rx_seg.virtual_address
        seg_bytes = bytearray(bytes(self.rx_seg.content))

        plan = []
        data_off = 0
        for ov in ovs:
            file_off = ov["offset"]
            ova = self.file_off_to_va(file_off)
            print(f"\n  [CSV=0x{file_off:08x} VA=0x{ova:08x}] \"{ov['translation'][:50]}\"  extra=+{len(ov['encoded']) - ov['maxlen']}")

            refs = self.find_u32_refs(seg_bytes, seg_va, ova)
            if not refs:
                print("    WARNING: No u32 references found, skipping")
                continue

            print(f"    u32 refs:  {len(refs)}")
            nva = seg_va + len(seg_bytes) + data_off
            plan.append(dict(orig_va=ova, new_va=nva, encoded=ov["encoded"], refs=refs))
            data_off += len(ov["encoded"]) + 2

        if not plan:
            return False

        total = sum(len(p["encoded"]) + 2 for p in plan)
        old_phys = self.rx_seg.physical_size
        old_virt = self.rx_seg.virtual_size

        seg_bytes.extend(b'\x00' * total)
        for p in plan:
            off = p["new_va"] - seg_va
            seg_bytes[off:off + len(p["encoded"]) + 2] = p["encoded"] + b'\x00\x00'

        print(f"\n  Extending RX segment +0x{total:x}")
        print(f"    RX:      phys 0x{old_phys:x} -> 0x{len(seg_bytes):x}")
        print(f"             virt 0x{old_virt:x} -> 0x{old_virt + total:x}")

        for p in plan:
            for ref_va, ref_off in p["refs"]:
                struct.pack_into("<I", seg_bytes, ref_off, p["new_va"])
            print(f"    [0x{p['orig_va']:08x}] -> VA 0x{p['new_va']:x}")

        self.rx_new_data = bytes(seg_bytes)
        return True

    def _write_elf(self, bin_path: str):
        data = bytearray(open(bin_path, "rb").read())
        if data[:4] != b"\x7fELF":
            raise ValueError("Not a valid ELF")
        if data[4] != 1:
            raise ValueError("Only 32-bit ELF supported")
        endian = "<" if data[5] == 1 else ">"

        e_phoff = struct.unpack_from(endian + "I", data, 28)[0]
        e_phentsize = struct.unpack_from(endian + "H", data, 42)[0]
        e_phnum = struct.unpack_from(endian + "H", data, 44)[0]

        rx_info = None
        for i in range(e_phnum):
            ph_off = e_phoff + i * e_phentsize
            p_type = struct.unpack_from(endian + "I", data, ph_off)[0]
            if p_type != 1:
                continue
            p_flags = struct.unpack_from(endian + "I", data, ph_off + 24)[0]
            if not (p_flags & 1):
                continue
            p_offset = struct.unpack_from(endian + "I", data, ph_off + 4)[0]
            if p_offset == self.rx_seg.file_offset:
                rx_info = dict(ph_off=ph_off, p_offset=p_offset,
                               p_filesz=struct.unpack_from(endian + "I", data, ph_off + 16)[0])
                break

        if rx_info is None:
            raise ValueError("Cannot find RX segment in ELF")

        old_filesz = rx_info["p_filesz"]
        new_data = self.rx_new_data
        new_filesz = len(new_data)
        delta = new_filesz - old_filesz

        if delta > 0:
            tail = data[rx_info["p_offset"] + old_filesz:]
            data[rx_info["p_offset"] + new_filesz:] = tail

        data[rx_info["p_offset"]:rx_info["p_offset"] + new_filesz] = new_data

        for i in range(e_phnum):
            ph_off = e_phoff + i * e_phentsize
            po = struct.unpack_from(endian + "I", data, ph_off + 4)[0]
            pt = struct.unpack_from(endian + "I", data, ph_off)[0]

            if i == list(range(e_phnum))[next(j for j in range(e_phnum)
                if struct.unpack_from(endian + "I", data, e_phoff + j * e_phentsize)[0] == 1
                and struct.unpack_from(endian + "I", data, e_phoff + j * e_phentsize + 24)[0] & 1
                and struct.unpack_from(endian + "I", data, e_phoff + j * e_phentsize + 4)[0] == self.rx_seg.file_offset)]:
                struct.pack_into(endian + "I", data, ph_off + 16, new_filesz)
                struct.pack_into(endian + "I", data, ph_off + 20, new_filesz)
            elif po >= rx_info["p_offset"] + old_filesz:
                po += delta
                struct.pack_into(endian + "I", data, ph_off + 4, po)

        open(bin_path, "wb").write(data)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PSV eboot UTF-16LE String Relocation Tool")
    parser.add_argument("-b", "--bin", required=True)
    parser.add_argument("-c", "--csv", required=True)
    args = parser.parse_args()

    if not os.path.exists(args.bin) or not os.path.exists(args.csv):
        print("Error: file not found")
        return 1

    elf = lief.parse(args.bin)
    if elf is None:
        print("Error: failed to parse ELF")
        return 1

    print(f"Arch:  ARM32 Thumb")
    print(f"CSV:   {args.csv}")

    r = Relocator(elf, args.csv)
    ok = r.run()
    if ok:
        print(f"\nWriting: {args.bin}")
        r._write_elf(args.bin)
        print("Done!")
    else:
        print("\nNo changes made.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
