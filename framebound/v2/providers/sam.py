"""SAM 3.1 adapter: Responses with real image content; special-token masks decoded.

Wire: POST {BASE}/responses, model sam-3.1, one user message with `input_text`
concept + `input_image` (data URL/file_id). The result streams in the
`output_text` lane as special-token text (`<Nf>obj<|box;...|><|mask;...|>`,
mask payload base85, `~` lossless / `!` one-bit). Empty lane + completed =
valid no-match. Raw base64 pixels, COCO RLE, PNG bytes and SAM tokens are
different formats with different parsers; this module never confuses them.

`decode_mask` below is kept as an explicit raw-byte helper for offline unit
fixtures (never a SAM parser); live SAM output always goes through
`parse_output_text`.
"""
from __future__ import annotations

import base64
import os

from ..services.errors import InvalidInput
from . import wire as W

MODEL = "sam-3.1"


def build_request(image_b64: str, prompt: str, *, mime: str = "image/png",
                  file_id: str | None = None, stream: bool = True,
                  include_confidence: bool = False) -> dict:
    """Build the documented wire payload. image_b64 must be real pixels."""
    if not prompt or not prompt.strip():
        raise InvalidInput("SAM needs a short noun-phrase concept prompt")
    if len(prompt.strip()) > 160:
        raise InvalidInput("SAM concept prompt should be a short noun phrase "
                           f"(got {len(prompt.strip())} chars)")
    if file_id:
        media = {"type": "input_image", "file_id": file_id, "detail": "high"}
    else:
        if not image_b64 or not isinstance(image_b64, str):
            raise InvalidInput("SAM needs real image bytes (base64), not a path or placeholder")
        if image_b64.startswith("<"):
            raise InvalidInput("SAM image is a placeholder stub, never transmittable pixels")
        try:
            raw = base64.b64decode(image_b64, validate=True)
        except Exception as e:
            raise InvalidInput(f"SAM image_b64 is not valid base64: {e}") from e
        if not raw:
            raise InvalidInput("SAM image bytes are empty")
        media = {"type": "input_image",
                 "image_url": W.data_url(mime, image_b64), "detail": "high"}
    req: dict = {
        "model": os.environ.get("FRAMEBOUND_SAM_MODEL") or MODEL,
        "stream": bool(stream),
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": prompt.strip()},
            media,
        ]}],
    }
    if include_confidence:
        # Provisional request flag: servers that honor it attach `c=` to box/mask
        # tokens; the parser accepts both forms, so absence stays fail-closed.
        req["include_confidence"] = True
    violations = W.validate_sam_request(req)
    if violations:
        raise InvalidInput("built SAM request fails wire validation: " + "; ".join(violations))
    return req


def parse_output_text(text: str, *, source_width: int | None = None,
                      source_height: int | None = None) -> dict:
    """Parse SAM special-token output_text into records. See wire module."""
    return W.parse_sam_output_text(text, source_width=source_width,
                                   source_height=source_height)


def decode_png_mask(payload_b64: str, width: int, height: int) -> dict:
    """Decode a base64 PNG mask payload into aligned bytes (explicit PNG path)."""
    try:
        raw = base64.b64decode(payload_b64, validate=True)
    except Exception as e:
        return {"outcome": "corrupt", "reason": f"PNG mask payload undecodable: {e}", "mask": None}
    try:
        from PIL import Image as _Image
        import io as _io
        img = _Image.open(_io.BytesIO(raw)).convert("L")
        if img.size != (width, height):
            return {"outcome": "corrupt",
                    "reason": f"PNG mask {img.size[0]}x{img.size[1]} misaligned with {width}x{height}",
                    "mask": None}
        px = img.tobytes()
        fg = sum(1 for b in px if b > 127)
        raster = bytes(1 if b > 127 else 0 for b in px)
    except Exception as e:
        return {"outcome": "corrupt", "reason": f"PNG mask undecodable: {e}", "mask": None}
    if fg == 0:
        return {"outcome": "empty", "reason": "PNG mask is all zero", "mask": raster}
    if fg == width * height:
        return {"outcome": "full", "reason": "PNG mask is full-frame", "mask": raster}
    return {"outcome": "mask", "reason": "PNG mask decoded + aligned", "mask": raster,
            "foreground_fraction": fg / (width * height)}


def decode_coco_rle(rle: dict, width: int, height: int) -> dict:
    """Decode a COCO RLE ({size:[h,w], counts}) into a row-major 0/1 raster."""
    try:
        from pycocotools import mask as _mask
        import numpy as _np
        if not isinstance(rle, dict) or rle.get("size") != [height, width]:
            return {"outcome": "corrupt",
                    "reason": f"COCO RLE size {rle.get('size') if isinstance(rle, dict) else rle!r} "
                              f"disagrees with {height}x{width}", "mask": None}
        decoded = _mask.decode(rle)
        if _np is not None and hasattr(decoded, "shape"):
            arr = _np.asarray(decoded)
            if arr.shape != (height, width):
                return {"outcome": "corrupt",
                        "reason": f"COCO RLE decoded to {arr.shape}, expected {(height, width)}",
                        "mask": None}
            flat = bytes(int(v) for v in arr.ravel().tolist())
        else:
            flat = bytes(decoded)
            if len(flat) != width * height:
                return {"outcome": "corrupt",
                        "reason": f"COCO RLE decoded {len(flat)} bytes, expected {width*height}",
                        "mask": None}
    except ImportError:
        return {"outcome": "corrupt",
                "reason": "pycocotools unavailable: cannot validate COCO RLE offline", "mask": None}
    except Exception as e:
        return {"outcome": "corrupt", "reason": f"COCO RLE undecodable: {e}", "mask": None}
    fg = sum(1 for b in flat if b)
    if fg == 0:
        return {"outcome": "empty", "reason": "COCO RLE is all zero", "mask": flat}
    if fg == width * height:
        return {"outcome": "full", "reason": "COCO RLE is full-frame", "mask": flat}
    return {"outcome": "mask", "reason": "COCO RLE decoded", "mask": flat,
            "foreground_fraction": fg / (width * height)}


def decode_mask(payload: dict, width: int, height: int) -> dict:
    """Legacy raw-byte helper for offline fixtures (NOT a SAM parser).

    Accepts {"mask_b64": base64-of-raw-bytes} test fixtures and reports
    empty/full/corrupt/mask outcomes. Live SAM special-token output must use
    `parse_output_text`; COCO RLE must use `decode_coco_rle`; PNG must use
    `decode_png_mask`. A dict carrying "mask_rle" raw pixels is rejected as an
    ambiguous legacy encoding.
    """
    if not isinstance(payload, dict):
        return {"outcome": "corrupt", "reason": "mask payload must be an object", "mask": None}
    if "mask_rle" in payload:
        return {"outcome": "corrupt",
                "reason": "mask_rle raw pixels are ambiguous: use decode_coco_rle for COCO RLE "
                          "or parse_output_text for SAM tokens", "mask": None}
    data_b64 = payload.get("mask_b64", "")
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
        return {"outcome": "empty", "reason": "mask is all zero; unmeasured, never pass-by-zero-area",
                "mask": bytes(raw)}
    if fg == total:
        return {"outcome": "full", "reason": "full-frame mask; not a subject mask", "mask": bytes(raw)}
    return {"outcome": "mask", "reason": "decoded + aligned", "mask": bytes(raw),
            "foreground_fraction": fg / total}


def alpha_fallback(mask_nonzero: int, width: int, height: int) -> dict:
    return {"outcome": "offline-alpha", "reason": "alpha used as fallback; NOT a SAM mask; "
            "part-dependent measurements stay visibly provisional",
            "mask_nonzero": mask_nonzero, "dimensions": [width, height]}


def submit(image_b64: str, prompt: str, project_dir: str, *, mime: str = "image/png",
           file_id: str | None = None, offline: bool = False, transport=None,
           timeout: float = 120.0, source_width: int | None = None,
           source_height: int | None = None) -> dict:
    """Submit a live SAM request and parse the special-token lane."""
    from .base import _key, http_post, retry_transient
    from .ledger import record_artifact
    req = build_request(image_b64, prompt, mime=mime, file_id=file_id, stream=False)
    redacted = W.redact_wire(req)
    if offline or not _key():
        digest = record_artifact(project_dir, "sam_request",
                                 {"request": redacted, "sent": False,
                                  "offline": bool(offline), "model": req["model"]},
                                 provider="sam", model=req["model"])
        return {"mode": "not_configured", "sent": False, "request_artifact": digest,
                "note": "Set MODEL_API_KEY to send; alpha stays labeled offline-alpha, never SAM."}
    def _send():
        return http_post(W.RESPONSE_PATH, req, timeout=timeout, transport=transport)
    body, _tries = retry_transient(_send)
    # Non-streaming: output_text lane; streaming SSE bodies carry events — both
    # funnel into one text lane before parsing.
    if isinstance(body, dict) and "events" in body:
        text = "".join(e.get("delta", "") for e in body["events"]
                       if isinstance(e, dict) and e.get("type") == "response.output_text.delta")
        response_id = body.get("id")
    else:
        text = ""
        if isinstance(body, dict):
            for o in body.get("output", []) or []:
                if isinstance(o, dict) and o.get("type") in ("message", "output_text"):
                    c = o.get("content", [])
                    if isinstance(c, list):
                        for p in c:
                            if isinstance(p, dict) and p.get("type") in ("output_text", "text"):
                                text += p.get("text", "")
                    elif isinstance(c, str):
                        text += c
        response_id = body.get("id") if isinstance(body, dict) else None
    parsed = parse_output_text(text, source_width=source_width, source_height=source_height)
    digest = record_artifact(project_dir, "sam_response",
                             {"request": redacted, "sent": True, "model": req["model"],
                              "response_id": response_id,
                              "outcome": parsed["outcome"], "reason": parsed.get("reason"),
                              "record_count": len(parsed.get("records", []))},
                             provider="sam", model=req["model"],
                             request_id=str(response_id or ""))
    out = {"mode": "live", "sent": True, "response_artifact": digest,
           "response_id": response_id, **parsed}
    # Strip rasters from the returned envelope? No — callers need geometry, but
    # rasters are bytes; expose foreground counts + boxes, keep rasters under "records".
    return out
