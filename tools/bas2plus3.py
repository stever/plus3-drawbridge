#!/usr/bin/env python3
"""Tokenise a Spectrum BASIC listing into a +3DOS BASIC file the +3 can LOAD.

  bas2plus3.py [--line N] listing.bas OUTFILE

Each listing line is "<number> <statements>".  Keywords are written in UPPER
CASE as the Spectrum lists them (PRINT, GO TO or GOTO, DEF FN, OPEN #).
Variable names should be lower case so they are never mistaken for keywords.
--line N makes the program auto-run from line N.

Stored form: per line, line number (big-endian), line length (little-endian),
tokens and text, 0x0D.  Keywords are single bytes 0xA5-0xFF.  Every number
literal is its text followed by 0x0E and the Spectrum's 5-byte number form.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plus3hdr import header  # noqa: E402

TOKENS = [
    "RND", "INKEY$", "PI", "FN", "POINT", "SCREEN$", "ATTR", "AT", "TAB", "VAL$", "CODE",
    "VAL", "LEN", "SIN", "COS", "TAN", "ASN", "ACS", "ATN", "LN", "EXP", "INT", "SQR", "SGN",
    "ABS", "PEEK", "IN", "USR", "STR$", "CHR$", "NOT", "BIN", "OR", "AND", "<=", ">=", "<>",
    "LINE", "THEN", "TO", "STEP", "DEF FN", "CAT", "FORMAT", "MOVE", "ERASE", "OPEN #",
    "CLOSE #", "MERGE", "VERIFY", "BEEP", "CIRCLE", "INK", "PAPER", "FLASH", "BRIGHT",
    "INVERSE", "OVER", "OUT", "LPRINT", "LLIST", "STOP", "READ", "DATA", "RESTORE", "NEW",
    "BORDER", "CONTINUE", "DIM", "REM", "FOR", "GO TO", "GO SUB", "INPUT", "LOAD", "LIST",
    "LET", "PAUSE", "NEXT", "POKE", "PRINT", "PLOT", "RUN", "SAVE", "RANDOMIZE", "IF", "CLS",
    "DRAW", "CLEAR", "RETURN", "COPY",
]
TOK = {name: 0xA5 + i for i, name in enumerate(TOKENS)}
TOK.update({"GOTO": TOK["GO TO"], "GOSUB": TOK["GO SUB"], "DEFFN": TOK["DEF FN"],
            "OPEN#": TOK["OPEN #"], "CLOSE#": TOK["CLOSE #"]})
# longest first so "INKEY$" beats "IN", "<=" beats "<"
KEYWORDS = sorted(TOK, key=len, reverse=True)
NUM_RE = re.compile(r"(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def number5(text):
    """Spectrum 5-byte form of a numeric literal."""
    v = float(text)
    if v == int(v) and -65535 <= v <= 65535:
        n = int(v)
        sign = 0xFF if n < 0 else 0
        return bytes([0, sign]) + struct.pack("<H", n & 0xFFFF) + b"\x00"
    if v == 0:
        return bytes(5)
    e = 0
    m = abs(v)
    while m >= 1.0:
        m /= 2.0
        e += 1
    while m < 0.5:
        m *= 2.0
        e -= 1
    mant = int(round(m * (1 << 32)))
    if mant >= (1 << 32):            # rounding overflow
        mant >>= 1
        e += 1
    mant &= 0x7FFFFFFF
    if v < 0:
        mant |= 0x80000000
    return bytes([e + 128]) + struct.pack(">I", mant)


def tokenise(stmt):
    out = bytearray()
    i = 0
    n = len(stmt)
    while i < n:
        c = stmt[i]
        if c == '"':                                   # string literal, copied verbatim
            j = stmt.find('"', i + 1)
            j = n if j < 0 else j + 1
            out += stmt[i:j].encode("latin-1")
            i = j
            continue
        matched = None
        for kw in KEYWORDS:
            if stmt.startswith(kw, i):
                after = stmt[i + len(kw):i + len(kw) + 1]
                if kw[-1].isalpha() and after.isalnum():   # e.g. "INK" inside "INKEY"
                    continue
                before = stmt[i - 1:i]
                if kw[0].isalpha() and before.isalnum():   # keyword glued to a variable name
                    continue
                matched = kw
                break
        if matched:
            out.append(TOK[matched])
            i += len(matched)
            if i < n and stmt[i] == " ":
                i += 1                                   # the token implies its own spacing
            if matched == "REM":
                out += stmt[i:].encode("latin-1")        # rest of line is literal
                return bytes(out)
            continue
        m = NUM_RE.match(stmt, i)
        if m and not stmt[i - 1:i].isalpha():            # not part of a name like a1
            out += m.group(0).encode("latin-1") + b"\x0E" + number5(m.group(0))
            i = m.end()
            continue
        if c == " " and out and out[-1] >= 0xA5:
            i += 1                                       # drop space after a token
            continue
        out.append(ord(c))
        i += 1
    return bytes(out)


def main():
    a = sys.argv[1:]
    line = 0x8000
    if a and a[0] == "--line":
        line = int(a[1])
        a = a[2:]
    if len(a) != 2:
        sys.exit(__doc__)
    prog = bytearray()
    for raw in open(a[0], encoding="latin-1"):
        raw = raw.rstrip("\r\n")
        if not raw.strip():
            continue
        m = re.match(r"\s*(\d+)\s?(.*)", raw)
        if not m:
            sys.exit(f"line without a number: {raw!r}")
        body = tokenise(m.group(2)) + b"\x0D"
        prog += struct.pack(">H", int(m.group(1))) + struct.pack("<H", len(body)) + body
    out = header(0, len(prog), line, len(prog)) + bytes(prog)
    open(a[1], "wb").write(out)
    print(f"{a[1]}: {len(prog)} bytes of BASIC + 128-byte header"
          + (f", auto-run from line {line}" if line < 0x8000 else ""))


if __name__ == "__main__":
    main()
