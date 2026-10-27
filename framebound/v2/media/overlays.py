"""Diagnostic overlays: bbox, span line, contact window. Review derivatives, never evidence."""
from __future__ import annotations

from PIL import Image, ImageDraw


def render_overlay(img: Image.Image, *, bbox: list[int] | None = None,
                   span: list[tuple[float, float]] | None = None,
                   window: list[int] | None = None) -> Image.Image:
    out = img.convert("RGBA").copy()
    d = ImageDraw.Draw(out)
    if window is not None:
        d.rectangle(window, outline=(255, 200, 40, 255), width=1)
    if bbox is not None:
        d.rectangle(bbox, outline=(80, 220, 255, 255), width=1)
    if span is not None and len(span) == 2:
        d.line([*span[0], *span[1]], fill=(255, 90, 90, 255), width=1)
        for x, y in span:
            d.ellipse([x - 2, y - 2, x + 2, y + 2], outline=(255, 90, 90, 255))
    return out
