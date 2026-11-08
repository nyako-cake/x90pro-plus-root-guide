#!/usr/bin/env python3
"""
vendor_boot_tool.py - 解析 Android vendor_boot 镜像（v3/v4）

适用：vivo / iQOO 等 A/B 设备，用来查看 vendor_boot 的分区布局、
提取 vendor ramdisk、解压 LZ4 legacy 压缩的 cpio，并列出 / 查找其中的文件
（例如 vendor_boot 里的 vr.ko、modules.load 等）。

依赖：Python 3.8+；解压 LZ4 需要 `pip install lz4`。

用法：
    python vendor_boot_tool.py info  vendor_boot.img
    python vendor_boot_tool.py ramdisk vendor_boot.img -o vb_ramdisk.bin
    python vendor_boot_tool.py cpio  vendor_boot.img -o vb_ramdisk.cpio
    python vendor_boot_tool.py list  vendor_boot.img
    python vendor_boot_tool.py find  vendor_boot.img vr.ko

说明：
- 只读取文件，不修改镜像；
- LZ4 legacy（magic 02 21 4c 18）按 4 字节小端块长切块，逐块解压；
- cpio 支持 newc（070701）格式，列出文件名/大小；
- 需要重新打包（例如删除 vr.ko）时，先 `cpio` 导出，改完再按 4 MB 块重新 LZ4 压缩，
  并重建 v4 头（vendor_ramdisk_size / dtb 偏移 / v4 table / bootconfig 都要同步更新）。
"""
import argparse
import io
import struct
import sys

MAGIC = b"VNDRBOOT"
LZ4_LEGACY_MAGIC = b"\x02\x21\x4c\x18"
CPIO_NEWC_MAGIC = b"070701"


def parse_header(data):
    if data[:8] != MAGIC:
        raise SystemExit("not a vendor_boot image (missing VNDRBOOT magic)")
    version, page_size, kernel_addr, ramdisk_addr, ramdisk_size = struct.unpack_from("<IIIII", data, 8)
    tags_addr = struct.unpack_from("<I", data, 28 + 2048)[0]
    name = data[28 + 2048 + 4 : 28 + 2048 + 20].split(b"\x00")[0].decode("ascii", "replace")
    header_size = struct.unpack_from("<I", data, 28 + 2048 + 20)[0]
    dtb_size = struct.unpack_from("<I", data, 28 + 2048 + 24)[0]
    dtb_addr = struct.unpack_from("<Q", data, 28 + 2048 + 28)[0]
    hdr = {
        "header_version": version,
        "page_size": page_size,
        "kernel_addr": kernel_addr,
        "ramdisk_addr": ramdisk_addr,
        "vendor_ramdisk_size": ramdisk_size,
        "tags_addr": tags_addr,
        "name": name,
        "header_size": header_size,
        "dtb_size": dtb_size,
        "dtb_addr": dtb_addr,
    }
    if version >= 4:
        (hdr["table_size"], hdr["table_entry_num"], hdr["table_entry_size"], hdr["bootconfig_size"]) = struct.unpack_from(
            "<IIII", data, 28 + 2048 + 36
        )
    ramdisk_off = page_size
    hdr["ramdisk_offset"] = ramdisk_off
    dtb_off = (ramdisk_off + ramdisk_size + page_size - 1) // page_size * page_size
    hdr["dtb_offset"] = dtb_off
    if version >= 4:
        table_off = (dtb_off + dtb_size + page_size - 1) // page_size * page_size
        hdr["table_offset"] = table_off
        bootconfig_off = (table_off + hdr["table_size"] + page_size - 1) // page_size * page_size
        hdr["bootconfig_offset"] = bootconfig_off
    return hdr


def extract_ramdisk(data):
    h = parse_header(data)
    return data[h["ramdisk_offset"] : h["ramdisk_offset"] + h["vendor_ramdisk_size"]]


def lz4_legacy_decompress(blob):
    if blob[:4] != LZ4_LEGACY_MAGIC:
        return blob  # 假定已经是未压缩 cpio
    try:
        import lz4.block
    except ImportError:
        raise SystemExit("need python lz4: pip install lz4")
    pos = 4
    out = bytearray()
    max_block = 8 * 1024 * 1024
    while pos + 4 <= len(blob):
        size = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        if size == 0 or pos + size > len(blob):
            break
        out += lz4.block.decompress(blob[pos : pos + size], uncompressed_size=max_block)
        pos += size
    return bytes(out)


def cpio_entries(cpio):
    if cpio[:6] != CPIO_NEWC_MAGIC:
        raise SystemExit("not a newc cpio archive (magic %r)" % cpio[:6])
    pos = 0
    while pos + 110 <= len(cpio):
        hdr = cpio[pos : pos + 110]
        if hdr[:6] != CPIO_NEWC_MAGIC:
            break
        fields = [int(hdr[6 + i * 8 : 14 + i * 8], 16) for i in range(13)]
        mode, filesize, namesize = fields[1], fields[6], fields[11]
        name = cpio[pos + 110 : pos + 110 + namesize - 1].decode("utf-8", "replace")
        data_off = pos + 110 + namesize
        data_off = (data_off + 3) & ~3
        if name == "TRAILER!!!":
            break
        yield name, mode, filesize, data_off
        pos = (data_off + filesize + 3) & ~3


def cmd_info(args):
    data = open(args.image, "rb").read()
    h = parse_header(data)
    print("image        :", args.image, "(%d bytes)" % len(data))
    for k in [
        "header_version", "page_size", "vendor_ramdisk_size", "ramdisk_offset",
        "dtb_size", "dtb_offset", "header_size", "name",
    ]:
        print("%-13s: %s" % (k, h[k]))
    if h["header_version"] >= 4:
        for k in ["table_offset", "table_size", "table_entry_num", "table_entry_size", "bootconfig_offset", "bootconfig_size"]:
            print("%-13s: %s" % (k, h[k]))
        if h["table_size"] and h["table_entry_num"]:
            for i in range(h["table_entry_num"]):
                base = h["table_offset"] + i * h["table_entry_size"]
                r_size, r_off, r_type = struct.unpack_from("<III", data, base)
                r_name = data[base + 12 : base + 44].split(b"\x00")[0].decode("ascii", "replace")
                print("  entry %d: size=%d offset=%d type=%d name=%r" % (i, r_size, r_off, r_type, r_name))


def cmd_ramdisk(args):
    data = open(args.image, "rb").read()
    blob = extract_ramdisk(data)
    open(args.out, "wb").write(blob)
    print("vendor ramdisk ->", args.out, len(blob), "bytes")


def cmd_cpio(args):
    data = open(args.image, "rb").read()
    cpio = lz4_legacy_decompress(extract_ramdisk(data))
    open(args.out, "wb").write(cpio)
    print("cpio ->", args.out, len(cpio), "bytes")


def cmd_list(args):
    data = open(args.image, "rb").read()
    cpio = lz4_legacy_decompress(extract_ramdisk(data))
    n = 0
    for name, mode, size, _ in cpio_entries(cpio):
        print("%8d  %s" % (size, name))
        n += 1
    print("# %d entries" % n)


def cmd_find(args):
    data = open(args.image, "rb").read()
    cpio = lz4_legacy_decompress(extract_ramdisk(data))
    needle = args.name.lower()
    hits = 0
    for name, mode, size, _ in cpio_entries(cpio):
        if needle in name.lower():
            print("%8d  %s" % (size, name))
            hits += 1
    print("# %d match(es)" % hits)


def main():
    ap = argparse.ArgumentParser(description="parse Android vendor_boot (v3/v4)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="print header / table layout")
    p.add_argument("image")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("ramdisk", help="extract raw vendor ramdisk blob")
    p.add_argument("image")
    p.add_argument("-o", "--out", default="vb_ramdisk.bin")
    p.set_defaults(func=cmd_ramdisk)

    p = sub.add_parser("cpio", help="decompress LZ4 legacy and save cpio")
    p.add_argument("image")
    p.add_argument("-o", "--out", default="vb_ramdisk.cpio")
    p.set_defaults(func=cmd_cpio)

    p = sub.add_parser("list", help="list cpio entries")
    p.add_argument("image")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("find", help="find entries by substring")
    p.add_argument("image")
    p.add_argument("name")
    p.set_defaults(func=cmd_find)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
