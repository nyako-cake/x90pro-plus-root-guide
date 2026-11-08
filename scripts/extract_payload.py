#!/usr/bin/env python3
"""Extract a partition from an Android OTA payload.bin (ChromeOS update_engine format).

Usage:
    python extract_payload.py payload.bin boot boot.img
    python extract_payload.py payload.bin init_boot init_boot.img
    python extract_payload.py payload.bin vendor_boot vendor_boot.img
    python extract_payload.py payload.bin --list

Supports REPLACE, REPLACE_BZ, REPLACE_XZ, ZERO, DISCARD operations.
No external dependencies.
"""
import argparse
import bz2
import lzma
import struct
import sys

TYPE_NAMES = {
    0: "REPLACE", 1: "REPLACE_BZ", 2: "MOVE", 3: "BSDIFF", 4: "SOURCE_COPY",
    5: "SOURCE_BSDIFF", 6: "ZERO", 7: "DISCARD", 8: "REPLACE_XZ", 9: "PUFFDIFF",
    10: "BROTLI_BSDIFF", 11: "ZUCCHINI", 12: "LZ4DIFF_BSDIFF", 13: "LZ4DIFF_PUFFDIFF",
}


def read_varint(buf, i):
    value = 0
    shift = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, i
        shift += 7


def parse_fields(buf, start=0, end=None):
    if end is None:
        end = len(buf)
    out = []
    i = start
    while i < end:
        key, i = read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if field == 0 or wire in (3, 4, 6, 7):
            raise ValueError("bad protobuf field at %d" % i)
        if wire == 0:
            val, i = read_varint(buf, i)
        elif wire == 2:
            ln, i = read_varint(buf, i)
            val = buf[i:i + ln]
            i += ln
        elif wire == 5:
            val = buf[i:i + 4]
            i += 4
        elif wire == 1:
            val = buf[i:i + 8]
            i += 8
        out.append((field, wire, val))
    return out


def load_manifest(path):
    with open(path, "rb") as f:
        head = f.read(24)
        if head[:4] != b"CrAU":
            raise SystemExit("not a payload.bin (bad magic)")
        version = struct.unpack(">Q", head[4:12])[0]
        manifest_size = struct.unpack(">Q", head[12:20])[0]
        sig_size = struct.unpack(">I", head[20:24])[0]
        manifest = f.read(manifest_size)
    data_start = 24 + manifest_size + sig_size
    return version, manifest, data_start


def parse_partitions(manifest):
    parts = []
    for field, wire, val in parse_fields(manifest):
        if field != 13 or wire != 2:
            continue
        name, size, ops = None, 0, []
        for f2, w2, v2 in parse_fields(val):
            if f2 == 1 and w2 == 2:
                name = v2.decode()
            elif f2 == 7 and w2 == 2:
                for f3, w3, v3 in parse_fields(v2):
                    if f3 == 1 and w3 == 0:
                        size = v3
            elif f2 == 8 and w2 == 2:
                op = {"type": 0, "offset": 0, "length": 0, "extents": []}
                for f3, w3, v3 in parse_fields(v2):
                    if f3 == 1 and w3 == 0:
                        op["type"] = v3
                    elif f3 == 2 and w3 == 0:
                        op["offset"] = v3
                    elif f3 == 3 and w3 == 0:
                        op["length"] = v3
                    elif f3 == 6 and w3 == 2:
                        start_block = num_blocks = 0
                        for f4, w4, v4 in parse_fields(v3):
                            if f4 == 1:
                                start_block = v4
                            elif f4 == 2:
                                num_blocks = v4
                        op["extents"].append((start_block, num_blocks))
                ops.append(op)
        parts.append((name, size, ops))
    return parts


def extract(payload, part_name, out_path):
    _, manifest, data_start = load_manifest(payload)
    parts = parse_partitions(manifest)
    for name, size, ops in parts:
        if name != part_name:
            continue
        buf = bytearray(size)
        with open(payload, "rb") as f:
            for op in ops:
                if op["type"] in (0, 1, 8):
                    f.seek(data_start + op["offset"])
                    data = f.read(op["length"])
                    if op["type"] == 1:
                        data = bz2.decompress(data)
                    elif op["type"] == 8:
                        data = lzma.decompress(data)
                    pos = 0
                    for start_block, num_blocks in op["extents"]:
                        dst = start_block * 4096
                        chunk = data[pos:pos + num_blocks * 4096]
                        buf[dst:dst + len(chunk)] = chunk
                        pos += num_blocks * 4096
                elif op["type"] in (6, 7):
                    for start_block, num_blocks in op["extents"]:
                        dst = start_block * 4096
                        buf[dst:dst + num_blocks * 4096] = b"\0" * (num_blocks * 4096)
                else:
                    raise SystemExit("unsupported op type %d in %s" % (op["type"], part_name))
        with open(out_path, "wb") as f:
            f.write(buf)
        print("wrote %s (%d bytes) -> %s" % (part_name, size, out_path))
        return
    raise SystemExit("partition not found: %s" % part_name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("payload")
    ap.add_argument("partition", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        _, manifest, _ = load_manifest(args.payload)
        for name, size, ops in parse_partitions(manifest):
            types = {}
            for op in ops:
                key = TYPE_NAMES.get(op["type"], str(op["type"]))
                types[key] = types.get(key, 0) + 1
            print("%-24s %12d %5d %s" % (name, size, len(ops), types))
        return
    if not args.partition or not args.output:
        ap.error("partition and output are required (or use --list)")
    extract(args.payload, args.partition, args.output)


if __name__ == "__main__":
    main()
