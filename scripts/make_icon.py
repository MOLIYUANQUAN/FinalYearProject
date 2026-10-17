#!/usr/bin/env python3
"""Friday 图标：黑底白环（一个代理，不用字母）。PNG + ICO。纯标准库。

  python scripts/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

BACKGROUND = (0.0, 0.0, 1.0, 1.0, 0.225)
# 白环：外半径 / 内半径（单位正方形）
RING_OUTER = 0.275
RING_INNER = 0.215
CX, CY = 0.5, 0.5

SAMPLES = 4


def _in_round_rect(x: float, y: float, rect: tuple[float, float, float, float, float]) -> bool:
    x0, y0, x1, y1, r = rect
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _color_at(x: float, y: float) -> tuple[int, int, int] | None:
    if not _in_round_rect(x, y, BACKGROUND):
        return None
    d2 = (x - CX) ** 2 + (y - CY) ** 2
    if RING_INNER * RING_INNER <= d2 <= RING_OUTER * RING_OUTER:
        return WHITE
    return BLACK


def render(size: int) -> bytes:
    rows = bytearray()
    step = 1.0 / (size * SAMPLES)
    total = SAMPLES * SAMPLES
    for py in range(size):
        rows.append(0)
        for px in range(size):
            r = g = b = hits = 0
            for sy in range(SAMPLES):
                y = (py * SAMPLES + sy + 0.5) * step
                for sx in range(SAMPLES):
                    color = _color_at((px * SAMPLES + sx + 0.5) * step, y)
                    if color:
                        r += color[0]
                        g += color[1]
                        b += color[2]
                        hits += 1
            if hits:
                rows += bytes((r // hits, g // hits, b // hits, 255 * hits // total))
            else:
                rows += b"\x00\x00\x00\x00"
    return bytes(rows)


def png(size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(render(size), 9))
        + chunk(b"IEND", b"")
    )


def ico(images: dict[int, bytes]) -> bytes:
    sizes = sorted(images)
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        data = images[size]
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(images[size] for size in sizes)


def main() -> None:
    STATIC.mkdir(exist_ok=True)
    for size in (32, 192, 512):
        (STATIC / f"icon-{size}.png").write_bytes(png(size))
    (STATIC / "friday.ico").write_bytes(ico({size: png(size) for size in (16, 24, 32, 48, 64, 256)}))
    print("wrote static/icon-32.png, icon-192.png, icon-512.png, friday.ico")


if __name__ == "__main__":
    main()
