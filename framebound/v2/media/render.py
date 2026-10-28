"""Single canonical native render path (Stage B corrected handoff).

Every consumer -- evaluation, desk images, video, runtime capture, export --
renders through render_native(): load the stored asset bytes once, apply the
frame's recorded registration translation exactly once onto the frozen native
canvas, and return canonical RGBA pixels. No caller may pre-translate the
asset and also apply the registration, and no caller may shift unchanged
slots.
"""
from __future__ import annotations

import io as _io

from PIL import Image as _Image

from .canonical import canonical_pixels, pixel_sha256, load_native_image


def render_native(raw_bytes: bytes, translation_px: list[int] | tuple[int, int] | None,
                  canvas: tuple[int, int]) -> tuple[bytes, str, tuple[int, int]]:
    """Render stored bytes onto the native canvas, applying translation once.

    Returns (canonical_pixels, pixel_sha256, (w, h)). Translation defaults to
    [0, 0] (no-op). Assets already sized to the canvas are pasted once;
    undersized sources are placed at the translated origin on a transparent
    canvas (never independently refit per pose).
    """
    dx, dy = 0, 0
    if translation_px:
        dx, dy = int(translation_px[0]), int(translation_px[1])
    base = load_native_image(raw_bytes)
    w, h = canvas
    if base.size == (w, h) and (dx, dy) == (0, 0):
        canon = canonical_pixels(base)
        return canon, pixel_sha256(canon), (w, h)
    out = _Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(base, (dx, dy))
    canon = canonical_pixels(out)
    return canon, pixel_sha256(canon), (w, h)
