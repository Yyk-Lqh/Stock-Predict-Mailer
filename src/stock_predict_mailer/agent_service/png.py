"""Deterministic RGB PNG charts, using only the standard library."""
from __future__ import annotations

import math
import struct
import zlib

from .contracts import instant


def chart_png(chart):
    """Rasterize the chart_svg geometry; textual labels belong in HTML."""
    width, height = 720, 350
    pixels = bytearray(b"\xff" * (width * height * 3))

    def disk(x, y, radius, color):
        for py in range(max(0, math.ceil(y - radius)), min(height, math.floor(y + radius) + 1)):
            for px in range(max(0, math.ceil(x - radius)), min(width, math.floor(x + radius) + 1)):
                if (px - x) ** 2 + (py - y) ** 2 <= radius ** 2:
                    offset = (py * width + px) * 3
                    pixels[offset:offset + 3] = color

    def line(a, b, color, thickness=2, dashed=False, phase=0):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        steps = max(1, math.ceil(length * 2))
        for step in range(steps + 1):
            distance = length * step / steps
            if not dashed or (phase + distance) % 8 < 5:
                disk(a[0] + dx * step / steps, a[1] + dy * step / steps, thickness / 2, color)
        return phase + length

    points = [p for s in chart["series"].values() for p in s["points"]]
    times = [instant(p["at"]).timestamp() for p in points]
    values = [v for p in points for v in (p["value"], p.get("lower", p["value"]), p.get("upper", p["value"]))]
    start, end, low, high = min(times), max(times), min(values), max(values)

    def x(at):
        return 72 + 590 * ((instant(at).timestamp() - start) / (end - start) if end != start else .5)

    def y(value):
        return 232 - 174 * ((value - low) / (high - low) if high != low else .5)

    line((72, 55), (72, 232), bytes.fromhex("829392"), 1)
    line((72, 232), (662, 232), bytes.fromhex("829392"), 1)
    palette = {"observed": "17634d", "forecast": "2356a3", "backtest": "a64b29"}
    for kind, series in chart["series"].items():
        color = bytes.fromhex(palette[kind])
        coords = [(x(p["at"]), y(p["value"])) for p in series["points"]]
        for point in series["points"]:
            if "lower" in point:
                line((x(point["at"]), y(point["lower"])),
                     (x(point["at"]), y(point["upper"])), bytes.fromhex("88b2ec"), 6)
        phase = 0
        for a, b in zip(coords, coords[1:], strict=False):
            phase = line(a, b, color, dashed=kind != "observed", phase=phase)
        for px, py in coords:
            disk(px, py, 3, color)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    # Stored DEFLATE blocks avoid compressor/version-dependent output.
    raw = b"".join(b"\x00" + pixels[row * width * 3:(row + 1) * width * 3] for row in range(height))
    compressed = bytearray(b"\x78\x01")
    for offset in range(0, len(raw), 65535):
        block = raw[offset:offset + 65535]
        compressed += bytes([int(offset + len(block) == len(raw))])
        compressed += struct.pack("<HH", len(block), 65535 - len(block)) + block
    compressed += struct.pack(">I", zlib.adler32(raw))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", bytes(compressed)) + chunk(b"IEND", b""))
