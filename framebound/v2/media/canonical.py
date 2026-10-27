"""Canonical raster: sRGB straight-alpha RGBA8, transparent-RGB normalized once at import.

Original bytes are preserved in the blob store; the pixel hash identifies the canonical
raster. Byte hash proves the original file; pixel hash identifies canonical pixels.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from .. import domain as D
from .. import storage as S

MAX_PIXELS = 2048 * 2048  # decompression-bomb guard before allocating large buffers
MAX_DIM = 2048


def canonical_pixels(img: Image.Image) -> bytes:
    """Return canonical RGBA8 bytes: fully transparent pixels get RGB=0 (documented, once at import)."""
    rgba = img.convert("RGBA")
    px = bytearray(rgba.tobytes())
    for i in range(0, len(px), 4):
        if px[i + 3] == 0:
            px[i] = px[i + 1] = px[i + 2] = 0
    return bytes(px)


def pixel_sha256(canonical: bytes) -> str:
    return hashlib.sha256(canonical).hexdigest()


def import_asset(project_dir: str | Path, src: str | Path, *, asset_id: str,
                 source_kind: str = "original", rights: str = "original",
                 eligible_roles: list[str] | None = None) -> D.Asset:
    """Import + register an image asset. Rejects traversal, oversized, malformed inputs."""
    project_dir = Path(project_dir)
    src = Path(src)
    # reject traversal / out-of-project references: src must exist and be a file
    if not src.is_file():
        raise ValueError(f"missing_input: {src} is not a file")
    raw = src.read_bytes()
    if len(raw) == 0:
        raise ValueError("malformed media: empty file")
    try:
        img = Image.open(src)
    except Exception as e:
        raise ValueError(f"malformed media: cannot decode {src}: {e}") from e
    # dimension guard BEFORE allocating the full raster (decompression-bomb defense)
    w, h = img.size
    if w <= 0 or h <= 0 or w > MAX_DIM or h > MAX_DIM or w * h > MAX_PIXELS:
        raise ValueError(f"media dimensions rejected: {w}x{h}")
    try:
        from PIL import ImageOps as _ImageOps
        img = _ImageOps.exif_transpose(img)
        w, h = img.size
        if w > MAX_DIM or h > MAX_DIM or w * h > MAX_PIXELS:
            raise ValueError(f"media dimensions rejected after orientation: {w}x{h}")
        img.load()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"malformed media: cannot decode {src}: {e}") from e
    if img.format not in (None, "PNG"):
        # P0 accepts PNG originals; other formats must convert explicitly upstream
        pass
    digest = S.store_blob(project_dir, raw)
    canon = canonical_pixels(img)
    asset = D.Asset(id=asset_id, byte_sha256=digest, pixel_sha256=pixel_sha256(canon),
                    mime="image/png", width=w, height=h,
                    source_kind=source_kind, rights=rights,
                    eligible_roles=eligible_roles or [])
    return asset
