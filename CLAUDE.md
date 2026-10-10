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
- `tools/plus3disk.py` is the everyday command (format, ls, put, get, read, write,
  verify). Both `format` and `put` were proven on hardware: 160/160 tracks, byte-exact
  read-back. Pushed to https://github.com/stever/plus3-drawbridge (public).
- Live write-up doc: https://claude.ai/code/artifact/e0744422-7411-44c3-b2e5-f6b2845354c1

## Disks (the user labels them)

- A: recycled Amstrad CPC disk, physically damaged band around cylinders 6-27, both
  sides. Its original contents are recovered in `~/Desktop/Claude/amstrad-disk1`.
  Formatting it retries endlessly; retired.
- B: 720K +3DOS, HELLO on it, works on the real +3 (CAT shows 706K free, LOAD "b:hello"
  runs). Written by the same patched writer as C.
- C: 720K +3DOS with HELLO, verified 160/160 here twice, but the +3 says
  "Drive B: track 0 sector 0 Missing address mark". OPEN PROBLEM, see below.
- All the user's disks are HD media. Density hole must be taped, both sides, opaque,
  for DD writes on this drive; hole open gave weak outer cylinders 0-26.

## Open problem: disk C unreadable on the +3

This drive reads C perfectly; the +3's drive finds no sector header on track 0.
Candidates, in order: C's tape not fully blocking the +3 drive's sensor (so it reads in
HD mode); C's media holding a DD recording too weakly for a drive other than the one
that wrote it; a weaker first write. Planned next steps, none done yet:
1. verify C here again against `work/diskC-hello.img`;
2. measure flux timing spread (how tightly intervals cluster at 4/6/8 us) on C vs B as
   read here, as a signal-quality comparison;
3. ask what the +3's 3.5" drive is (PC HD mechanism with hole sensor, or true DD);
4. retape or rewrite C, else retire it.

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

- `plus3disk rm` / `mv` (cpmrm, cpmcp round trip; trivial).
- TAP to +3DOS import (each TAP block carries the header fields needed): the most
  useful next feature, ~1 hour.
- Amiga ADF writes from this unit are untested; the ADF path also waits for the index
  pulse by default (`Main.cpp`, `ADFToDisk` sixth argument).
- Report the index-wait failure upstream to Rob Smith with `patches/0001`.
