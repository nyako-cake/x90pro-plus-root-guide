#!/usr/bin/env python3
"""Recover exported-symbol CRCs from a vmlinux ELF produced by vmlinux-to-elf.

Why: DirtyFrag's embedded modules carry no `__versions` table, but the target
kernel has CONFIG_MODVERSIONS=y, so the loader rejects them. We rebuild the
table with the CRCs the *device kernel* actually exports.

Input is the ELF written by:
    vmlinux-to-elf --base-address <kernel base> Image vmlinux.elf

Some builds make vmlinux-to-elf emit symbol values relative to a different base
than the one the ELF sections use; `--symbol-shift` compensates (PD2227 with
5.15.137 needed 0x78000000).

Usage:
    python kernel_crcs.py vmlinux.elf --out crcs.json \
        --symbols module_layout,snprintf,register_kprobe,...

Output: {"symbol": "0x1234abcd", ...}
"""
import argparse
import json
import struct

from elftools.elf.elffile import ELFFile


def build_reader(elf_path, shift):
    f = open(elf_path, "rb")
    elf = ELFFile(f)
    sections = []
    for s in elf.iter_sections():
        if s["sh_type"] != "SHT_NOBITS" and s["sh_size"]:
            sections.append((s["sh_addr"], s["sh_size"], s["sh_offset"]))

    def read_at(vaddr, size):
        for attempt in (vaddr, vaddr + shift):
            for addr, sh_size, off in sections:
                if addr <= attempt < addr + sh_size:
                    f.seek(off + (attempt - addr))
                    return f.read(min(size, addr + sh_size - attempt))
        return None

    symbols = {}
    for s in elf.get_section_by_name(".symtab").iter_symbols():
        symbols.setdefault(s.name, s["st_value"])
    return read_at, symbols


def cstr(read_at, vaddr):
    data = read_at(vaddr, 256)
    if not data:
        return None
    return data.split(b"\0")[0].decode("latin1", "replace")


def read_table(read_at, start, end, crc_base):
    out = {}
    count = (end - start) // 12
    for i in range(count):
        entry = start + 12 * i
        raw = read_at(entry + 4, 4)
        if not raw:
            break
        name_off = struct.unpack("<i", raw)[0]
        name = cstr(read_at, entry + 4 + name_off)
        crc_raw = read_at(crc_base + 4 * i, 4)
        if name and crc_raw:
            out.setdefault(name, struct.unpack("<I", crc_raw)[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--symbol-shift", type=lambda v: int(v, 0), default=0x78000000)
    args = ap.parse_args()

    read_at, syms = build_reader(args.elf, args.symbol_shift)
    need = ["__start___ksymtab", "__stop___ksymtab", "__stop___ksymtab_gpl",
            "__start___kcrctab", "__start___kcrctab_gpl"]
    missing = [n for n in need if n not in syms]
    if missing:
        raise SystemExit("missing symbols in ELF: %s" % ", ".join(missing))

    ks, ke = syms["__start___ksymtab"], syms["__stop___ksymtab"]
    gks, gke = syms["__stop___ksymtab"], syms["__stop___ksymtab_gpl"]
    kc, gkc = syms["__start___kcrctab"], syms["__start___kcrctab_gpl"]

    table = read_table(read_at, ks, ke, kc)
    table.update(read_table(read_at, gks, gke, gkc))

    if args.symbols:
        wanted = [s for s in args.symbols.split(",") if s]
        result = {}
        for name in wanted:
            if name not in table:
                raise SystemExit("symbol not exported: %s" % name)
            result[name] = "0x%08x" % table[name]
    else:
        result = {k: "0x%08x" % v for k, v in table.items()}

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print("wrote %d CRCs -> %s" % (len(result), args.out))


if __name__ == "__main__":
    main()
