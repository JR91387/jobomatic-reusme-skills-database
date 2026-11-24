#!/usr/bin/env python3
"""Build assets/icon.icns (the macOS app icon) from assets/icon-256.png. Pure Python.

    python3 scripts/make_icns.py

An .icns file is a container: b"icns" + total length, then chunks of 4-byte type + length + data.
Chunk type "ic08" holds a 256x256 PNG as is, which every macOS since 10.5 reads."""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def icns_from_png(png):
    if not png.startswith(PNG_MAGIC) or png[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    width, height = struct.unpack(">II", png[16:24])
    if (width, height) != (256, 256):
        raise ValueError(f"ic08 needs a 256x256 PNG, got {width}x{height}")
    chunk = b"ic08" + struct.pack(">I", 8 + len(png)) + png
    return b"icns" + struct.pack(">I", 8 + len(chunk)) + chunk


def main(src=ROOT / "assets" / "icon-256.png", dest=ROOT / "assets" / "icon.icns"):
    data = icns_from_png(Path(src).read_bytes())
    Path(dest).write_bytes(data)
    print(f"wrote {dest} ({len(data)} bytes)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
