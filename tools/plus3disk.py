#!/usr/bin/env python3
"""plus3disk - work with +3DOS floppies through a DrawBridge.

  plus3disk format [--size 720|180]            blank +3DOS disk (720K double sided by default)
  plus3disk ls                                 list the files on the disk
  plus3disk put FILE... [--basic [--line N]]   copy files onto the disk
                        [--code --addr A]
                        [--as NAME]            name on disk for a single file (8.3, upper case)
                        [--from-image IMG]     use this verified image instead of reading the disk first
  plus3disk get NAME... [--to DIR]             copy files off the disk (header kept; strip with plus3hdr.py)
  plus3disk read IMG                           read the disk into a sector image
  plus3disk write IMG                          write a sector image to the disk, then verify
  plus3disk verify IMG                         read the disk back and compare with IMG

Options: --port /dev/ttyUSB0   --keep-image PATH (save the final verified image)

A write always rewrites the whole disk, so put/format take about 8 minutes:
read 1.5 min, write 5 min with verify, read back 1.5 min.  Nothing is written
unless the disk read back cleanly first, and the result is always read back
and compared byte for byte.  High-density disks: tape the density hole.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "vendor/ArduinoFloppyDiskReader/ArduinoFloppyReader/ArduinoFloppyReader/drawbridge")
GW = os.path.join(ROOT, "gwenv/bin/gw")
DISKDEFS = os.path.join(ROOT, "diskdefs")
SIZES = {"720": ("plus3-720k", 737280, "ibm.720"), "180": ("plus3-180k", 184320, "ibm.180")}


def die(msg):
    sys.exit(f"plus3disk: {msg}")


def run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def find_port(opt):
    if opt:
        return opt
    ports = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    if not ports:
        die("no serial port found; is the DrawBridge plugged in?")
    if not os.access(ports[0], os.R_OK | os.W_OK):
        die(f"no access to {ports[0]}: sudo setfacl -m u:$USER:rw {ports[0]}  (or join the dialout group)")
    return ports[0]


def check_tools():
    for p, hint in ((DB, "run ./setup.sh"), (GW, "run ./setup.sh")):
        if not os.access(p, os.X_OK):
            die(f"{p} missing; {hint}")
    for t in ("cpmls", "cpmcp"):
        if not shutil.which(t):
            die(f"{t} missing; install cpmtools")


def drawbridge(port, *args):
    r = run([DB, port, *args], stdin=subprocess.DEVNULL)
    out = r.stdout.replace("\r", "\n")
    if "Error opening COM port" in out or "not found" in out and "COM port" in out:
        die("cannot open the serial port (replugged? re-run setfacl)")
    return out


def read_disk(port, tmp):
    """Read the disk; return (image path, size key). Dies unless every track decoded."""
    print("reading disk ...", flush=True)
    scp = os.path.join(tmp, "rb.scp")
    drawbridge(port, scp, "READ")
    img = os.path.join(tmp, "rb.img")
    r = run([GW, "convert", "--format=ibm.720", scp, img])
    log = r.stdout + r.stderr
    data = open(img, "rb").read()
    # the +3DOS spec in the boot sector says what the disk is
    size = "720" if data[0] == 3 else "180"
    if size == "180":
        # ibm.720 image order is c0h0 c0h1 c1h0 ...; keep cylinders 0-39, head 0
        data = b"".join(data[c * 9216: c * 9216 + 4608] for c in range(40))
        open(img, "wb").write(data)
        tracks = [l for l in log.splitlines() if re.match(r"T([0-9]|[1-3][0-9])\.0: IBM", l)]
    else:
        tracks = [l for l in log.splitlines() if re.match(r"T[0-9]+\.[01]: IBM", l)]
    bad = [l.split(" from")[0] for l in tracks if "9/9 sectors" not in l]
    print(f"  {len(tracks) - len(bad)} of {len(tracks)} tracks read cleanly")
    if bad:
        die("disk did not read cleanly, refusing to continue:\n  " + "\n  ".join(bad))
    return img, size


def write_disk(port, img):
    size = next((k for k, v in SIZES.items() if v[1] == os.path.getsize(img)), None) or die("image is not 720K or 180K")
    print("writing disk (about 5 minutes) ...", flush=True)
    p = subprocess.Popen([DB, port, img, "WRITE", "VERIFY"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out, _ = p.communicate("RRRRR" + "I" * 400)
    out = out.replace("\r", "\n")
    prompts = [l for l in out.splitlines() if "verify error" in l]
    if prompts:
        print(f"  {len(prompts)} verify prompts during write (tracks retried)")
    if "File written to disk" not in out:
        die("write did not complete:\n" + out[-800:])
    return size


def verify_disk(port, img, tmp):
    print("reading back to verify ...", flush=True)
    back, _ = read_disk(port, tmp)
    if open(back, "rb").read() != open(img, "rb").read():
        die("VERIFY FAILED: disk differs from the image")
    print("verified: disk matches the image byte for byte")


def cpm(cmd, fmt, img, *args):
    r = run(["cpm" + cmd, "-f", fmt, "-T", "raw", img, *args], cwd=DISKDEFS)
    if r.returncode:
        die(f"cpm{cmd} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def disk_name(path, override):
    if override:
        return override.upper()
    base = os.path.basename(path).upper()
    stem, _, ext = base.partition(".")
    stem = re.sub(r"[^A-Z0-9]", "", stem)[:8] or "FILE"
    ext = re.sub(r"[^A-Z0-9]", "", ext)[:3]
    return f"{stem}.{ext}" if ext else stem


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    cmd, args = args[0], args[1:]
    opts, files = {}, []
    flags = {"basic", "code"}
    valued = {"size", "line", "addr", "as", "from-image", "to", "port", "keep-image"}
    while args:
        a = args.pop(0)
        if a.startswith("--"):
            k = a[2:]
            if k in flags:
                opts[k] = True
            elif k in valued:
                opts[k] = args.pop(0) if args else die(f"--{k} needs a value")
            else:
                die(f"unknown option {a}")
        else:
            files.append(a)
    check_tools()
    port = find_port(opts.get("port"))
    tmp = tempfile.mkdtemp(prefix="plus3disk-")
    try:
        if cmd == "format":
            size = opts.get("size", "720")
            size in SIZES or die("--size must be 720 or 180")
            img = os.path.join(tmp, "blank.img")
            run([sys.executable, os.path.join(HERE, "mkplus3img.py"), size, img]).returncode == 0 or die("mkplus3img failed")
            write_disk(port, img)
            verify_disk(port, img, tmp)
            final = img
        elif cmd == "ls":
            img, size = read_disk(port, tmp)
            print(cpm("ls", SIZES[size][0], img, "-F").rstrip())
            final = img
        elif cmd == "put":
            files or die("put needs at least one file")
            if "as" in opts and len(files) > 1:
                die("--as only works with a single file")
            if opts.get("from-image"):
                img = os.path.join(tmp, "disk.img")
                shutil.copy(opts["from-image"], img)
                size = next((k for k, v in SIZES.items() if v[1] == os.path.getsize(img)), None) or die("image is not 720K or 180K")
            else:
                img, size = read_disk(port, tmp)
            fmt = SIZES[size][0]
            for f in files:
                src = f
                if opts.get("basic"):
                    src = os.path.join(tmp, "tok_" + os.path.basename(f))
                    c = [sys.executable, os.path.join(HERE, "bas2plus3.py")]
                    if "line" in opts:
                        c += ["--line", opts["line"]]
                    r = run(c + [f, src])
                    r.returncode == 0 or die(r.stderr or r.stdout)
                elif opts.get("code"):
                    "addr" in opts or die("--code needs --addr")
                    src = os.path.join(tmp, "hdr_" + os.path.basename(f))
                    r = run([sys.executable, os.path.join(HERE, "plus3hdr.py"), "code", "--addr", opts["addr"], f, src])
                    r.returncode == 0 or die(r.stderr or r.stdout)
                name = disk_name(f, opts.get("as"))
                cpm("cp", fmt, img, src, f"0:{name}")
                print(f"  added {name} ({os.path.getsize(src)} bytes)")
            print(cpm("ls", fmt, img).rstrip())
            write_disk(port, img)
            verify_disk(port, img, tmp)
            final = img
        elif cmd == "get":
            files or die("get needs at least one name")
            img, size = read_disk(port, tmp)
            dest = opts.get("to", ".")
            os.makedirs(dest, exist_ok=True)
            for n in files:
                cpm("cp", SIZES[size][0], img, f"0:{n.upper()}", dest)
                print(f"  copied {n.upper()} to {dest}")
            final = img
        elif cmd == "read":
            files or die("read needs an output image path")
            img, size = read_disk(port, tmp)
            shutil.copy(img, files[0])
            print(f"wrote {files[0]} ({SIZES[size][1]} bytes)")
            final = None
        elif cmd == "write":
            files or die("write needs an image path")
            write_disk(port, files[0])
            verify_disk(port, files[0], tmp)
            final = files[0]
        elif cmd == "verify":
            files or die("verify needs an image path")
            verify_disk(port, files[0], tmp)
            final = files[0]
        else:
            die(f"unknown command {cmd}\n{__doc__}")
        if final and opts.get("keep-image"):
            shutil.copy(final, opts["keep-image"])
            print(f"image kept at {opts['keep-image']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
