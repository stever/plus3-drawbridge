#!/usr/bin/env python3
"""Split a TAP tape image into +3DOS files the +3 can LOAD from disk.

  tap2plus3.py [--avoid NAME,NAME...] game.tap OUTDIR

Every header block on the tape (flag 0, 17 bytes: type, name, length, two
parameters) followed by its data block becomes one file in OUTDIR, named from
the tape name made into a +3DOS name (upper case, letters and digits, 8 chars,
no extension).  The 128-byte +3DOS header is built from the tape header:

  tape type 0 Program      -> BASIC, autorun line and variables offset copied
  tape type 1 Number array -> numeric array, variable name byte copied
  tape type 2 Char array   -> character array, variable name byte copied
  tape type 3 Bytes        -> CODE, load address copied

The BASIC loader is patched so it works from disk: every LOAD "" (or LOAD
"name") in it is given the disk name of the next block on the tape, in order,
because LOAD "" means nothing on a disk drive.  Line lengths and the header are
fixed up.  --avoid lists names already on the disk so nothing is overwritten
when several tapes share one disk.

A data block with no header before it (a headerless loader) has nothing to
LOAD it on the +3 and is skipped with a warning.  Prints one line per file:
NAME, tape name, type and parameters.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plus3hdr import header  # noqa: E402

TYPES = {0: "BASIC", 1: "DATA", 2: "DATA", 3: "CODE"}


def blocks(data):
    i = 0
    while i + 2 <= len(data):
        n = int.from_bytes(data[i:i + 2], "little")
        i += 2
        if n < 2 or i + n > len(data):
            sys.exit(f"tap2plus3: truncated TAP at byte {i - 2}")
        yield data[i:i + n]
        i += n


def disk_name(tape_name, used):
    """8.3 name from a tape name: letters and digits only, a dot keeps an extension, unique within used."""
    stem, _, ext = tape_name.upper().partition(".")
    stem = re.sub(r"[^A-Z0-9]", "", stem)[:8] or "BLOCK"
    ext = re.sub(r"[^A-Z0-9]", "", ext)[:3]
    name, n = stem + ("." + ext if ext else ""), 1
    while name in used:
        n += 1
        name = stem[:8 - len(str(n))] + str(n) + ("." + ext if ext else "")
    used.add(name)
    return name


LOAD, NUMBER, QUOTE, EOL = 0xEF, 0x0E, 0x22, 0x0D


def patch_loader(prog, names):
    """Give each LOAD "..." in a tokenised BASIC program the next name in names.

    Returns (new program, notes).  Stored form per line: number (big endian),
    length (little endian), tokens and text, 0x0D.  A 0x0E inside a line starts
    a 5-byte binary number and is skipped, so a quote in there is not a string."""
    out, notes, queue, i = bytearray(), [], list(names), 0
    while i + 4 <= len(prog):
        lineno = int.from_bytes(prog[i:i + 2], "big")
        length = int.from_bytes(prog[i + 2:i + 4], "little")
        body, i = bytearray(prog[i + 4:i + 4 + length]), i + 4 + length
        j = 0
        while j < len(body):
            c = body[j]
            if c == NUMBER:
                j += 6
                continue
            if c == QUOTE:                                   # skip any string literal
                k = body.find(QUOTE, j + 1)
                j = len(body) if k < 0 else k + 1
                continue
            if c == LOAD and j + 1 < len(body) and body[j + 1] == QUOTE:
                k = body.find(QUOTE, j + 2)
                if k < 0:
                    break
                old = bytes(body[j + 2:k]).decode("latin-1")
                if queue:
                    new = queue.pop(0)
                    body[j + 2:k] = new.encode()
                    notes.append(f'line {lineno}: LOAD "{old}" -> LOAD "{new}"')
                    j = j + 2 + len(new) + 1
                else:
                    notes.append(f'line {lineno}: LOAD "{old}" left alone, no block left for it')
                    j = k + 1
                continue
            j += 1
        out += lineno.to_bytes(2, "big") + len(body).to_bytes(2, "little") + body
    if queue:
        notes.append(f"{len(queue)} block(s) are never LOADed by the loader: {' '.join(queue)}")
    return bytes(out), notes


def describe(ftype, length, p1, p2):
    if ftype == 0:
        return f"BASIC {length} bytes" + (f", LINE {p1}" if p1 < 0x8000 else "")
    if ftype == 3:
        return f"CODE {p1},{length}"
    var = chr(((p1 >> 8) & 0x1F) + 0x60) + ("$" if ftype == 2 else "") + "()"   # name is the high byte
    return f"DATA {var} {length} bytes"


def convert(tap_path, outdir, avoid=()):
    """Write one +3DOS file per tape header+data pair; return [(name, tape name, description)]."""
    os.makedirs(outdir, exist_ok=True)
    out, used, pending, parts = [], set(avoid), None, []
    for k, blk in enumerate(blocks(open(tap_path, "rb").read())):
        flag, body = blk[0], blk[1:-1]
        if flag == 0 and len(body) == 17:
            pending = body
            continue
        if pending is None:
            print(f"  skipped block {k}: headerless data, {len(body)} bytes", file=sys.stderr)
            continue
        h, pending = pending, None
        ftype = h[0]
        tape_name = h[1:11].decode("latin-1").rstrip()
        length, p1, p2 = (int.from_bytes(h[i:i + 2], "little") for i in (11, 13, 15))
        if ftype not in TYPES:
            print(f"  skipped {tape_name!r}: unknown tape type {ftype}", file=sys.stderr)
            continue
        if len(body) != length:
            print(f"  warning: {tape_name!r} header says {length} bytes, block has {len(body)}", file=sys.stderr)
        parts.append((ftype, disk_name(tape_name, used), tape_name, bytes(body), p1, p2))
    if pending is not None:
        print("  warning: tape ends with a header and no data block", file=sys.stderr)
    for k, (ftype, name, tape_name, body, p1, p2) in enumerate(parts):
        if ftype == 0:
            if k == 0 and len(parts) > 1:                # the loader: point its LOADs at the other blocks
                old_len = len(body)
                body, notes = patch_loader(body, [q[1] for q in parts[1:]])
                for n in notes:
                    print("  " + n, file=sys.stderr)
                if p2 >= old_len:
                    p2 += len(body) - old_len            # variables area moved with the program
            hdr = header(0, len(body), p1, p2)           # autorun line, variables offset
        elif ftype == 3:
            hdr = header(3, len(body), p1, 0x8000)       # load address
        else:
            hdr = header(ftype, len(body), (p1 & 0xFF00), 0)   # byte 19 = variable name
        open(os.path.join(outdir, name), "wb").write(hdr + body)
        out.append((name, tape_name, describe(ftype, len(body), p1, p2)))
    return out


def main():
    a = sys.argv[1:]
    avoid = []
    if a[:1] == ["--avoid"]:
        avoid = [n for n in a[1].upper().split(",") if n]
        a = a[2:]
    if len(a) != 2:
        sys.exit(__doc__)
    files = convert(a[0], a[1], avoid)
    for name, tape_name, desc in files:
        print(f"{name:<8}  {tape_name!r:<13} {desc}")
    if not files:
        sys.exit("tap2plus3: nothing usable on the tape")


if __name__ == "__main__":
    main()
