# plus3-drawbridge: session notes

Read this first. README.md is the user-facing guide; docs/WORKFLOW.md is the full
write-up of how the setup was diagnosed and proven. This file is what a new session
needs that those do not say.

## State as of 2026-10-10

- Hardware: IBM/Lenovo USB floppy (FRU 36L8645, TEAC FD-05PUB mechanism) rebuilt with
  Rob Smith's DrawBridge board for that drive. Appears as `/dev/ttyUSB0` (FTDI). The
  board's disk-change signal does not work; everything else passed the diagnostic.
- Toolchain is built in this checkout: `vendor/ArduinoFloppyDiskReader` (upstream at
  commit 2cbbfd1 with the four patches in `patches/`), `gwenv/` (Greaseweazle decoder).
  `./setup.sh` rebuilds it all and is idempotent.
- `tools/plus3disk.py` is the everyday command (format, ls, put, get, cat, rm, mv, read,
  write, verify). `format` and `put` were proven on hardware: 160/160 tracks, byte-exact
  read-back. Pushed to https://github.com/stever/plus3-drawbridge (public).
- Added 2026-10-10 afternoon, tested only against image files (`--image`), not yet on
  the drive: `rm`, `mv`, `cat`, `get --strip`, `put --tap` (via `tools/tap2plus3.py`),
  `--image IMG` offline mode, and `ls` rewritten to parse the CP/M directory itself
  (shows +3DOS header type and free space; the old `cpmls -F` printed "No files found").
  The drive paths these use (read_disk, write_disk, verify_disk) are unchanged.
- Live write-up doc: https://claude.ai/code/artifact/e0744422-7411-44c3-b2e5-f6b2845354c1

## Disks (the user labels them)

- A: recycled Amstrad CPC disk, physically damaged band around cylinders 6-27, both
  sides. Its original contents are recovered in `~/Desktop/Claude/amstrad-disk1`.
  Formatting it retries endlessly; retired.
- B: 720K +3DOS, HELLO on it, works on the real +3 (CAT shows 706K free, LOAD "b:hello"
  runs). Written by the same patched writer as C.
- C: 720K +3DOS holding Dan Dare, Rebel Planet and zxdesk (the user's own program)
  imported from TAP: 12 files, image `work/diskC-taps2.img`, written and verified
  160/160 on 2026-10-10. On the +3: `LOAD "b:"` (does not survive a reset) then
  `LOAD "dandare"` / `LOAD "rebel"` / `LOAD "zxdesk"`. zxdesk's COUNTER, WATCH and
  TALLY blocks are on the disk but zxdesk loads them itself, presumably from tape.
  Idea: `--drive b` to bake `b:` into patched loaders so one LOAD does it. An earlier
  "Missing address mark" on C came from a crashed session, not the media.
- A read that fails at track 0 with "error running the ReadTrackStream command" means
  no disk in the drive. plus3disk now stops on that instead of continuing.
- All the user's disks are HD media. Density hole must be taped, both sides, opaque,
  for DD writes on this drive; hole open gave weak outer cylinders 0-26.

## Conventions and hazards

- Never capture the DrawBridge tool's output unbounded or feed it a finite answer
  string: on failure it can print prompts at full speed. `plus3disk` streams and
  rate-limits; patch 4 makes the tool exit on closed stdin. This once exhausted RAM.
- `/tmp` is a 31 GB RAM tmpfs on this machine. Temp files go under `work/`
  (gitignored). Flux captures are 42 MB each.
- Serial access lapses every time the board is replugged until the user's dialout
  group membership takes effect: `sudo setfacl -m u:steve:rw /dev/ttyUSB0`. The user
  runs sudo commands themselves (give them the command with a `!` prefix).
- Board settings: ALLDD must be 1. Setting an option to 0 does not take via the CLI.
- Verify prompt keys: R retry, I skip; S is shown but acts as retry.
- A whole-disk write takes ~5 min, a flux read ~90 s; put = read + write + read ≈ 8 min.
  Run long operations in the background with output to a file under `work/`.
- Commits: author "Steven Robertson <steven@wolflogic.co.uk>", GPL-3.0 repo.
  Push only after the change is proven on hardware.
- The user is at the drive; ask for disk swaps and taping, and relay +3 error text
  verbatim. Label disks A/B/C consistently.

## Ideas not started

- `put --tap` patches `LOAD ""` in the loader to the next block's disk name (tape order)
  and keeps names unique across the disk (`--avoid`). First real test: Dan Dare and
  Rebel Planet from `~/Downloads/ZX Spectrum +3/z80to/` onto disk C, image kept at
  `work/diskC-taps.img`. Check the outcome on the +3: `LOAD "b:"` then `LOAD "dandare"`.
  TAPs with headerless blocks or custom loaders are out of scope.
- Prove rm/mv/cat on the drive.
- A BASIC detokeniser (`get` as a .bas listing); the tokeniser table in `bas2plus3.py`
  is the reverse map.
- Amiga ADF writes from this unit are untested; the ADF path also waits for the index
  pulse by default (`Main.cpp`, `ADFToDisk` sixth argument).
- Report the index-wait failure upstream to Rob Smith with `patches/0001`.
