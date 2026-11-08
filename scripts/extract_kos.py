#!/usr/bin/env python3
"""Split the kernel modules embedded in DirtyFrag's libdfroot.so.

DirtyFrag (and the DirtyFrag-vr fork) `.incbin`s eight per-KMI `dfroot-*.ko`
images into libdfroot.so. This script finds every ELF inside the .so, reads its
`.modinfo` vermagic, and writes each module to `outdir` with a name derived from
the vermagic.

Usage:
    python extract_kos.py libdfroot.so outdir/
"""
import os
import struct
import sys


def elf_size(buf, off):
    """Return the size of the ELF starting at `off` (via its section headers)."""
    shoff = struct.unpack_from("<Q", buf, off + 0x28)[0]
    shentsize = struct.unpack_from("<H", buf, off + 0x3A)[0]
    shnum = struct.unpack_from("<H", buf, off + 0x3C)[0]
    end = shoff + shentsize * shnum
    for i in range(shnum):
        b = off + shoff + i * shentsize
        _, _, _, _, sec_off, sec_size, _, _, _, _ = struct.unpack_from("<IIQQQQIIQQ", buf, b)
        if sec_off and sec_size:
            end = max(end, sec_off + sec_size)
    return end


def sections(buf, off):
    shoff = struct.unpack_from("<Q", buf, off + 0x28)[0]
    shentsize = struct.unpack_from("<H", buf, off + 0x3A)[0]
    shnum = struct.unpack_from("<H", buf, off + 0x3C)[0]
    shstrndx = struct.unpack_from("<H", buf, off + 0x3E)[0]
    secs = []
    for i in range(shnum):
        b = off + shoff + i * shentsize
        vals = struct.unpack_from("<IIQQQQIIQQ", buf, b)
        secs.append(dict(name=vals[0], offset=vals[4], size=vals[5]))
    shstr = secs[shstrndx]

    def name_of(sec):
        start = off + shstr["offset"] + sec["name"]
        end = buf.find(b"\0", start)
        return buf[start:end].decode("latin1")

    for s in secs:
        s["sname"] = name_of(s)
    return secs


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: extract_kos.py <libdfroot.so> <outdir>")
    so_path, outdir = sys.argv[1], sys.argv[2]
    buf = open(so_path, "rb").read()
    os.makedirs(outdir, exist_ok=True)

    found = 0
    pos = buf.find(b"\x7fELF")
    while pos != -1:
        try:
            secs = sections(buf, pos)
            modinfo = next((s for s in secs if s["sname"] == ".modinfo"), None)
            if modinfo:
                raw = buf[pos + modinfo["offset"]:pos + modinfo["offset"] + modinfo["size"]]
                idx = raw.find(b"vermagic=")
                if idx >= 0:
                    vermagic = raw[idx + 9:raw.find(b"\0", idx)].decode("latin1")
                    size = elf_size(buf, pos)
                    name = "dfroot-" + vermagic.split(" ")[0].replace("/", "_") + ".ko"
                    with open(os.path.join(outdir, name), "wb") as f:
                        f.write(buf[pos:pos + size])
                    print("%-60s %6d bytes -> %s" % (vermagic[:60], size, name))
                    found += 1
                    pos = buf.find(b"\x7fELF", pos + size)
                    continue
        except Exception:
            pass
        pos = buf.find(b"\x7fELF", pos + 4)

    if not found:
        raise SystemExit("no embedded kernel modules found")
    print("extracted %d modules" % found)


if __name__ == "__main__":
    main()
