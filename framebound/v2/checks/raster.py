"""Shared raster primitives on canonical RGBA bytes (no skeletons inferred)."""
from __future__ import annotations

import math


def alpha_mask(px: bytes, w: int, h: int, min_alpha: int = 128) -> bytearray:
    return bytearray(1 if px[i + 3] >= min_alpha else 0 for i in range(0, len(px), 4))


def silhouette(mask: bytearray, w: int, h: int) -> dict:
    area = sum(mask)
    if not area:
        return {"area": 0, "bbox": None, "centroid": None, "width": 0, "height": 0}
    xs = [x for y in range(h) for x in range(w) if mask[y * w + x]]
    ys = [y for y in range(h) for x in range(w) if mask[y * w + x]]
    return {"area": area, "bbox": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
            "width": max(xs) - min(xs) + 1, "height": max(ys) - min(ys) + 1,
            "centroid": [sum(xs) / area, sum(ys) / area]}


def occupancy_descriptor(px: bytes, w: int, h: int, region: list[int], grid: list[int],
                           asymmetry_weight: float = 2.0) -> list[float]:
    """Occupancy grid + signed horizontal-asymmetry term.

    Pure alpha occupancy cannot separate mirror poses (A-side vs B-side contact share a
    silhouette). The asymmetry term (right-half mass minus left-half mass, normalized)
    distinguishes mirrors while remaining a registered raster measurement, not a judgment.
    """

    left, top, right, bottom = region
    cols, rows = grid
    out = []
    for r in range(rows):
        y0, y1 = top + (bottom - top) * r // rows, top + (bottom - top) * (r + 1) // rows
        for c in range(cols):
            x0, x1 = left + (right - left) * c // cols, left + (right - left) * (c + 1) // cols
            tot = 0
            for y in range(y0, y1):
                base = y * w * 4
                for x in range(x0, x1):
                    tot += px[base + x * 4 + 3]
            out.append(tot / (255 * max(1, (x1 - x0) * (y1 - y0))))
    left, top, right, bottom = region
    left_mass = right_mass = 0
    for y in range(top, bottom):
        base = y * w * 4
        for x in range(left, right):
            a = px[base + x * 4 + 3]
            if x < (left + right) / 2:
                left_mass += a
            else:
                right_mass += a
    total = left_mass + right_mass
    asym = ((right_mass - left_mass) / total) if total else 0.0
    out.append(asymmetry_weight * asym)
    return out


def descriptor_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def quantized_palette_distance(px_a: bytes, px_b: bytes, bins: int = 4) -> float:
    """Masked-agnostic global histogram distance (coarse). Part-level comparison is separate."""
    def hist(px: bytes) -> list[int]:
        h = [0] * (bins ** 3)
        for i in range(0, len(px), 4):
            if px[i + 3] < 128:
                continue
            h[((px[i] * bins // 256) * bins + (px[i + 1] * bins // 256)) * bins + (px[i + 2] * bins // 256)] += 1
        return h
    ha, hb = hist(px_a), hist(px_b)
    na, nb = sum(ha), sum(hb)
    if not na or not nb:
        return 1.0
    return sum(abs(x / na - y / nb) for x, y in zip(ha, hb)) / 2.0


def feature_points(px: bytes, w: int, h: int, color: tuple[int, int, int],
                   window: list[int], tol: int = 40) -> list[tuple[float, float]]:
    """Find connected-ish feature pixels of a declared costume color inside a search window."""
    l, t, r, b = window
    pts = []
    for y in range(max(0, t), min(h, b)):
        for x in range(max(0, l), min(w, r)):
            i = (y * w + x) * 4
            if px[i + 3] < 128:
                continue
            if abs(px[i] - color[0]) <= tol and abs(px[i + 1] - color[1]) <= tol and abs(px[i + 2] - color[2]) <= tol:
                pts.append((x + 0.5, y + 0.5))
    return pts


def centroid(pts: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
