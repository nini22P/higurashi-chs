import csv, os, sys, struct
import lief
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import (
    ARM64_INS_ADRP, ARM64_INS_ADD,
    ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_MEM,
    ARM64_REG_X0
)
from typing import List, Tuple

R_AARCH64_RELATIVE = 0x403
RELOC_AARCH64_RELATIVE = lief.ELF.Relocation.TYPE.AARCH64_RELATIVE


def enc_adrp(imm: int, rd: int) -> bytes:
    imml = imm & 0x3
    immhi = (imm >> 2) & 0x7FFFF
    return struct.pack("<I", 0x90000000 | (imml << 29) | (immhi << 5) | (rd & 0x1F))


def enc_add(rd: int, rn: int, imm12: int) -> bytes:
    return struct.pack("<I", 0x91000000 | (imm12 << 10) | ((rn & 0x1F) << 5) | (rd & 0x1F))


def dec_adrp_imm(buf: bytearray) -> int:
    v = struct.unpack("<I", bytes(buf[:4]))[0]
    imm = (((v >> 5) & 0x7FFFF) << 2) | ((v >> 29) & 3)
    return imm - 0x200000 if imm & 0x100000 else imm


class Relocator:
    def __init__(self, elf, csv_path: str, encoding: str):
        self.elf = elf
        self.csv_path = csv_path
        self.encoding = encoding
        def _find_section(name):
            sec = next((s for s in self.elf.sections if s.name == name), None)
            if sec is None:
                raise ValueError(f"Required section '{name}' not found in ELF")
            return sec
        self.rodata = _find_section(".rodata")
        self.text_sec = _find_section(".text")
        self.rela = _find_section(".rela.dyn")
        self.ro_load = None
        for seg in self.elf.segments:
            if seg.type == lief.ELF.Segment.TYPE.LOAD:
                s, e = seg.virtual_address, seg.virtual_address + seg.virtual_size
                if s <= self.rodata.virtual_address < e:
                    self.ro_load = seg
                    break
        assert self.ro_load is not None, "Cannot find LOAD segment for .rodata"

    def csv_off_to_va(self, file_off: int) -> int:
        return file_off - self.rodata.file_offset + self.rodata.virtual_address

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

    def find_rela_refs(self, str_va: int) -> List[Tuple[int, int]]:
        data = bytes(self.rela.content)
        res = []
        for i in range(len(data) // 24):
            off, info, add = struct.unpack_from("<QQQ", data, i * 24)
            if (info & 0xFFFFFFFF) == R_AARCH64_RELATIVE and add == str_va:
                res.append((off, add))
        return res

    def find_adrp_refs(self, text_bytes: bytes, text_va: int, str_va: int) -> List[Tuple[int, int, str, int, int]]:
        page = str_va & ~0xFFF
        off = str_va & 0xFFF
        refs = []

        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        md.detail = True
        md.skipdata = True

        adrps = []
        for insn in md.disasm(text_bytes, text_va):
            if insn.id != ARM64_INS_ADRP:
                continue
            imm = dec_adrp_imm(insn.bytes)
            ip = (insn.address & ~0xFFF) + (imm << 12)
            rd = insn.operands[0].value.reg - ARM64_REG_X0
            adrps.append((insn.address, rd, ip))

        for a_addr, rd, ip in adrps:
            if ip != page:
                continue
            if a_addr - text_va < 4:
                continue
            win_off = a_addr - text_va - 4
            window = text_bytes[win_off: win_off + 40]
            for ji in md.disasm(window, a_addr - 4):
                if ji.address <= a_addr or ji.address > a_addr + 32:
                    continue
                if ji.id == ARM64_INS_ADD and len(ji.operands) >= 3:
                    o0, o1, o2 = ji.operands[:3]
                    if (o0.type == ARM64_OP_REG and o1.type == ARM64_OP_REG
                            and o1.value.reg - ARM64_REG_X0 == rd
                            and o2.type == ARM64_OP_IMM and o2.value.imm == off):
                        refs.append((a_addr, ji.address, "add", o0.value.reg - ARM64_REG_X0, rd))
                        break
        return refs

    def patch_ref(self, adrp_addr: int, new_va: int, add_addr: int, rd: int, rn: int):
        pc_page = adrp_addr & ~0xFFF
        imm = ((new_va & ~0xFFF) - pc_page) >> 12
        self.elf.patch_address(adrp_addr, list(enc_adrp(imm, rn)))
        self.elf.patch_address(add_addr, list(enc_add(rd, rn, new_va & 0xFFF)))

    def patch_rela(self, r_off: int, new_va: int):
        self.elf.patch_address(r_off, list(struct.pack("<Q", new_va)))
        for r in self.elf.relocations:
            if r.address == r_off and r.type == RELOC_AARCH64_RELATIVE:
                r.addend = new_va
                break

    def run(self):
        ovs = self.find_overflows()
        print(f"  Overflow entries: {len(ovs)}")
        if not ovs:
            return True

        text_bytes = bytes(self.text_sec.content)
        text_va = self.text_sec.virtual_address

        plan = []
        data_off = 0
        for ov in ovs:
            file_off = ov["offset"]
            ova = self.csv_off_to_va(file_off)
            print(f"\n  [CSV=0x{file_off:08x} VA=0x{ova:08x}] \"{ov['translation'][:50]}\"  extra=+{len(ov['encoded']) - ov['maxlen']}")
            rr = self.find_rela_refs(ova)
            ar = self.find_adrp_refs(text_bytes, text_va, ova)
            if rr:
                print(f"    RELA entries: {len(rr)}")
            if ar:
                print(f"    ADRP refs:    {len(ar)}")
            if not rr and not ar:
                print("    WARNING: No references found, skipping")
                continue
            nva = self.rodata.virtual_address + self.rodata.size + data_off
            plan.append(dict(orig_va=ova, new_va=nva, encoded=ov["encoded"],
                             rela_refs=rr, adrp_refs=ar))
            data_off += len(ov["encoded"]) + 1

        if not plan:
            return False

        total = sum(len(p["encoded"]) + 1 for p in plan)
        print(f"\n  Extending .rodata +0x{total:x}")
        cur = bytearray(bytes(self.rodata.content))
        rodata_va = self.rodata.virtual_address
        for p in plan:
            off = p["new_va"] - rodata_va
            cur[off:off + len(p["encoded"]) + 1] = p["encoded"] + b'\x00'
        old_r = self.rodata.size
        old_p = self.ro_load.physical_size
        old_v = self.ro_load.virtual_size
        self.rodata.content = list(cur)
        self.rodata.size = len(cur)
        self.ro_load.physical_size += total
        self.ro_load.virtual_size += total
        print(f"    .rodata: 0x{old_r:x} -> 0x{self.rodata.size:x}")
        print(f"    LOAD:    phys 0x{old_p:x} -> 0x{self.ro_load.physical_size:x}")
        print(f"             virt 0x{old_v:x} -> 0x{self.ro_load.virtual_size:x}")

        for p in plan:
            for r_off, _ in p["rela_refs"]:
                self.patch_rela(r_off, p["new_va"])
            for ref in p["adrp_refs"]:
                self.patch_ref(ref[0], p["new_va"], ref[1], ref[3], ref[4])
            print(f"    [0x{p['orig_va']:08x}] -> VA 0x{p['new_va']:x}")

        return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ELF String Relocation Tool (Switch ARM64)")
    parser.add_argument("-b", "--bin", required=True)
    parser.add_argument("-c", "--csv", required=True)
    parser.add_argument("-e", "--encoding", default="utf-8")
    args = parser.parse_args()

    if not os.path.exists(args.bin) or not os.path.exists(args.csv):
        print("Error: file not found")
        return 1

    elf = lief.parse(args.bin)
    if elf is None:
        print("Error: failed to parse ELF")
        return 1

    if elf.header.machine_type != lief.ELF.ARCH.AARCH64:
        print(f"Error: unsupported architecture {elf.header.machine_type}, need AARCH64")
        return 1

    print(f"Arch:  ARM64")
    print(f"CSV:   {args.csv}")
    print(f"Enc:   {args.encoding}")

    r = Relocator(elf, args.csv, args.encoding)
    ok = r.run()
    if ok:
        print(f"\nWriting: {args.bin}")
        elf.write(args.bin)
        print("Done!")
    else:
        print("\nNo changes made.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
