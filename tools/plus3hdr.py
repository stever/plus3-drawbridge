#!/usr/bin/env python3
"""Add a 128-byte +3DOS header to a file so the +3 can LOAD it.

  plus3hdr.py basic [--line N] in out      tokenised BASIC program (use bas2plus3.py to make one)
  plus3hdr.py code  --addr A   in out      CODE block loaded at address A
  plus3hdr.py strip in out                 remove a header

Header layout (+3 manual, chapter 8):
  0   "PLUS3DOS"      8   0x1A      9  issue 1     10  version 0
  11  total length incl. header (4 bytes LE)
  15  type: 0 BASIC, 1 numeric array, 2 char array, 3 CODE
  16  data length (2)     18  BASIC: autorun line / CODE: load address (2)
  20  BASIC: offset of variables (2)       22  unused
  127 checksum = sum(bytes 0..126) mod 256
"""
import struct
import sys


def header(ftype, length, p1, p2):
    h = bytearray(128)
    h[0:8] = b"PLUS3DOS"
    h[8] = 0x1A
    h[9] = 1
    h[11:15] = struct.pack("<I", 128 + length)
    h[15] = ftype
    h[16:18] = struct.pack("<H", length)
    h[18:20] = struct.pack("<H", p1)
    h[20:22] = struct.pack("<H", p2)
    h[127] = sum(h[:127]) & 0xFF
    return bytes(h)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    kind = a.pop(0)
    opts = {}
    while a and a[0].startswith("--"):
        k = a.pop(0)[2:]
        opts[k] = int(a.pop(0), 0)
    if len(a) != 2:
        sys.exit(__doc__)
    data = open(a[0], "rb").read()
    if kind == "strip":
        if data[:8] != b"PLUS3DOS":
            sys.exit("no +3DOS header found")
        out = data[128:]
    elif kind == "basic":
        line = opts.get("line", 0x8000)      # 0x8000 = no autorun
        out = header(0, len(data), line, len(data)) + data
    elif kind == "code":
        if "addr" not in opts:
            sys.exit("code needs --addr")
        out = header(3, len(data), opts["addr"], 0x8000) + data
    else:
        sys.exit(__doc__)
    open(a[1], "wb").write(out)
    print(f"{a[1]}: {len(out)} bytes")


if __name__ == "__main__":
    main()
