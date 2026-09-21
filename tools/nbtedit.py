#!/usr/bin/env python3
"""Decode a Minecraft .dat to SNBT text, and encode it back.

    nbtedit.py decode <file.dat> [out.snbt]     .dat  -> readable SNBT
    nbtedit.py encode <in.snbt> <file.dat>      SNBT  -> .dat (keeps a .bak)

SNBT is the same notation commands use: {Time: 1234L, spawn: {pos: [I; 0,64,0]}}
with b/s/L/f/d suffixes on numbers. Stop the server before encoding, or its next
save will overwrite the file.
"""
import gzip, struct, sys, shutil

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE = 0, 1, 2, 3, 4, 5, 6
BYTES, STRING, LIST, COMPOUND, INTS, LONGS = 7, 8, 9, 10, 11, 12
NUM = {BYTE: (">b", 1, "b"), SHORT: (">h", 2, "s"), INT: (">i", 4, ""),
       LONG: (">q", 8, "L"), FLOAT: (">f", 4, "f"), DOUBLE: (">d", 8, "d")}
ARRAY = {BYTES: (">b", 1, "B"), INTS: (">i", 4, "I"), LONGS: (">q", 8, "L")}

# ---------------- decode ----------------

def dec(buf, i, tag, depth):
    if tag in NUM:
        fmt, width, suffix = NUM[tag]
        return i + width, "%s%s" % (struct.unpack_from(fmt, buf, i)[0], suffix)
    if tag == STRING:
        n = struct.unpack_from(">H", buf, i)[0]
        s = buf[i + 2:i + 2 + n].decode("utf-8", "replace")
        return i + 2 + n, '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')
    if tag in ARRAY:
        fmt, width, prefix = ARRAY[tag]
        n = struct.unpack_from(">i", buf, i)[0]
        vals = [str(struct.unpack_from(fmt, buf, i + 4 + width * k)[0]) for k in range(n)]
        return i + 4 + width * n, "[%s; %s]" % (prefix, ", ".join(vals))
    if tag == LIST:
        inner = buf[i]
        n = struct.unpack_from(">i", buf, i + 1)[0]
        j, parts = i + 5, []
        for _ in range(n):
            j, s = dec(buf, j, inner, depth + 1)
            parts.append(s)
        if not parts:
            return j, "[]"
        if sum(len(p) for p in parts) < 70:
            return j, "[%s]" % ", ".join(parts)
        pad = "  " * (depth + 1)
        return j, "[\n" + ",\n".join(pad + p for p in parts) + "\n" + "  " * depth + "]"
    if tag == COMPOUND:
        items = []
        while buf[i] != END:
            t = buf[i]
            nl = struct.unpack_from(">H", buf, i + 1)[0]
            name = buf[i + 3:i + 3 + nl].decode("utf-8", "replace")
            i, s = dec(buf, i + 3 + nl, t, depth + 1)
            items.append("%s: %s" % (name, s))
        i += 1
        if not items:
            return i, "{}"
        pad = "  " * (depth + 1)
        return i, "{\n" + ",\n".join(pad + x for x in items) + "\n" + "  " * depth + "}"
    raise ValueError("unknown tag %d" % tag)

# ---------------- parse SNBT ----------------

class P:
    def __init__(self, s):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def take(self, c):
        self.ws()
        if self.s[self.i] != c:
            raise ValueError("expected %r at %d, found %r" % (c, self.i, self.s[self.i]))
        self.i += 1

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def string(self):
        self.take('"')
        out = []
        while self.s[self.i] != '"':
            if self.s[self.i] == "\\":
                self.i += 1
            out.append(self.s[self.i])
            self.i += 1
        self.i += 1
        return "".join(out)

    def key(self):
        self.ws()
        if self.peek() == '"':
            return self.string()
        j = self.i
        while self.s[self.i] not in ": \t\r\n":
            self.i += 1
        return self.s[j:self.i]

    def value(self):
        c = self.peek()
        if c == "{":
            return self.compound()
        if c == "[":
            return self.listish()
        if c == '"':
            return (STRING, self.string())
        j = self.i
        while self.i < len(self.s) and self.s[self.i] not in ",}] \t\r\n":
            self.i += 1
        return self.scalar(self.s[j:self.i])

    def scalar(self, tok):
        if tok in ("true", "false"):
            return (BYTE, 1 if tok == "true" else 0)
        for tag, (_, _, suffix) in NUM.items():
            if suffix and tok[-1] in (suffix, suffix.upper()):
                body = tok[:-1]
                return (tag, float(body) if tag in (FLOAT, DOUBLE) else int(body))
        if "." in tok or "e" in tok or "E" in tok:
            return (DOUBLE, float(tok))
        return (INT, int(tok))

    def compound(self):
        self.take("{")
        items = []
        while self.peek() != "}":
            k = self.key()
            self.take(":")
            items.append((k, self.value()))
            if self.peek() == ",":
                self.take(",")
        self.take("}")
        return (COMPOUND, items)

    def listish(self):
        self.take("[")
        if self.i + 1 < len(self.s) and self.s[self.i + 1] == ";":
            prefix, self.i = self.s[self.i], self.i + 2
            tag = {"B": BYTES, "I": INTS, "L": LONGS}[prefix.upper()]
            vals = []
            while self.peek() != "]":
                _, v = self.value()
                vals.append(int(v))
                if self.peek() == ",":
                    self.take(",")
            self.take("]")
            return (tag, vals)
        items = []
        while self.peek() != "]":
            items.append(self.value())
            if self.peek() == ",":
                self.take(",")
        self.take("]")
        return (LIST, items)

# ---------------- encode ----------------

def enc_payload(out, tag, val):
    if tag in NUM:
        fmt = NUM[tag][0]
        out += struct.pack(fmt, val)
        return
    if tag == STRING:
        b = val.encode("utf-8")
        out += struct.pack(">H", len(b)) + b
        return
    if tag in ARRAY:
        fmt = ARRAY[tag][0]
        out += struct.pack(">i", len(val))
        for v in val:
            out += struct.pack(fmt, v)
        return
    if tag == LIST:
        inner = val[0][0] if val else END
        out += bytes([inner]) + struct.pack(">i", len(val))
        for t, v in val:
            if t != inner:
                raise ValueError("mixed types in list")
            enc_payload(out, t, v)
        return
    if tag == COMPOUND:
        for name, (t, v) in val:
            nb = name.encode("utf-8")
            out += bytes([t]) + struct.pack(">H", len(nb)) + nb
            enc_payload(out, t, v)
        out += bytes([END])
        return
    raise ValueError("cannot encode tag %d" % tag)

def load(path):
    head = open(path, "rb").read(2)
    opener = gzip.open if head == b"\x1f\x8b" else open
    return bytearray(opener(path, "rb").read()), (opener is gzip.open)

def main():
    mode, src = sys.argv[1], sys.argv[2]
    if mode == "decode":
        buf, _ = load(src)
        nl = struct.unpack_from(">H", buf, 1)[0]
        _, text = dec(buf, 3 + nl, COMPOUND, 0)
        text += "\n"
        if len(sys.argv) > 3:
            open(sys.argv[3], "w").write(text)
            print("wrote %s" % sys.argv[3])
        else:
            sys.stdout.write(text)
    elif mode == "encode":
        dst = sys.argv[3]
        tag, val = P(open(src).read()).value()
        if tag != COMPOUND:
            raise SystemExit("SNBT root must be a compound")
        body = bytearray(bytes([COMPOUND]) + struct.pack(">H", 0))
        enc_payload(body, COMPOUND, val)
        shutil.copy2(dst, dst + ".bak")
        with gzip.open(dst, "wb") as f:
            f.write(bytes(body))
        print("wrote %s (backup at %s.bak)" % (dst, dst))
    else:
        raise SystemExit(__doc__)

main()
