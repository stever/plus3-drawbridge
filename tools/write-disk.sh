#!/bin/bash
# Write a sector image to the floppy with the patched DrawBridge tool, then
# read it back and compare every byte.   usage: write-disk.sh image.img [port]
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
IMG=${1:?image file}; PORT=${2:-/dev/ttyUSB0}
DB="$HERE/vendor/ArduinoFloppyDiskReader/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge"
# At a verify prompt: R = retry (5 times), then I = skip that track.  (S is shown but acts as retry.)
( printf 'RRRRR'; yes I ) | stdbuf -o0 "$DB" "$PORT" "$IMG" WRITE VERIFY 2>&1 | tr '\r' '\n' \
  | grep -E "verify error|written|rror|protect" | sort | uniq -c
exec "$HERE/tools/verify-disk.sh" "$IMG" "$PORT"
