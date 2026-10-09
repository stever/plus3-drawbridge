#!/usr/bin/env python3
"""Create a blank +3DOS disk image.

  mkplus3img.py 720 out.img    PCW 9512 / +3DOS double-sided 80-track, 706K free
  mkplus3img.py 180 out.img    standard +3 single-sided 40-track, 173K free

The +3 reads the disk layout from the 16-byte specification at the start of
track 0 sector 1 (see the +3 manual, chapter 8, "+3DOS").  Everything else is
0xE5, which CP/M treats as an empty directory and unused data.
"""
import sys

SPECS = {
    # type, sidedness, tracks, sectors, log2(sec)-7, reserved, log2(blk)-7, dir blocks, gap rw, gap fmt
    "720": (3, 0x81, 80, 9, 2, 1, 4, 4, 0x2A, 0x52),   # sides alternate, 80 tracks, 2K blocks, 256 dir entries
    "180": (0, 0x00, 40, 9, 2, 1, 3, 2, 0x2A, 0x52),   # single sided, 40 tracks, 1K blocks, 64 dir entries
}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in SPECS:
        sys.exit(__doc__)
    size, out = sys.argv[1], sys.argv[2]
    spec = bytes(SPECS[size]) + bytes(6)
    typ, sided, tracks, secs = SPECS[size][:4]
    sides = 2 if sided & 3 else 1
    img = bytearray(b"\xE5" * (tracks * sides * secs * 512))
    img[0:16] = spec
    with open(out, "wb") as f:
        f.write(img)
    print(f"{out}: {len(img)} bytes, {tracks} tracks x {sides} side(s) x {secs} sectors")


if __name__ == "__main__":
    main()
