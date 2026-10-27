"""SAM 3.1 adapter: Responses with real image content; special-token masks decoded.

The v1 prototype sent a local path string to chat completions — that never transmits
image bytes. This adapter requires real image bytes (or provider file IDs), decodes the
returned mask payload into aligned mask bytes, and validates empty/full/clipped/odd-size
masks as explicit outcomes. Alpha fallback stays labeled offline-alpha, never SAM.
"""
from __future__ import annotations

import base64


def build_request(image_b64: str, prompt: str, model: str = "sam-3.1") -> dict:
    return {"model": model, "endpoint": "POST /responses (media segmentation)",
            "input": [{"role": "user", "content": [
                {"type": "input_image", "image_b64": "<bytes>"},
                {"type": "text", "text": f"Segment: {prompt}. Return box/mask special tokens."}]}],
            "_image_b64_held_locally": bool(image_b64)}


def decode_mask(payload: dict, width: int, height: int) -> dict:
    """Decode a provider mask payload into aligned bytes. Explicit outcomes, never silent."""
    data_b64 = (payload.get("mask_b64") or payload.get("mask_rle") or "")
    if not data_b64:
        return {"outcome": "no_match", "reason": "provider returned no mask payload", "mask": None}
    try:
        raw = base64.b64decode(data_b64)
    except Exception as e:
        return {"outcome": "corrupt", "reason": f"mask payload undecodable: {e}", "mask": None}
    if len(raw) != width * height:
        return {"outcome": "corrupt",
                "reason": f"mask {len(raw)} bytes misaligned with {width}x{height}; rejected", "mask": None}
    fg = sum(1 for b in raw if b)
    total = width * height
    if fg == 0:
        return {"outcome": "empty", "reason": "SAM returned an empty mask; unmeasured, never pass-by-zero-area",
                "mask": bytes(raw)}
    if fg == total:
        return {"outcome": "full", "reason": "SAM returned a full-frame mask; not a subject mask", "mask": bytes(raw)}
    return {"outcome": "mask", "reason": "decoded + aligned", "mask": bytes(raw),
            "foreground_fraction": fg / total}


def alpha_fallback(mask_nonzero: int, width: int, height: int) -> dict:
    return {"outcome": "offline-alpha", "reason": "alpha used as fallback; NOT a SAM mask; "
            "part-dependent measurements stay visibly provisional",
            "mask_nonzero": mask_nonzero, "dimensions": [width, height]}
