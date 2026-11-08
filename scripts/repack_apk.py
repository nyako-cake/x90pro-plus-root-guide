#!/usr/bin/env python3
"""Replace files inside an APK without rebuilding it.

Usage:
    python repack_apk.py in.apk out.apk \
        lib/arm64-v8a/libdfroot.so=build/libdfroot.so \
        lib/arm64-v8a/libbootstrap.so=build/libbootstrap.so

The output is unsigned. Align and sign it before installing, e.g.:

    zipalign -f 4 out.apk out-aligned.apk
    apksigner sign --ks my.jks --out signed.apk out-aligned.apk
"""
import argparse
import sys
import zipfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("apk")
    ap.add_argument("out")
    ap.add_argument("replace", nargs="+", help="entry=local_file")
    args = ap.parse_args()

    mapping = {}
    for item in args.replace:
        if "=" not in item:
            sys.exit("bad replacement (want entry=file): %s" % item)
        entry, path = item.split("=", 1)
        mapping[entry] = path

    with zipfile.ZipFile(args.apk) as zin, zipfile.ZipFile(args.out, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in mapping:
                with open(mapping[info.filename], "rb") as f:
                    data = f.read()
                print("replaced %s (%d bytes)" % (info.filename, len(data)))
            new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            new.internal_attr = info.internal_attr
            new.create_system = info.create_system
            zout.writestr(new, data)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
