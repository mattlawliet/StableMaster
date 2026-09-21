#!/usr/bin/env python3
"""Read or set the game clock (Data.Time) in a Minecraft level.dat.

Usage:  nbttime.py <level.dat>              show Time and DayTime
        nbttime.py <level.dat> <new Time>   set Time (writes a .bak first)

Patches the 8 bytes of the long in place, so nothing about the file's
structure changes. Server must be stopped.
"""
import gzip, struct, sys, shutil

TAG_END, TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG = 0, 1, 2, 3, 4
TAG_FLOAT, TAG_DOUBLE, TAG_BYTES, TAG_STRING = 5, 6, 7, 8
TAG_LIST, TAG_COMPOUND, TAG_INTS, TAG_LONGS = 9, 10, 11, 12
FIXED = {TAG_BYTE: 1, TAG_SHORT: 2, TAG_INT: 4, TAG_LONG: 8, TAG_FLOAT: 4, TAG_DOUBLE: 8}

def skip(buf, i, tag):
    """Return offset just past a payload of this tag type."""
    if tag in FIXED:
        return i + FIXED[tag]
    if tag == TAG_STRING:
        return i + 2 + struct.unpack_from(">H", buf, i)[0]
    if tag == TAG_BYTES:
        return i + 4 + struct.unpack_from(">i", buf, i)[0]
    if tag == TAG_INTS:
        return i + 4 + 4 * struct.unpack_from(">i", buf, i)[0]
    if tag == TAG_LONGS:
        return i + 4 + 8 * struct.unpack_from(">i", buf, i)[0]
    if tag == TAG_LIST:
        inner = buf[i]
        n = struct.unpack_from(">i", buf, i + 1)[0]
        i += 5
        for _ in range(n):
            i = skip(buf, i, inner)
        return i
    if tag == TAG_COMPOUND:
        while buf[i] != TAG_END:
            t = buf[i]
            nlen = struct.unpack_from(">H", buf, i + 1)[0]
            i = skip(buf, i + 3 + nlen, t)
        return i + 1
    raise ValueError("unknown tag %d at %d" % (tag, i))

def find(buf, i, path):
    """Offset of the payload at compound path, e.g. ['Data', 'Time']."""
    want, rest = path[0], path[1:]
    while buf[i] != TAG_END:
        t = buf[i]
        nlen = struct.unpack_from(">H", buf, i + 1)[0]
        name = buf[i + 3:i + 3 + nlen].decode()
        payload = i + 3 + nlen
        if name == want:
            return payload if not rest else find(buf, payload, rest)
        i = skip(buf, payload, t)
    raise KeyError(want)

def load(path):
    with open(path, "rb") as f:
        head = f.read(2)
    opener = gzip.open if head == b"\x1f\x8b" else open
    with opener(path, "rb") as f:
        return bytearray(f.read()), (opener is gzip.open)

def root(buf):
    nlen = struct.unpack_from(">H", buf, 1)[0]
    return 3 + nlen

def main():
    path = sys.argv[1]
    buf, gz = load(path)
    r = root(buf)
    t = find(buf, r, ["Data", "Time"])
    print("Time %d" % struct.unpack_from(">q", buf, t))
    if len(sys.argv) < 3:
        return
    new = int(sys.argv[2])
    old = struct.unpack_from(">q", buf, t)[0]
    if new < old:
        print("REFUSING: %d is lower than the current %d. Moving a world clock "
              "backwards is what causes the camel bug." % (new, old))
        sys.exit(1)
    shutil.copy2(path, path + ".bak")
    struct.pack_into(">q", buf, t, new)
    writer = gzip.open if gz else open
    with writer(path, "wb") as f:
        f.write(bytes(buf))
    print("Time set to %d (backup at %s.bak)" % (new, path))

main()
