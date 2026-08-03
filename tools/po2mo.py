#!/usr/bin/env python3
"""
po2mo.py -- compile a gettext .po catalog into a binary .mo.

Written because the msgfmt.py bundled with MusicBot (i18n/msgfmt.py, from upstream
commit 4224ab7) resets `msgid = msgstr = b""` *inside* the per-line parse loop, so
`add()` always receives an empty msgstr and its `if not fuzzy and msgstr` guard drops
every entry. That tool can only ever emit a 28-byte (empty) .mo, which is why no .mo
files exist in the repo and why translations silently never load.

Usage:  po2mo.py <input.po> [output.mo]
"""
import re
import struct
import sys
import pathlib

# gettext .po string escapes (a deliberately small, exact set -- anything else,
# such as \N{...}, must survive as literal text for MusicBot to process later).
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            # Unknown escape: keep the backslash literally.
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_po(text: str):
    """Yield (msgid, msgstr) pairs, already unescaped."""
    entries = re.split(r"\n\n+", text)
    for e in entries:
        mi = re.search(r"^msgid ((?:\s*\"(?:[^\"\\]|\\.)*\"\n?)+)", e, re.M)
        ms = re.search(r"^msgstr ((?:\s*\"(?:[^\"\\]|\\.)*\"\n?)+)", e, re.M)
        if not mi or not ms:
            continue
        msgid = "".join(re.findall(r"\"((?:[^\"\\]|\\.)*)\"", mi.group(1)))
        msgstr = "".join(re.findall(r"\"((?:[^\"\\]|\\.)*)\"", ms.group(1)))
        yield unescape(msgid), unescape(msgstr)


def write_mo(pairs, path: pathlib.Path) -> int:
    # Keep only entries that actually carry a translation. The header (msgid "")
    # must be kept -- gettext reads Content-Type/Language from it, and MusicBot
    # compares info()["language"] against the guild's setting to decide whether
    # its cached catalog is still valid.
    items = [(k.encode("utf-8"), v.encode("utf-8")) for k, v in pairs if v]
    items.sort(key=lambda kv: kv[0])

    n = len(items)
    keystart = 7 * 4 + 16 * n
    offsets = []
    ids = b""
    strs = b""
    for kid, kstr in items:
        offsets.append((len(ids), len(kid), len(strs), len(kstr)))
        ids += kid + b"\0"
        strs += kstr + b"\0"
    valuestart = keystart + len(ids)

    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]

    output = struct.pack(
        "Iiiiiii",
        0x950412DE,   # magic
        0,            # version
        n,            # number of entries
        7 * 4,        # start of key index
        7 * 4 + n * 8,  # start of value index
        0, 0,         # size/offset of hash table (unused)
    )
    output += array_pack(koffsets + voffsets)
    output += ids
    output += strs

    path.write_bytes(output)
    return n


def array_pack(values):
    return struct.pack("%di" % len(values), *values)


def main():
    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".mo")

    pairs = list(parse_po(src.read_text(encoding="utf-8")))
    n = write_mo(pairs, dst)
    print(f"{src.name}: {len(pairs)} entries parsed, {n} translated -> {dst} ({dst.stat().st_size} bytes)")
    if n == 0:
        print("ERROR: nothing translated, the .mo would be useless", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
