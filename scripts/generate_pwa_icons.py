"""Generate simple project-owned BT app icons with only Python's standard library."""

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend/public/icons"
GLYPHS = [
    "11110011111",
    "10010000100",
    "10010000100",
    "11110000100",
    "10010000100",
    "10010000100",
    "11110000100",
]


def icon(size):
    unit = size // 16
    left, top = (size - 11 * unit) // 2, (size - 7 * unit) // 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            gx, gy = (x - left) // unit, (y - top) // unit
            on = 0 <= gx < 11 and 0 <= gy < 7 and GLYPHS[gy][gx] == "1"
            row.extend((255, 255, 255) if on else (53, 95, 245))
        rows.append(bytes(row))

    def chunk(kind, value):
        return (
            struct.pack("!I", len(value))
            + kind
            + value
            + struct.pack("!I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    for size in (180, 192, 512):
        (ROOT / f"icon-{size}.png").write_bytes(icon(size))
