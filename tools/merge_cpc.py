"""Merge good sectors from several SCP flux passes of a 40-track double-sided
CPC disk and write one raw 180K image per side.  Side 0 is expected to be
CPC System format (sector IDs 0x41-0x49) and side 1 CPC Data format
(0xC1-0xC9); the base ID is detected per side from whatever is found."""
import sys, collections
from greaseweazle.codec import codec
from greaseweazle.image.scp import SCP

CYLS, HEADS, SPT, BPS = 40, 2, 9, 512
passes = sys.argv[1:-1]; outprefix = sys.argv[-1]
fmt = codec.get_diskdef('ibm.scan')
good = {}            # (cyl, head, r) -> data
seen_ids = collections.defaultdict(set)
for p in passes:
    img = SCP.from_file(p, None, {})
    for c in range(CYLS):
        for h in range(HEADS):
            flux = img.get_track(c, h)
            if flux is None: continue
            t = fmt.mk_track(c, h)
            t.decode_flux(flux)
            for s in getattr(t.track, 'sectors', []):
                seen_ids[h].add(s.idam.r)
                if s.crc == 0 and (c, h, s.idam.r) not in good:
                    good[(c, h, s.idam.r)] = bytes(s.dam.data)
for h in range(HEADS):
    base = min(seen_ids[h]) if seen_ids[h] else 1
    missing = []
    out = bytearray()
    for c in range(CYLS):
        for r in range(base, base + SPT):
            d = good.get((c, h, r))
            if d is None:
                missing.append(f"T{c} sector {r:02X}")
                d = b'\xe5' * BPS
            out += d[:BPS].ljust(BPS, b'\xe5')
    name = f"{outprefix}-side{h}.raw"
    open(name, 'wb').write(out)
    print(f"side {h}: sector IDs {base:02X}-{base+SPT-1:02X}, {len(out)} bytes -> {name}")
    print(f"  missing sectors: {len(missing)}" + (": " + ", ".join(missing) if missing else ""))
