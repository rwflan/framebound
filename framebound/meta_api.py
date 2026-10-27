"""Meta Model API adapters: Muse Spark / Wonder, Muse Image, SAM 3.1.

Configuration (environment):
  MODEL_API_KEY (or META_API_KEY)   API key. Without it, adapters run
                                     offline: they return the exact request
                                     they would send and never fake output.
  META_BASE_URL                      Default https://api.meta.ai/v1
  FRAMEBOUND_VISION_MODEL            Default muse-spark-1.3
  FRAMEBOUND_IMAGE_MODEL             Default muse-image-1.0
  FRAMEBOUND_SEGMENT_MODEL           Default sam-3.1

Roles in the loop: Muse Image generates under a compiled brief; SAM 3.1
supplies instance masks for shape measurement; Muse Spark / Wonder act
as the orchestrator and as a second, visual critic. Deterministic raster
checks remain the gate: a model opinion never overrides a failed bound.
"""
import base64
import json
import os
import urllib.request
from pathlib import Path

BASE = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")
KEY = os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
VISION = os.environ.get("FRAMEBOUND_VISION_MODEL", "muse-spark-1.3")
IMAGE = os.environ.get("FRAMEBOUND_IMAGE_MODEL", "muse-image-1.0")
SEGMENT = os.environ.get("FRAMEBOUND_SEGMENT_MODEL", "sam-3.1")


def _post(path, payload):
    req = urllib.request.Request(
        BASE.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _img_part(path):
    mime = "image/png"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def vision_critique(image_paths, contract_summary, fault_codes):
    """Ask the vision model to describe faults. Advisory only, never a gate."""
    payload = {"model": VISION, "messages": [
        {"role": "system", "content": "You review 2D animation frames against a frozen character contract. Name visible shape, size, movement, or appearance inconsistencies per frame. Do not approve art."},
        {"role": "user", "content": [
            {"type": "text", "text": f"Contract: {contract_summary}\nDeterministic checks already found: {fault_codes}\nDescribe any additional visible inconsistency, frame by frame."},
            *[_img_part(p) for p in image_paths]]}]}
    if not KEY:
        return {"mode": "offline", "sent": False, "request": payload,
                "note": "Set MODEL_API_KEY to send. No output was fabricated."}
    return {"mode": "live", "sent": True, "response": _post("/chat/completions", payload)}


def generate_image(brief_path, out_path):
    """Generate one frame under a compiled brief via Muse Image."""
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    payload = {"model": IMAGE, "prompt": brief["instruction"], "size": "1024x1024"}
    if not KEY:
        return {"mode": "offline", "sent": False, "request": payload,
                "note": "Set MODEL_API_KEY to send. Preflight any returned image before use."}
    resp = _post("/images/generations", payload)
    return {"mode": "live", "sent": True, "response": resp,
            "note": f"Save the returned image to {out_path} and run candidate preflight."}


def segment(image_path, prompt):
    """SAM 3.1 mask for a named part. Offline fallback: alpha mask of the PNG."""
    payload = {"model": SEGMENT, "image": str(image_path), "prompt": prompt}
    if not KEY:
        from .pngcodec import read_png
        w, h, data = read_png(image_path)
        mask = bytes(255 if data[i + 3] >= 128 else 0 for i in range(0, len(data), 4))
        return {"mode": "offline-alpha", "sent": False, "request": payload,
                "width": w, "height": h, "mask_nonzero": sum(1 for v in mask if v),
                "note": "Alpha fallback used. Set MODEL_API_KEY for SAM 3.1 masks."}
    return {"mode": "live", "sent": True, "response": _post("/chat/completions", payload)}
