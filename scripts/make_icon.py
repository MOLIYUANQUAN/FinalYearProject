#!/usr/bin/env python3
"""画 Friday 的图标「F.」：PNG（网页 / 窗口）+ ICO（桌面快捷方式）。纯标准库，无需 Pillow。

  python scripts/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

GREEN = (15, 92, 76)
CREAM = (255, 252, 247)
AMBER = (242, 180, 90)

# 单位正方形里的几何（y 向下）：圆角底 + F + 落在基线上的句点
BACKGROUND = (0.0, 0.0, 1.0, 1.0, 0.225)
F_BARS = (
    (0.26, 0.24, 0.38, 0.76, 0.012),
    (0.26, 0.24, 0.64, 0.355, 0.012),
    (0.26, 0.465, 0.57, 0.575, 0.012),
)
DOT = (0.71, 0.705, 0.065)

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
    dx, dy, dr = DOT
    if (x - dx) ** 2 + (y - dy) ** 2 <= dr * dr:
        return AMBER
    if any(_in_round_rect(x, y, bar) for bar in F_BARS):
        return CREAM
    return GREEN


def render(size: int) -> bytes:
    """RGBA 行数据（每行前置 PNG 过滤字节 0）。"""
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
    """PNG 内嵌的 ICO（Windows Vista 起支持）。"""
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
