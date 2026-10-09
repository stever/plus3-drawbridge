#!/bin/bash
# Recreate the whole toolchain from a bare clone of this repository:
#   - clone DrawBridge host software at the pinned upstream commit into vendor/
#   - apply the patches in patches/ and build the command-line tool
#   - create a Python venv with the Greaseweazle host tools (offline flux decoder)
# Re-runnable.  Needs: git, make, g++, python3 with venv, cpmtools (for the file steps).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
UPSTREAM=https://github.com/RobSmithDev/ArduinoFloppyDiskReader.git
PIN=2cbbfd1c8d9e5c3e641316a5d643b9148e592206       # V2.8.9, 2024-11-24; the commit the patches apply to
SRC="$HERE/vendor/ArduinoFloppyDiskReader"

for t in git make g++ python3; do command -v $t >/dev/null || { echo "missing: $t  (Fedora: sudo dnf install git make gcc-c++ python3 cpmtools; Debian: sudo apt install git build-essential python3-venv cpmtools)"; exit 1; }; done

if [ ! -d "$SRC/.git" ]; then
  git clone "$UPSTREAM" "$SRC"
fi
git -C "$SRC" fetch -q origin
git -C "$SRC" checkout -q --detach "$PIN"
git -C "$SRC" checkout -q -- .                      # drop any previous patching
for p in "$HERE"/patches/*.patch; do
  git -C "$SRC" apply "$p" && echo "applied $(basename "$p")"
done
make -s -C "$SRC/ArduinoFloppyReader/ArduinoFloppyReader" -j"$(nproc)" >/dev/null
echo "built $SRC/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge"

if [ ! -x "$HERE/gwenv/bin/gw" ]; then
  python3 -m venv "$HERE/gwenv"
  "$HERE/gwenv/bin/pip" -q install "git+https://github.com/keirf/greaseweazle.git"
fi
echo "greaseweazle decoder: $HERE/gwenv/bin/gw"

python3 "$HERE/tools/mkplus3img.py" 720 "$HERE/plus3-blank-720k.img" >/dev/null
python3 "$HERE/tools/mkplus3img.py" 180 "$HERE/plus3-blank-180k.img" >/dev/null
echo "blank images: plus3-blank-720k.img plus3-blank-180k.img"

cat <<EOF

Next:
  serial access     sudo usermod -aG dialout \$USER   (log out/in)  or, per plug-in:  sudo setfacl -m u:\$USER:rw /dev/ttyUSB0
  board setting     $SRC/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge /dev/ttyUSB0 SETTINGS ALLDD 1
  format a +3 disk  tools/write-disk.sh plus3-blank-720k.img       (HD disk: tape the density hole, both sides)
  cpmtools          run from the diskdefs/ directory, or:  export CPMTOOLSFMT=plus3-720k; cpmcp -f plus3-720k -T raw ...
EOF
