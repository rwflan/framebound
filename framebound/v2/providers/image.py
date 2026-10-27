"""Muse Image adapter: reference-conditioned generation. References reach the model.

P0 uses the documented reference-conditioned Responses flow: actual approved reference
pixels (or provider file IDs) travel with role labels — never local path strings.
Without credentials the adapter returns not_configured with the exact request it WOULD
send, and fabricates nothing.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

from ..services.errors import InvalidInput, Unsupported

BASE = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.environ.get("FRAMEBOUND_IMAGE_MODEL", "muse-image-1.0")


def build_request(brief: dict, reference_blobs: list[dict]) -> dict:
    """reference_blobs: [{role, asset_id, mime, bytes_b64, byte_sha256}]."""
    if not reference_blobs or len([r for r in reference_blobs if r.get("role") in (
            "approved_identity", "approved_style")]) < 2:
        raise InvalidInput("image request needs ≥2 role-labeled references (identity + style)")
    return {
        "model": MODEL, "endpoint": "POST /responses (reference-conditioned)",
        "input": [
            {"role": "system", "content": "Generate one animation frame under the supplied frozen contract."},
            {"role": "user", "content": [
                {"type": "text", "text": brief["instruction"]},
                *[{"type": "input_image", "role": r["role"], "asset_id": r["asset_id"],
                    "byte_sha256": r["byte_sha256"], "image_b64": "<redacted>" if r.get("redact") else r["bytes_b64"]}
                  for r in reference_blobs],
            ]},
        ],
        "note": "size controls aspect ratio, never guaranteed exact pixels; persist + register actual outputs",
    }


def submit(brief: dict, reference_blobs: list[dict], project_dir: str,
           idempotency_key: str) -> dict:
    from .base import _key
    from .ledger import record_artifact
    req = build_request(brief, reference_blobs)
    if not _key():
        redacted = json.loads(json.dumps(req).replace(
            next((r["bytes_b64"] for r in reference_blobs if r.get("bytes_b64")), ""), "<bytes>"))
        digest = record_artifact(project_dir, "image_request",
                                 {"idempotency_key": idempotency_key, "request": redacted, "sent": False})
        return {"mode": "not_configured", "sent": False, "capability": "image-generation",
                "request_artifact": digest,
                "note": "Set MODEL_API_KEY to send. No output fabricated; replay labels stay distinct from live."}
    payload = dict(req)
    http = urllib.request.Request(BASE.rstrip("/") + "/responses", data=json.dumps(payload).encode(),
                                  headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(http, timeout=120) as resp:
        body = json.loads(resp.read().decode())
    digest = record_artifact(project_dir, "image_response", {"request": req, "response": body, "sent": True})
    return {"mode": "live", "sent": True, "response_artifact": digest, "response": body}
