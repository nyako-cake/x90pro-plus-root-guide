#!/usr/bin/env python3
"""Give a version-less DirtyFrag module the `__versions` table + vermagic it needs.

The modules embedded in DirtyFrag's libdfroot.so are built without symbol
version info (their `__versions` section is empty) and carry a GKI vermagic.
On a kernel with CONFIG_MODVERSIONS=y and CONFIG_MODULE_FORCE_LOAD=n this is
rejected at module_layout check time.

This tool:
  1. rewrites the `.modinfo` vermagic string (the kernel compares it with its
     own full vermagic when the module has CRC entries);
  2. fills the existing (empty) `__versions` section with `<name, crc>` records
     using CRCs recovered from the target kernel.

Usage:
    python patch_ko.py dfroot-android13-5.15.ko \
        --crcs crcs.json \
        --vermagic "5.15.137-ge30fcc60efc0-dirty SMP preempt mod_unload modversions vivo aarch64" \
        --out dfroot-patched.ko

`crcs.json` is the output of kernel_crcs.py and must contain at least
`module_layout` plus every undefined symbol of the module.
"""
import argparse
import json
import struct

MODVERSION_SIZE = 64  # char name[56]; unsigned long crc (8 bytes on arm64)


def section_names(ko, shdrs, shstrndx):
    shstr = shdrs[shstrndx]
    names = []
    for sh in shdrs:
        start = shstr["offset"] + sh["name"]
        end = ko.find(b"\0", start)
        names.append(ko[start:end].decode("latin1"))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ko")
    ap.add_argument("--crcs", required=True)
    ap.add_argument("--vermagic", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ko = bytearray(open(args.ko, "rb").read())
    if ko[:4] != b"\x7fELF":
        raise SystemExit("not an ELF object")

    shoff = struct.unpack_from("<Q", ko, 0x28)[0]
    shentsize = struct.unpack_from("<H", ko, 0x3A)[0]
    shnum = struct.unpack_from("<H", ko, 0x3C)[0]
    shstrndx = struct.unpack_from("<H", ko, 0x3E)[0]
    if shentsize != 64:
        raise SystemExit("unexpected ELF64 section header size")

    shdrs = []
    for i in range(shnum):
        b = shoff + i * shentsize
        name, typ, flags, addr, off, size, link, info, align, entsize = \
            struct.unpack_from("<IIQQQQIIQQ", ko, b)
        shdrs.append(dict(name=name, type=typ, flags=flags, addr=addr, offset=off,
                          size=size, link=link, info=info, align=align, entsize=entsize))
    names = section_names(ko, shdrs, shstrndx)

    # ---- 1. patch .modinfo vermagic -------------------------------------
    mi = names.index(".modinfo")
    sec = shdrs[mi]
    entries = [e for e in bytes(ko[sec["offset"]:sec["offset"] + sec["size"]]).split(b"\0") if e]
    entries = [e for e in entries if not e.startswith(b"vermagic=")]
    entries.append(b"vermagic=" + args.vermagic.encode())
    blob = b"\0".join(entries) + b"\0"
    if len(blob) > sec["size"]:
        raise SystemExit(".modinfo too small for new vermagic (%d > %d)" % (len(blob), sec["size"]))
    ko[sec["offset"]:sec["offset"] + sec["size"]] = blob + b"\0" * (sec["size"] - len(blob))

    # ---- 2. fill __versions --------------------------------------------
    vi = names.index("__versions")
    crcs = json.load(open(args.crcs))
    if "module_layout" not in crcs:
        raise SystemExit("crcs.json must contain module_layout")

    vers = bytearray()
    for name, crc in crcs.items():
        raw = name.encode()
        if len(raw) >= 56:
            raise SystemExit("symbol name too long for __versions: %s" % name)
        vers += raw + b"\0" * (56 - len(raw)) + struct.pack("<Q", int(crc, 0))
    if len(vers) % MODVERSION_SIZE:
        raise SystemExit("internal: bad version record size")

    while len(ko) % 8:
        ko.append(0)
    vers_off = len(ko)
    ko += vers

    struct.pack_into("<QQ", ko, shoff + vi * shentsize + 16, vers_off, len(vers))
    with open(args.out, "wb") as f:
        f.write(ko)
    print("wrote %s (%d bytes, %d version records)" % (args.out, len(ko), len(vers) // MODVERSION_SIZE))


if __name__ == "__main__":
    main()
