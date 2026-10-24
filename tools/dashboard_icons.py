"""Generate the existing note icon as small dependency-free PNGs (no network)."""
from pathlib import Path
import struct
import zlib

def png(size):
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            a, b = (x + .5)*64/size, (y + .5)*64/size
            color = (16, 16, 24)
            # Same note geometry/palette as favicon.svg; solid full-bleed iOS tile.
            bar = ((23 <= a <= 29 and 20 <= b <= 46) or
                   (48 <= a <= 54 and 15 <= b <= 40) or
                   (26 <= a <= 51 and abs(b - (20-(a-26)*.2)) <= 3) or
                   (26 <= a <= 51 and abs(b - (26-(a-26)*.2)) <= 3))
            if bar or ((a-19)/10)**2 + ((b-46)/7)**2 <= 1:
                color = (100, 210, 255)
            if ((a-44)/10)**2 + ((b-40)/7)**2 <= 1:
                color = (191, 90, 242)
            rows.extend(color)
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind+value))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size,size,8,2,0,0,0)) +
            chunk(b"IDAT", zlib.compress(bytes(rows),9)) + chunk(b"IEND", b""))

if __name__ == "__main__":
    root = Path(__file__).parents[1] / "frontend" / "public"
    for size, filename in ((192,"icon-192.png"),(512,"icon-512.png"),(180,"apple-touch-icon.png")):
        data = png(size)
        (root / filename).write_bytes(data)
        print(filename, len(data))
