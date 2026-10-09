#!/bin/bash
# Capture a disk as raw flux, N passes (default 3).   usage: read-disk.sh name [passes] [port]
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
NAME=${1:?base name}; N=${2:-3}; PORT=${3:-/dev/ttyUSB0}
DB="$HERE/vendor/ArduinoFloppyDiskReader/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge"
for i in $(seq 1 "$N"); do
  "$DB" "$PORT" "$NAME-pass$i.scp" READ 2>&1 | tr '\r' '\n' | grep -E "success|rror"
done
echo "now identify the format:  gwenv/bin/gw convert --format=ibm.scan $NAME-pass1.scp $NAME-scan.edsk"
