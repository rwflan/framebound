"""Frozen registration: one uniform source-to-native scale per source family.

No per-pose fitting. Integer translation default (pixel art); subpixel only when the
contract declares it with a fixed resampling filter. Every op records its recipe.
"""
from __future__ import annotations

from PIL import Image


class FrozenRegistration:
    def __init__(self, *, uniform_scale: float, translation: tuple[float, float],
                 source_crop: tuple[int, int, int, int] | None = None,
                 sampling: str = "nearest", subpixel_allowed: bool = False):
        if uniform_scale <= 0:
            raise ValueError("uniform_scale must be positive")
        tx, ty = translation
        if not subpixel_allowed and (float(tx) != int(tx) or float(ty) != int(ty)):
            raise ValueError("integer translation required unless subpixel explicitly allowed")
        if sampling not in ("nearest", "bilinear", "bicubic"):
            raise ValueError(f"unknown sampling {sampling}")
        self.uniform_scale = uniform_scale
        self.translation = translation
        self.source_crop = source_crop
        self.sampling = sampling
        self.subpixel_allowed = subpixel_allowed

    def recipe(self) -> str:
        return (f"crop={self.source_crop};scale={self.uniform_scale};"
                f"translate={self.translation};sampling={self.sampling}")


_RESAMPLE = {"nearest": Image.NEAREST, "bilinear": Image.BILINEAR, "bicubic": Image.BICUBIC}


def register_onto_canvas(img: Image.Image, reg: FrozenRegistration,
                         canvas: tuple[int, int]) -> Image.Image:
    """Place source onto the frozen native canvas. Never refits per pose."""
    if reg.source_crop is not None:
        l, t, r, b = reg.source_crop
        img = img.crop((l, t, r, b))
    if reg.uniform_scale != 1.0:
        nw = max(1, round(img.size[0] * reg.uniform_scale))
        nh = max(1, round(img.size[1] * reg.uniform_scale))
        img = img.resize((nw, nh), _RESAMPLE[reg.sampling])
    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    tx, ty = reg.translation
    out.alpha_composite(img.convert("RGBA"), (int(round(tx)), int(round(ty))))
    return out
