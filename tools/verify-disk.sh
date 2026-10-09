#!/bin/bash
# Read the floppy back as flux, decode it as a 720K PC-style layout and compare
# with an image.   usage: verify-disk.sh image.img [port]
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
IMG=${1:?image file}; PORT=${2:-/dev/ttyUSB0}
DB="$HERE/vendor/ArduinoFloppyDiskReader/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge"
GW="$HERE/gwenv/bin/gw"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
"$DB" "$PORT" "$T/rb.scp" READ 2>&1 | tr '\r' '\n' | grep -E "rror" || true
FMT=ibm.720; [ "$(stat -c %s "$IMG")" -eq 184320 ] && FMT=ibm.180
"$GW" convert --format=$FMT "$T/rb.scp" "$T/rb.img" > "$T/rb.log" 2>&1
echo "tracks fully read: $(grep -c '9/9 sectors' "$T/rb.log")"
grep -E '^T[0-9]+\.[01]: IBM' "$T/rb.log" | grep -v '9/9 sectors' | sed -E 's/ from Raw.*//' || true
if cmp -s "$IMG" "$T/rb.img"; then echo "VERIFIED: disk matches $IMG exactly"; else echo "MISMATCH: disk differs from $IMG"; exit 1; fi
