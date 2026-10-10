# plus3-drawbridge

Read, write and format ZX Spectrum +3 and Amstrad CPC disks on Linux with a
[DrawBridge](https://amiga.robsmithdev.co.uk) fitted inside an IBM/Lenovo USB
floppy drive (TEAC FD-05PUB mechanism).

DrawBridge is Rob Smith's Amiga floppy reader/writer. It also reads any disk as
raw flux and writes PC-style MFM tracks, which is what +3DOS and AMSDOS use. The
stock host tool could not write a usable track on this board-and-drive
combination; three small patches fix that. Everything here was proven on
2026-10-10 by formatting a 720K +3DOS disk from the PC, adding a BASIC program,
and loading it on a real +3.

## Quick start

```
git clone <this repo> && cd plus3-drawbridge
./setup.sh                       # clones upstream DrawBridge at the pinned commit, patches, builds, makes a venv
sudo usermod -aG dialout $USER   # once; log out and in.  Stopgap: sudo setfacl -m u:$USER:rw /dev/ttyUSB0
export DB=vendor/ArduinoFloppyDiskReader/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge
$DB /dev/ttyUSB0 SETTINGS ALLDD 1          # treat every disk as double density
```

Everyday use goes through one command (high-density disks: tape over the density hole on both sides first):

```
tools/plus3disk.py format                              # blank 720K +3DOS disk; --size 180 for the standard format
tools/plus3disk.py ls                                  # catalogue
tools/plus3disk.py put examples/hello.bas --basic --line 10 --as HELLO   # tokenise, add header, copy on
tools/plus3disk.py put data.txt program.bin            # plain files, no header
tools/plus3disk.py put game.bin --code --addr 32768    # CODE block with a +3DOS header
tools/plus3disk.py get HELLO --to out/                 # copy off
tools/plus3disk.py read disk.img / write disk.img / verify disk.img
```

On the +3: `CAT "b:"` shows the files; `LOAD "b:hello"` loads and runs the example.

A write always rewrites the whole disk, so `put` reads the disk first (and refuses to continue unless every
track read cleanly), adds the files to that image, writes it with verify, then reads the disk back and compares
byte for byte. About 8 minutes. `--from-image` skips the first read when you kept the image with `--keep-image`.

The lower-level pieces, if you want them separately:

```
cd diskdefs
python3 ../tools/bas2plus3.py --line 10 ../examples/hello.bas HELLO
cp ../plus3-blank-720k.img disk.img
cpmcp -f plus3-720k -T raw disk.img HELLO 0:HELLO
../tools/write-disk.sh disk.img
```

Image an unknown disk and recover its files:

```
tools/read-disk.sh mydisk 3                                   # three flux passes
gwenv/bin/gw convert --format=ibm.scan mydisk-pass1.scp scan.edsk   # which sectors, which IDs
gwenv/bin/python tools/merge_cpc.py mydisk-pass*.scp out      # CPC disks: best sectors of all passes, one image per side
cd diskdefs && cpmls -f cpcsys -T raw ../out-side0.raw        # cpcsys / cpcdata / plus3-720k / plus3-180k
```

## What is in here

| Path | What |
| --- | --- |
| `setup.sh` | Recreates the toolchain: upstream clone at commit `2cbbfd1`, patches, build, Greaseweazle venv, blank images |
| `patches/` | Three patches to the DrawBridge host tool (below). Applied by `setup.sh` |
| `tools/plus3disk.py` | The everyday command: format, ls, put, get, read, write, verify |
| `tools/write-disk.sh` | Write an image with verify, then read back and compare |
| `tools/verify-disk.sh` | Read back and compare only |
| `tools/read-disk.sh` | Capture N flux passes of a disk |
| `tools/mkplus3img.py` | Blank +3DOS image, 720K double sided or 180K standard |
| `tools/bas2plus3.py` | Tokenise a BASIC listing into a +3DOS file that LOADs and auto-runs |
| `tools/plus3hdr.py` | Add or strip the 128-byte +3DOS header on BASIC or CODE files |
| `tools/merge_cpc.py` | Merge good sectors from several flux passes of a CPC disk |
| `diskdefs/` | cpmtools definitions for +3DOS 720K/180K and CPC System/Data; Greaseweazle definitions for CPC DSK output |
| `examples/` | `hello.bas` and its built `HELLO`, the program that ran on the +3 |
| `docs/WORKFLOW.md` | The full write-up: hardware, diagnosis, media rules, formats, header layout, Amiga comparison |

## The patches

Against upstream V2.8.9 (`RobSmithDev/ArduinoFloppyDiskReader` commit `2cbbfd1`). Host program only; the board firmware is untouched.

1. **Write each track immediately, not from the index pulse** (`lib/ADFWriter.cpp`, `sectorFileToDisk`). The index-wait path held the write gate open and sent no data on this hardware, so every track came out erased. The board's own diagnostic, which does not wait for index, wrote fine. 0 of 160 tracks good became 70.
2. **Erase before write, precompensation off** (`Main.cpp`). A non-index write covers 98.5 percent of a revolution; without an erase the unwritten slice keeps old fragments that decode as broken sectors. 70 became 139. Precompensation was off while isolating the fault and the inner cylinders are perfect without it.
3. **Diagnostic treats a disk-change failure as a warning.** This mechanism never delivers disk-change to the board; unpatched, the diagnostic aborts before its read and write tests.

The last step to 160 of 160 was not software: high-density media must have the density hole covered for double-density writes on this drive.

These are workarounds for this board-and-drive pairing. The index-wait path presumably works on the hardware upstream is tested with; why it fails here is not known.

## Caveats

- The Amiga ADF write path also waits for the index pulse by default and has **not** been tested from this unit. Read a known Amiga disk, write it back to a spare and verify before trusting Amiga writes. Reading needed no patches at all.
- At a verify prompt the tool offers R, S, A. S is unhandled and acts as retry; **I** skips. The scripts answer R five times then I.
- Setting a board option to 0 does not take through the command-line tool on this firmware; check `SETTINGS` before a session.
- Writing always rewrites the whole disk. To add files to a disk that has some, read it back first and add to that image.

## Licence

Scripts and documentation in this repository: GPL-3.0, to match the DrawBridge command-line tool they patch.
DrawBridge is copyright Robert Smith; its library is dual MPL-2.0 / GPL-2.0-or-later and its command-line tool GPL-3.0. `setup.sh` fetches it from upstream; it is not vendored here.
