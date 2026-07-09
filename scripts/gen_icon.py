#!/usr/bin/env python3
"""Generate the macOS app-icon iconset — pure standard library (no PIL).

Draws the same analytics mark as static/icon.svg (rounded blue tile, three
ascending white bars, a trend line + dot) at every size iconutil needs, using
signed-distance-field anti-aliasing. Writes an .iconset directory ready for
`iconutil -c icns`.

Usage: gen_icon.py <iconset_dir>
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

TOP = (76, 141, 255)      # #4c8dff
BOTTOM = (27, 110, 243)   # #1b6ef3
LINE = (207, 227, 255)    # #cfe3ff
WHITE = (255, 255, 255)

# Bars and trend in a 100x100 design space (matches icon.svg).
BARS = [(23, 56, 12, 21), (44, 44, 12, 33), (65, 30, 12, 47)]
TREND = [(29, 52), (50, 41), (71, 27)]
DOT = (71, 27, 5)


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def _sdf_rbox(px, py, cx, cy, hx, hy, r):
    qx = abs(px - cx) - (hx - r)
    qy = abs(py - cy) - (hy - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - x1, py - y1)
    t = _clamp(((px - x1) * dx + (py - y1) * dy) / l2)
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _blend(dst, off, rgb, cov):
    if cov <= 0:
        return
    inv = 1.0 - cov
    dst[off] = int(dst[off] * inv + rgb[0] * cov)
    dst[off + 1] = int(dst[off + 1] * inv + rgb[1] * cov)
    dst[off + 2] = int(dst[off + 2] * inv + rgb[2] * cov)


def draw(size: int) -> bytearray:
    s = size / 100.0
    cx = cy = size / 2.0
    hx = hy = 46.0 * s
    r = 22.0 * s
    bars = [(x + w / 2, y + h / 2, w / 2, h / 2) for (x, y, w, h) in BARS]
    trend = [(x * s, y * s) for (x, y) in TREND]
    half_stroke = 2.0 * s
    dcx, dcy, dr = DOT[0] * s, DOT[1] * s, DOT[2] * s
    buf = bytearray(size * size * 4)

    for y in range(size):
        t = _clamp(y / max(size - 1, 1))
        base = (int(TOP[0] + (BOTTOM[0] - TOP[0]) * t),
                int(TOP[1] + (BOTTOM[1] - TOP[1]) * t),
                int(TOP[2] + (BOTTOM[2] - TOP[2]) * t))
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            alpha = _clamp(0.5 - _sdf_rbox(px, py, cx, cy, hx, hy, r))
            off = (y * size + x) * 4
            if alpha <= 0:
                continue
            buf[off] = base[0]; buf[off + 1] = base[1]; buf[off + 2] = base[2]
            buf[off + 3] = int(alpha * 255)
            # bars (rounded)
            for (bx, by, bhx, bhy) in bars:
                cov = _clamp(0.5 - _sdf_rbox(px, py, bx * s, by * s, bhx * s, bhy * s, 3 * s))
                if cov > 0:
                    _blend(buf, off, WHITE, cov)
            # trend line
            dmin = min(_seg_dist(px, py, trend[i][0], trend[i][1], trend[i + 1][0], trend[i + 1][1])
                       for i in range(len(trend) - 1))
            _blend(buf, off, LINE, _clamp(half_stroke + 0.5 - dmin))
            # dot
            _blend(buf, off, WHITE, _clamp(dr + 0.5 - math.hypot(px - dcx, py - dcy)))
    return buf


def write_png(path: Path, size: int, rgba: bytearray) -> None:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = bytearray()
    row = size * 4
    for y in range(size):
        raw.append(0)
        raw += rgba[y * row:(y + 1) * row]
    idat = zlib.compress(bytes(raw), 9)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


# size -> iconset filenames
TARGETS = {
    16: ["icon_16x16.png"],
    32: ["icon_16x16@2x.png", "icon_32x32.png"],
    64: ["icon_32x32@2x.png"],
    128: ["icon_128x128.png"],
    256: ["icon_128x128@2x.png", "icon_256x256.png"],
    512: ["icon_256x256@2x.png", "icon_512x512.png"],
    1024: ["icon_512x512@2x.png"],
}


def main(argv):
    if len(argv) < 2:
        print("usage: gen_icon.py <iconset_dir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for size, names in TARGETS.items():
        rgba = draw(size)
        for name in names:
            write_png(out / name, size, rgba)
    print(f"wrote {sum(len(v) for v in TARGETS.values())} PNGs to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
