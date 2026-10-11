#!/usr/bin/env python3
"""plus3disk - work with +3DOS floppies through a DrawBridge.

  plus3disk format [--size 720|180]            blank +3DOS disk (720K double sided by default)
  plus3disk ls                                 catalogue: name, size, +3DOS header type, free space
  plus3disk put FILE... [--basic [--line N]]   copy files onto the disk
                        [--code --addr A]
                        [--tap]                FILE is a .tap tape image: one disk file per block, loader patched
                        [--as NAME]            name on disk for a single file, or a tape's loader (8.3, upper case)
                        [--from-image IMG]     use this verified image instead of reading the disk first
  plus3disk get NAME... [--to DIR] [--strip]   copy files off the disk (--strip drops the +3DOS header)
  plus3disk cat NAME                           print a file (header dropped) to stdout
  plus3disk rm NAME...                         delete files
  plus3disk mv OLD NEW                         rename a file
  plus3disk read IMG                           read the disk into a sector image
  plus3disk write IMG                          write a sector image to the disk, then verify
  plus3disk verify IMG                         read the disk back and compare with IMG

Options: --port /dev/ttyUSB0   --keep-image PATH (save the final verified image)
         --image IMG   work on this image file instead of the drive: ls, get and cat read it,
                       put, rm and mv change it in place.  No drive needed.

A write always rewrites the whole disk, so put/rm/mv/format take about 8 minutes:
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
# cpmtools diskdef values, needed to walk the directory ourselves: (boot track bytes, block size, directory entries)
GEOM = {"720": (9 * 512, 2048, 256), "180": (9 * 512, 1024, 64)}
TYPES = {0: "BASIC", 1: "DATA", 2: "DATA", 3: "CODE"}


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
    out = drawbridge(port, scp, "READ")
    if "Error" in out or not os.path.exists(scp) or os.path.getsize(scp) < 1_000_000:
        last = [l for l in out.splitlines() if l.strip()][-3:]
        die("the disk did not read (no disk in the drive, or not seated?)\n  " + "\n  ".join(last))
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
    tracks or die("no tracks decoded from the flux read")
    if bad:
        die("disk did not read cleanly, refusing to continue:\n  " + "\n  ".join(bad))
    return img, size


def write_disk(port, img):
    """Write img with the tool's own verify, answering its prompts as they come.

    Output is streamed, never accumulated: the writer prints progress with
    carriage returns and, on a dead board, can emit prompts at full speed.
    Each track gets 5 retries (the tool itself tries 5 times before each
    prompt), then it is skipped.  Prompts arriving faster than a drive can
    physically fail, or many more prompts than tracks, mean the board is not
    responding; the write is aborted and the process killed."""
    import select, time
    size = image_size(img)
    ntracks = 160 if size == "720" else 40
    print("writing disk (about 5 minutes) ...", flush=True)
    p = subprocess.Popen([DB, port, img, "WRITE", "VERIFY"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=0)
    buf = b""; tail = []; retries = {}; prompts = 0; t_last = 0.0; done = False; failed = []
    t0 = time.time()
    def abort(msg):
        try: p.stdin.write(b"A"); p.stdin.flush()
        except OSError: pass
        p.kill(); p.wait()
        die(msg + "\n  last output:\n  " + "\n  ".join(tail[-8:]))
    try:
      while True:
          if time.time() - t0 > 1800:
              abort("write took more than 30 minutes")
          r, _, _ = select.select([p.stdout], [], [], 5.0)
          if not r:
              if p.poll() is not None: break
              continue
          chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else os.read(p.stdout.fileno(), 4096)
          if not chunk:
              break
          buf += chunk
          while True:
              m = re.search(rb"[\r\n]", buf)
              if m:
                  line, buf = buf[:m.start()].decode("latin-1"), buf[m.end():]
              elif buf.endswith(b"? ") or buf.endswith(b": "):     # a prompt waiting for a key
                  line, buf = buf.decode("latin-1"), b""
              else:
                  break
              if not line.strip():
                  continue
              tail = (tail + [line])[-40:]
              if "File written to disk" in line:
                  done = True
              if "verify error" in line and "[R]etry" in line:
                  prompts += 1
                  now = time.time()
                  if now - t_last < 0.5 or prompts > 6 * ntracks:
                      abort("the board stopped responding during the write")
                  t_last = now
                  mt = re.search(r"track (\d+), (\w+) side", line)
                  key = (mt.group(1), mt.group(2)) if mt else ("?", "?")
                  retries[key] = retries.get(key, 0) + 1
                  if retries[key] <= 5:
                      ans = b"R"
                  else:
                      ans = b"I"                                   # I = skip (S is shown but acts as retry)
                      failed.append(key)
                      print(f"  track {key[0]} {key[1]} side: giving up after 5 retries", flush=True)
                  p.stdin.write(ans); p.stdin.flush()
    except KeyboardInterrupt:
        p.kill(); p.wait()
        die("interrupted; the write is incomplete")
    p.wait()
    if failed:
        print(f"  {len(failed)} track(s) skipped; the read-back will show the damage")
    elif prompts:
        print(f"  {prompts} verify prompt(s) during write, all recovered by retrying")
    if not done:
        die("write did not complete\n  last output:\n  " + "\n  ".join(tail[-8:]))
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


def image_size(img):
    return next((k for k, v in SIZES.items() if v[1] == os.path.getsize(img)), None) or die("image is not 720K or 180K")


def catalogue(img, size):
    """Walk the CP/M directory: return ([(name, bytes, description)], free K) as the +3's CAT shows them."""
    data = open(img, "rb").read()
    boot, bsize, maxdir = GEOM[size]
    nblocks = (len(data) - boot) // bsize                 # blocks 0.. are counted from the directory
    wide = nblocks > 256                                  # 2-byte block pointers on the 720K disk
    dirblocks = maxdir * 32 // bsize
    files, used = {}, set()
    for e in range(maxdir):
        ent = data[boot + e * 32: boot + e * 32 + 32]
        if ent[0] > 15:                                   # 0xE5 free, 0x21+ labels, passwords, timestamps
            continue
        name = (bytes(b & 0x7F for b in ent[1:9]).decode("latin-1").rstrip()
                + "." + bytes(b & 0x7F for b in ent[9:12]).decode("latin-1").rstrip()).rstrip(".")
        extent = (ent[14] << 5) | (ent[12] & 0x1F)
        ptrs = [int.from_bytes(ent[16 + 2 * i: 18 + 2 * i], "little") for i in range(8)] if wide else list(ent[16:32])
        ptrs = [b for b in ptrs if b]
        used.update(ptrs)
        f = files.setdefault(name, {"first": None, "records": 0, "lastlen": 0})
        if extent == 0 and ptrs:
            f["first"] = ptrs[0]
        if extent * 128 + ent[15] > f["records"]:
            f["records"] = extent * 128 + ent[15]
            f["lastlen"] = ent[13] & 0x7F                  # CP/M 3 byte count of the last record, if set
    out = []
    for name in sorted(files):
        f = files[name]
        size_b = f["records"] * 128 - (128 - f["lastlen"] if f["lastlen"] and f["records"] else 0)
        desc = "plain"
        if f["first"] is not None:
            h = data[boot + f["first"] * bsize: boot + f["first"] * bsize + 128]
            if h[:8] == b"PLUS3DOS" and sum(h[:127]) & 0xFF == h[127]:
                length = int.from_bytes(h[16:18], "little")
                p1, p2 = int.from_bytes(h[18:20], "little"), int.from_bytes(h[20:22], "little")
                size_b = int.from_bytes(h[11:15], "little")
                t = h[15]
                if t == 0:
                    desc = "BASIC" + (f"  LINE {p1}" if p1 < 0x8000 else "")
                elif t == 3:
                    desc = f"CODE   {p1},{length}"
                elif t in (1, 2):
                    desc = "DATA   " + chr((h[19] & 0x1F) + 0x60) + ("$" if t == 2 else "") + "()"
                else:
                    desc = f"type {t}"
        out.append((name, size_b, desc))
    free_k = (nblocks - dirblocks - len(used)) * bsize // 1024
    return out, free_k


def print_catalogue(img, size):
    files, free_k = catalogue(img, size)
    for name, size_b, desc in files:
        print(f"  {name:<12} {size_b:>7}  {desc}")
    print(f"  {len(files)} file(s), {free_k}K free")


def strip_header(data):
    if data[:8] == b"PLUS3DOS" and sum(data[:127]) & 0xFF == data[127]:
        return data[128:]
    return data


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
    flags = {"basic", "code", "tap", "strip"}
    valued = {"size", "line", "addr", "as", "from-image", "to", "port", "keep-image", "image"}
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
    for t in ("cpmls", "cpmcp", "cpmrm"):
        shutil.which(t) or die(f"{t} missing; install cpmtools")
    offline = opts.get("image")                                  # work on a file, never touch the drive
    if offline:
        os.path.isfile(offline) or die(f"{offline}: no such image")
        offline = os.path.abspath(offline)
        cmd in ("ls", "get", "cat", "put", "rm", "mv") or die(f"--image does not apply to {cmd}")
    else:
        check_tools()
        port = find_port(opts.get("port"))
    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)       # on disk, not /tmp (often RAM)
    tmp = tempfile.mkdtemp(prefix="plus3disk-", dir=os.path.join(ROOT, "work"))

    def load():
        """The disk image to work on: the --image file, the --from-image file, or a fresh read of the disk."""
        if offline:
            return offline, image_size(offline)
        if opts.get("from-image"):
            img = os.path.join(tmp, "disk.img")
            shutil.copy(opts["from-image"], img)
            return img, image_size(img)
        return read_disk(port, tmp)

    def commit(img, size):
        """Put a changed image back: onto the disk with verify, or over the --image file."""
        if offline:
            print(f"updated {offline}")
            return
        write_disk(port, img)
        verify_disk(port, img, tmp)

    def must_exist(img, size, names):
        have = {n for n, _, _ in catalogue(img, size)[0]}
        missing = [n for n in names if n not in have]
        missing and die(f"not on the disk: {' '.join(missing)}")

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
            img, size = load()
            print_catalogue(img, size)
            final = img
        elif cmd == "put":
            files or die("put needs at least one file")
            if "as" in opts and len(files) > 1:
                die("--as only works with a single file")
            img, size = load()
            if offline:
                img = os.path.join(tmp, "disk.img"); shutil.copy(offline, img)
            fmt = SIZES[size][0]
            if opts.get("tap"):
                tapfiles = []
                for f in files:
                    outdir = os.path.join(tmp, "tap_" + re.sub(r"[^A-Za-z0-9]", "_", os.path.basename(f)))
                    taken = {n for n, _, _ in catalogue(img, size)[0]} | {os.path.basename(t) for t in tapfiles}
                    r = run([sys.executable, os.path.join(HERE, "tap2plus3.py"), "--avoid", ",".join(sorted(taken)), f, outdir])
                    r.returncode == 0 or die(r.stderr.strip() or r.stdout.strip())
                    sys.stderr.write(r.stderr)
                    tapfiles += [os.path.join(outdir, l.split()[0]) for l in r.stdout.splitlines() if l.strip()]
                if "as" in opts:                               # --as names the loader; the other blocks keep theirs
                    len(files) == 1 or die("--as only works with a single tape")
                    new = os.path.join(os.path.dirname(tapfiles[0]), opts["as"].upper())
                    os.rename(tapfiles[0], new)
                    tapfiles[0] = new
                    del opts["as"]
                files = tapfiles
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
                verb = "added"
                if name in {n for n, _, _ in catalogue(img, size)[0]}:
                    cpm("rm", fmt, img, f"0:{name}")              # replace, as SAVE does on the +3
                    verb = "replaced"
                cpm("cp", fmt, img, os.path.abspath(src), f"0:{name}")
                print(f"  {verb} {name} ({os.path.getsize(src)} bytes)")
            print_catalogue(img, size)
            if offline:
                shutil.copy(img, offline)
            commit(img, size)
            final = img
        elif cmd == "get":
            files or die("get needs at least one name")
            img, size = load()
            names = [n.upper() for n in files]
            must_exist(img, size, names)
            dest = os.path.abspath(opts.get("to", "."))
            os.makedirs(dest, exist_ok=True)
            for n in names:
                cpm("cp", SIZES[size][0], img, f"0:{n}", dest)
                path = os.path.join(dest, n.lower())             # cpmcp writes lower-case names
                if not os.path.exists(path):
                    path = os.path.join(dest, n)
                if opts.get("strip"):
                    data = open(path, "rb").read()
                    stripped = strip_header(data)
                    open(path, "wb").write(stripped)
                    print(f"  copied {n} to {path}" + (" (header stripped)" if len(stripped) != len(data) else " (no header)"))
                else:
                    print(f"  copied {n} to {path}")
            final = img
        elif cmd == "cat":
            len(files) == 1 or die("cat needs exactly one name")
            img, size = load()
            n = files[0].upper()
            must_exist(img, size, [n])
            out = os.path.join(tmp, "out"); os.makedirs(out)
            cpm("cp", SIZES[size][0], img, f"0:{n}", out)
            path = os.path.join(out, os.listdir(out)[0])
            sys.stdout.buffer.write(strip_header(open(path, "rb").read()))
            sys.stdout.flush()
            final = img
        elif cmd == "rm":
            files or die("rm needs at least one name")
            img, size = load()
            if offline:
                img = os.path.join(tmp, "disk.img"); shutil.copy(offline, img)
            names = [n.upper() for n in files]
            must_exist(img, size, names)
            for n in names:
                cpm("rm", SIZES[size][0], img, f"0:{n}")
                print(f"  deleted {n}")
            print_catalogue(img, size)
            if offline:
                shutil.copy(img, offline)
            commit(img, size)
            final = img
        elif cmd == "mv":
            len(files) == 2 or die("mv needs OLD NEW")
            img, size = load()
            if offline:
                img = os.path.join(tmp, "disk.img"); shutil.copy(offline, img)
            old, new = files[0].upper(), disk_name(files[1], None)
            must_exist(img, size, [old])
            have = {n for n, _, _ in catalogue(img, size)[0]}
            new in have and die(f"{new} already exists")
            fmt = SIZES[size][0]
            out = os.path.join(tmp, "out"); os.makedirs(out)
            cpm("cp", fmt, img, f"0:{old}", out)                 # cpmtools has no rename: copy out, delete, copy in
            path = os.path.join(out, os.listdir(out)[0])
            cpm("rm", fmt, img, f"0:{old}")
            cpm("cp", fmt, img, path, f"0:{new}")
            print(f"  renamed {old} to {new}")
            print_catalogue(img, size)
            if offline:
                shutil.copy(img, offline)
            commit(img, size)
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
