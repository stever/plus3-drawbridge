# DrawBridge +3 Disk Workflow

Live copy: https://claude.ai/code/artifact/e0744422-7411-44c3-b2e5-f6b2845354c1

## Summary

A TEAC-based IBM/Lenovo USB floppy drive, rebuilt around Rob Smith's DrawBridge board, now reads and writes ZX Spectrum +3 and Amstrad CPC disks from a Fedora PC. On 10 October 2026 a 720K +3DOS disk formatted and written here loaded and auto-ran a BASIC program on the +3.

The chain is: DrawBridge captures or writes raw flux and MFM over USB serial; the Greaseweazle host tools decode flux images offline into sector images; cpmtools reads and writes the CP/M filesystem that +3DOS and AMSDOS use; a 128-byte +3DOS header in front of each program file makes the +3 treat it as BASIC or CODE.

Four things were not obvious and cost most of the time:

- The stock DrawBridge image writer waits for the index pulse before each track. On this hardware that path holds the write gate open and sends no data, so every track came out erased. Starting the write immediately fixed it.
- Tracks must be erased before writing, because a non-index-aligned write is 1.5 percent shorter than a revolution and the unwritten slice otherwise keeps old sector fragments.
- High-density disks must have the density hole covered on both sides. With it open, cylinders 0 to 26 came back weak and unreliable. With it covered, 160 of 160 tracks read back exactly on two passes.
- The USB drive's original bridge board could never have read these disks. It only understands PC layouts and reports 1.44M for anything else, whatever the hole says.

Everything needed to repeat this is in `~/Desktop/Claude/plus3-tools` and is described below.

## The hardware

The drive is an IBM/Lenovo external USB floppy, FRU 36L8645, dated May 2005. Inside is a TEAC slimline mechanism that was sold as the TEAC FD-05PUB, identified over USB as TEAC USB UF000x. The DrawBridge board is Rob Smith's purpose-built version for this drive family: it plugs into the mechanism's 26-pin flat flex cable in place of the original USB bridge board, and the drive's own captive USB lead is soldered to its four pads. It carries an ATmega microcontroller and an FTDI FT232R serial chip, and shows up in Linux as an FTDI serial port, not as a floppy.

**Opening the case.** There are no visible screws and none under the rubber feet. The single screw is under the QC sticker on the underside, felt as a dimple. With it out, the top cover slides a few millimetres towards the disk slot and lifts off at the rear.

**What the diagnostic confirmed.** The board's built-in diagnostic passed the serial link, CTS, firmware 1.9.25, transfer speed, write-protect sensing, motor speed at 299.9 rpm, index pulse, track 0 and track 70 seeking, and the write test on track 41 both sides, with and without precompensation.

**What does not work.** The mechanism's disk-change signal never reaches the board. The diagnostic fails that test and, unpatched, aborts there. This is harmless for imaging and writing from the command line. It would matter for using the drive live from an Amiga emulator, which relies on disk-change to notice swaps.

**Power.** Everything runs from the one USB lead. Moving between a front-panel port and a back-panel USB 3 port made no difference once the real fault was fixed, so a plain USB 2 port is enough.

**The original USB bridge board** is kept aside. It is of no further use for non-PC disks: it decides density itself, ignores the host, and reports an unreadable disk as 1.44M.

## Setting up from scratch on a new Linux install

About 20 minutes on Fedora. Package names are Fedora's; Debian and Ubuntu equivalents are in brackets.

1. **Packages.** `sudo dnf install git make gcc-c++ cpmtools python3 python3-pip` (Debian: `build-essential cpmtools python3-venv`). Optional for drive diagnostics: `ddrescue sg3_utils`.
2. **Serial port access.** The DrawBridge appears as `/dev/ttyUSB0`, owned by group `dialout`. Add yourself once with `sudo usermod -aG dialout $USER` and log out and in. Until then, or as a stopgap after every replug, `sudo setfacl -m u:$USER:rw /dev/ttyUSB0`. The device node is recreated each time the board is unplugged, which silently drops the setfacl grant.
3. **DrawBridge host tool, patched.** Either copy `plus3-tools/drawbridge-src` and run `make` in `ArduinoFloppyReader/ArduinoFloppyReader`, or clone the upstream `RobSmithDev/ArduinoFloppyDiskReader` repository and apply `plus3-tools/drawbridge-patches.diff` with `git apply` before building. The binary is called `drawbridge`. The pre-built `plus3-tools/drawbridge-patched` works on an x86-64 Fedora with the same glibc.
4. **Greaseweazle host tools**, used purely as an offline flux decoder, no Greaseweazle hardware involved. Not on PyPI under that name, so: `python3 -m venv gwenv && gwenv/bin/pip install git+https://github.com/keirf/greaseweazle.git`. The command is `gwenv/bin/gw`.
5. **Board settings.** `drawbridge /dev/ttyUSB0 SETTINGS ALLDD 1` stops the board guessing density per disk. Check with `drawbridge /dev/ttyUSB0 SETTINGS`. Note that setting a value to 0 appears not to take on this firmware; only 1 does.
6. **cpmtools definitions.** Copy `plus3-tools/diskdefs` (the +3 formats) and `cpmtools-diskdefs-cpc` (CPC System and Data) somewhere handy and pass them with `-f` after setting `CPMTOOLSFMT`, or simply run cpmtools from the folder containing a file named `diskdefs`, which it reads from the current directory.
7. **Sanity check.** With a disk in the drive, `drawbridge /dev/ttyUSB0 test.scp READ` should take about 90 seconds and produce a 42 MB file. `drawbridge /dev/ttyUSB0 DIAGNOSTIC` runs the full interactive check; expect the disk-change test to fail and continue.

The only files that matter are in `plus3-tools`:

| File | Purpose |
| --- | --- |
| `drawbridge-patches.diff` | The four source changes, applied to upstream V2.8.9 |
| `drawbridge-src/` | The patched source tree, ready to `make` |
| `drawbridge-patched` | Pre-built binary for this machine |
| `plus3-blank-720k.img` | Blank 720K +3DOS image with the disk specification in its boot sector |
| `diskdefs` | cpmtools definitions `plus3-720k` and `plus3-180k` |
| `cpmtools-diskdefs-cpc` | cpmtools definitions `cpcsys` and `cpcdata` |
| `cpc-gw-diskdefs.cfg` | Greaseweazle definitions `cpc.system` and `cpc.data` for building DSK images |
| `merge_cpc.py` | Merges good sectors from several flux passes of a CPC disk into per-side images |
| `files/HELLO` | The test program, with its +3DOS header |

## The four patches to the DrawBridge tool

All are in `drawbridge-patches.diff`, 50 lines against upstream V2.8.9. They touch only the host program, never the board firmware.

| Patch | Where | Why |
| --- | --- | --- |
| Write each track immediately, not from the index pulse | `lib/ADFWriter.cpp`, `sectorFileToDisk`, the `writeCurrentTrackPrecomp` call | The index-wait path erased every track and wrote no data on this board and drive. The diagnostic's own write test, which does not wait for index, passed. Result went from 0 of 160 tracks to 70 |
| Erase each track before writing it | `Main.cpp`, fifth argument of `sectorFileToDisk` set to `true` | A non-index write covers about 98.5 percent of a revolution. Without an erase, the remaining slice keeps fragments of earlier writes, which read back as spurious broken sectors. Result went from 70 to 139 of 160 |
| Write precompensation off | `Main.cpp`, fourth argument of `sectorFileToDisk` set to `false` | Precompensation applied from cylinder 40 inward. Disabled while isolating the fault; inner cylinders are perfect without it, so it stayed off |
| Disk-change failure in the diagnostic is a warning | `lib/ADFWriter.cpp`, `runDiagnostics`, two `return false` lines removed | This mechanism never delivers disk-change to the board. Unpatched, the diagnostic aborts before the read and write tests, which are the useful ones |

Two things in the stock tool that are not bugs but will bite:

- At a write-verify prompt the choices are shown as R, S and A, but S is not handled and acts as retry. The key that actually skips a track is I. A script answering S loops forever and, if its output goes to a file, fills the disk.
- Progress lines are written with carriage returns and no newline, and are buffered when not on a terminal. Pipe through `tr '\r' '\n'` and use `stdbuf -o0` when logging.

## Media rules

**Cover the density hole on high-density disks**, both sides, with opaque tape pressed flat. The +3 and the CPC write double density. On this TEAC mechanism an HD disk with the hole open gave weak writes across cylinders 0 to 26, with different sectors failing on each read. The same disk with the hole covered wrote without a single retry and read back exactly twice. Leave the tape on when the disk goes to the +3, whose drive makes the same decision from the same hole.

**Genuine double-density disks**, marked DD or 2DD with no second hole, need nothing and are the better choice for anything you want to keep. They are still sold by retro suppliers.

**Verify by reading back, not by trusting the writer.** The writer's own verify passed tracks that were marginal on the next read. The reliable check is a full flux read, a decode, and a byte comparison against the image:

```
drawbridge /dev/ttyUSB0 check.scp READ
gw convert --format=ibm.720 check.scp check.img
cmp disk.img check.img && echo identical
```

The decode log lists every track as `9/9 sectors` when all is well. Do it twice on a disk that matters; agreement between two reads is the real test.

**Damaged disks show two patterns.** A band of failures at one sector number across a run of tracks is a physical mark at one angular position, as on the Amstrad disk. Whole tracks that decode as noise in every pass are degraded media. Neither is recoverable by rereading, and the Amstrad disk had both.

## Workflow: imaging a disk and recovering its files

The DrawBridge reads flux, so it does not care what format a disk is. Identification happens afterwards, on the PC.

1. **Capture flux**, three passes for anything old: `drawbridge /dev/ttyUSB0 pass1.scp READ`, then `pass2.scp`, `pass3.scp`. Each pass is 80 cylinders, both sides, three revolutions per track, about 42 MB and 90 seconds. Keep the SCP files; they are the archival copy.
2. **Identify the format**: `gw convert --format=ibm.scan pass1.scp scan.edsk`. The log shows sectors found per track. The `.edsk` output preserves sector numbering, which a short Python read of the track headers reveals. Sector IDs tell you what you have.
3. **Decode and merge.** For a known PC-style layout, `gw convert --format=ibm.720 pass1.scp disk.img`. For a CPC disk, `merge_cpc.py pass1.scp pass2.scp pass3.scp out` takes every sector that decoded with a good CRC from any pass and writes one raw image per side, listing what is still missing.
4. **Extract files** with cpmtools: `cpmls -f cpcsys -T raw side0.raw` to list, `cpmcp -f cpcsys -T raw side0.raw '0:*' outdir/` to copy. The `-T raw` flag matters; without it cpmtools expects a different container.
5. **Build emulator images** if wanted: `gw convert --diskdefs cpc-gw-diskdefs.cfg --format=cpc.system side0.img side0.edsk`, then rename to `.dsk`. Note the input must not end in `.raw`, which gw treats as a KryoFlux stream.

**Sector numbering by format**, which is what the USB bridge could not cope with:

| Format | Tracks | Sides | Sector IDs | Reserved tracks | Who reads it |
| --- | --- | --- | --- | --- | --- |
| +3DOS standard, PCW 8256 | 40 | 1 | 1 to 9 | 1 | +3, PCW, CPC with CP/M |
| PCW 9512 / +3DOS 720K | 80 | 2 | 1 to 9 | 1 | +3, PCW |
| CPC System | 40 | 1 | 0x41 to 0x49 | 2 | CPC, +3 |
| CPC Data | 40 | 1 | 0xC1 to 0xC9 | 0 | CPC, +3 |
| PC 720K | 80 | 2 | 1 to 9 | n/a | PCs, USB floppy drives |

**The Amstrad disk** turned out to be two disks in one: side 0 in CPC System format holding an Amstrad CP/M 2.2 system disk, side 1 in CPC Data format holding a modern homebrew program with ZX0-packed files. The +3 only reads side 0. All 54 files were extracted to `amstrad-disk1`, with 8 sectors on side 0 and 32 on side 1 unrecoverable after three passes, mapped to file names in its README.

## Workflow: formatting a 720K +3DOS disk

Formatting is just writing a blank image. The +3 reads the disk's layout from a 16-byte specification at the start of the boot sector, and it understands the PCW 9512 double-sided format natively, so a disk built this way gives 706K free and 256 directory entries instead of the standard 173K and 64. The +3 ROM reads it; it cannot create it, which is why it is done here.

1. Tape the density hole on both sides if the disk is HD. Write-protect window closed.
2. `drawbridge /dev/ttyUSB0 plus3-blank-720k.img WRITE VERIFY`. About five minutes. At any verify prompt, R retries and I skips. A clean disk produces no prompts.
3. Read back and compare as in Media rules. Expect `160 / 160` and `identical`.
4. On the +3, `CAT "b:"` shows an empty catalogue and `706K free`.

**The disk specification** in the first 16 bytes of track 0 sector 1, everything else in the image being 0xE5:

| Byte | Value | Meaning |
| --- | --- | --- |
| 0 | 3 | Disk type: PCW range, double sided, double track |
| 1 | 0x81 | Bit 7: 80 tracks. Bits 0 to 1 = 1: sides alternate, cylinder 0 side 0, cylinder 0 side 1, cylinder 1 side 0, and so on |
| 2 | 80 | Tracks per side |
| 3 | 9 | Sectors per track |
| 4 | 2 | log2(sector size) minus 7, so 512 bytes |
| 5 | 1 | Reserved tracks |
| 6 | 4 | log2(block size) minus 7, so 2K blocks |
| 7 | 4 | Directory blocks, so 256 entries |
| 8 | 0x2A | Read/write gap |
| 9 | 0x52 | Format gap |
| 10 to 15 | 0 | Reserved; byte 15 is a checksum that only matters for a bootable disk |

To regenerate the image, the whole recipe is: 737,280 bytes of 0xE5, with those 16 bytes at offset 0. For a standard 173K single-sided disk the spec would be type 0, sidedness 0, 40 tracks, 1K blocks, 2 directory blocks, and the image 184,320 bytes; the `plus3-180k` cpmtools definition matches it.

## Workflow: putting files on a +3 disk

Files go into the image with cpmtools, then the whole image is written to disk. There is no way to write one file to a physical disk with this setup; a write always rewrites every track, which takes five minutes and is verified as a whole.

```
cp plus3-blank-720k.img disk.img            # or an image read back from the disk
cpmcp -f plus3-720k -T raw disk.img HELLO 0:HELLO
cpmls -f plus3-720k -T raw disk.img
drawbridge /dev/ttyUSB0 disk.img WRITE VERIFY
```

To add to a disk that already has files, read it back first and add to that image rather than the blank one, or the existing files are lost.

**The +3DOS header.** CP/M stores files as plain bytes. For the +3 to `LOAD` something as BASIC or CODE, the file needs a 128-byte header in front, which +3DOS strips on load. Data files opened from BASIC with `OPEN #` and CP/M programs need no header.

| Offset | Size | Content |
| --- | --- | --- |
| 0 | 8 | `PLUS3DOS` |
| 8 | 1 | 0x1A |
| 9 | 1 | Issue number, 1 |
| 10 | 1 | Version number, 0 |
| 11 | 4 | Total file length including this header, little-endian |
| 15 | 1 | Type: 0 BASIC program, 1 numeric array, 2 character array, 3 CODE |
| 16 | 2 | Data length, excluding the header |
| 18 | 2 | BASIC: auto-run line, or 0x8000 or above for none. CODE: load address |
| 20 | 2 | BASIC: offset of the variables area, equal to the program length when there are none |
| 22 | 1 | Unused |
| 23 | 104 | Zeros |
| 127 | 1 | Checksum: sum of bytes 0 to 126, modulo 256 |

**BASIC programs** are stored tokenised, exactly as in memory: per line, a big-endian line number, a little-endian line length, the line's bytes, then 0x0D. Keywords are single bytes from 0xA5 to 0xFF, for example PRINT 0xF5, FOR 0xEB, NEXT 0xF3, BORDER 0xE7. Every number literal is its text followed by 0x0E and a 5-byte binary form; for an integer n that form is 0, 0, n low, n high, 0.

**The HELLO test**, in `files/HELLO`, is six lines and 180 bytes of BASIC plus the header, type 0, auto-run from line 10. On the +3, `LOAD "b:hello"` loads and runs it. It was built by a 40-line Python script that tokenises a handful of keywords; a general converter from a listing or a TAP file is the natural next tool.

**CODE files** are simpler: header type 3, length and load address filled in, then the raw bytes. `LOAD "b:name" CODE` puts them at that address.

## How this compares with Amiga disks

For Amiga disks the DrawBridge does the whole job itself, and the workflow is two commands with none of the decoding and filesystem steps above. The +3 and CPC work used the board as a general flux reader and MFM writer, which it supports but was not built around.

| | Amiga, the design case | +3 and CPC, as done here |
| --- | --- | --- |
| Read a disk | `drawbridge PORT disk.adf READ` decodes AmigaDOS on the fly, with per-sector checksums and automatic retries, straight to an ADF | `READ` to an SCP flux file, then `gw convert` on the PC to decode, then `merge_cpc.py` across passes for damaged disks |
| Write a disk | `drawbridge PORT disk.adf WRITE VERIFY` | Build a sector image, then `WRITE VERIFY` through the patched IBM path |
| Get at the files | Mount the ADF in any Amiga emulator, or `unadf` | cpmtools, with the right `diskdefs` entry per format |
| Format detection | Not needed; one layout, 880K or 1760K HD | Sector IDs decide between +3DOS, PCW, CPC System and CPC Data, and a disk can mix two |
| Index alignment | Amiga tracks are written as one long stream with a gap; alignment is irrelevant by design | PC-style tracks are a chain of individually addressed sectors, so the writer's track geometry and the unwritten slice matter |
| Live use from an emulator | WinUAE and DiskFlashback on Windows, FS-UAE and Amiberry on Linux, through FloppyBridge | Not applicable; +3 emulators take DSK images, which this produces |

**One caveat before writing Amiga disks with this unit.** The command-line ADF writer also waits for the index pulse by default, the same path that failed here for PC-style tracks. The function takes it as a parameter, so a one-word change in `Main.cpp` turns it off, and the diagnostic's write test shows the board writes fine without it. That change has not been tested on an Amiga disk from this machine. Read a known Amiga disk to ADF first, write it back to a spare, and verify, before trusting any Amiga write.

**The disk-change signal** matters more for Amiga use than it did here. FloppyBridge relies on it to notice a swapped disk when an emulator is running. For command-line imaging it is irrelevant.

**Reading needed no patches at all.** The flux capture that recovered the Amstrad disk, and that verified every +3 write, is the stock DrawBridge SCP read. Everything the board had to do for reading, it did out of the box.

## Gotchas and lessons learned

- **Unplugging the board drops serial access** until the dialout group is active for your login. Symptom: the tool reports the port was not found even though `/dev/ttyUSB0` exists.
- **Label the disks.** Half an hour was lost to a disk swap that one side of the conversation did not know about. Disk A is the damaged Amstrad disk, now overwritten; disk B is the verified 720K +3 disk.
- **Do not trust a single read-back of a marginal disk.** Two reads of the same disk disagreed on which sectors were bad. Two clean, identical reads are the standard.
- **The USB floppy's own controller cannot be made to read non-PC disks.** Taping the hole, three times, changed nothing because that controller falls back to 1.44M whenever it finds no sector it recognises. Do not spend time there again.
- **The DrawBridge diagnostic's alignment warning is a false alarm on 40-track disks.** It tests at track 40, which a CPC or standard +3 disk does not have. Its write test is the part worth having.
- **Setting a board option to 0 does not take** on this firmware through the command-line tool; only setting to 1 does. ALLDD was found reset once, so check `SETTINGS` before a session.
- **Flux files are large.** 42 MB per pass. Keep the originals in `amstrad-disk1/images/flux`; delete working copies from `/tmp`, which is a RAM filesystem here and filled up once during this work.
- **Next useful tools**, not yet built: a listing-to-tokenised-BASIC converter that handles every keyword and floating-point numbers, and a TAP-to-+3DOS converter, which is the quickest route for getting existing Spectrum software onto disk.
