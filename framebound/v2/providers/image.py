"""Muse Image adapter: reference-conditioned generation. References reach the model.

Wire: POST {BASE}/responses, model muse-image-1.0, input messages with
`input_text` + `input_image` (`image_url` data:/https: or `file_id`).
Role explanations travel as text; approved pixels travel as images.
No `endpoint`/`note`/`image_b64`/`asset_id` keys ever leave this process.
Without credentials (or with offline=True) the adapter returns not_configured
with the exact request it WOULD send, and fabricates nothing.
"""
from __future__ import annotations

import json
import os

from ..services.errors import InvalidInput, ResponseInvalid
from . import wire as W

MODEL_ENV = "FRAMEBOUND_IMAGE_MODEL"
DEFAULT_MODEL = "muse-image-1.0"


def _model() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


def build_request(brief: dict, reference_blobs: list[dict],
                  *, previous_response_id: str | None = None,
                  store: bool | None = None) -> dict:
    """Build the documented wire payload.

    reference_blobs: [{role, asset_id, mime, bytes_b64, byte_sha256}].
    Requires >=2 role-labeled references (identity + style) for a fresh turn,
    >=1 when chaining with previous_response_id.
    """
    if not isinstance(brief, dict) or not str(brief.get("instruction", "")).strip():
        raise InvalidInput("image request needs a brief with a non-empty instruction")
    blobs = reference_blobs or []
    need = 1 if previous_response_id else 2
    roles = [b.get("role") for b in blobs if isinstance(b, dict)]
    if len(blobs) < need or not ({"approved_identity", "approved_style"} <= set(roles) or previous_response_id):
        raise InvalidInput(
            "image request needs >=2 role-labeled references (identity + style); "
            "refine chains need previous_response_id plus >=1 new reference")
    for b in blobs:
        if not isinstance(b, dict) or not b.get("bytes_b64") or not b.get("byte_sha256"):
            raise InvalidInput("reference blob needs bytes_b64 + byte_sha256 from the stored asset")
        if b.get("bytes_b64", "").startswith("<"):
            raise InvalidInput("reference blob carries a redaction stub, not transmittable pixels")
    instruction = str(brief["instruction"])
    role_lines = []
    images = []
    for b in blobs:
        mime = b.get("mime") or "image/png"
        role_lines.append(
            f"Reference ({b.get('role')}, asset {b.get('asset_id')}, "
            f"sha256:{str(b.get('byte_sha256'))[:16]}): approved pixels attached as image.")
        if b.get("file_id"):
            images.append({"type": "input_image", "file_id": b["file_id"], "detail": "high"})
        else:
            images.append({"type": "input_image",
                           "image_url": W.data_url(mime, b["bytes_b64"]), "detail": "high"})
    user_text = instruction + "\n\nApproved references (do not copy verbatim; match identity/style):\n" \
        + "\n".join(f"- {l}" for l in role_lines)
    req: dict = {
        "model": _model(),
        "input": [
            {"role": "system", "content": [
                {"type": "input_text",
                 "text": "Generate one animation frame under the supplied frozen contract. "
                         "Preserve canvas, calibration, and protected regions."}]},
            {"role": "user", "content": [
                {"type": "input_text", "text": user_text},
                *images,
            ]},
        ],
    }
    if previous_response_id:
        req["previous_response_id"] = previous_response_id
    if store is not None:
        req["store"] = bool(store)
    violations = W.validate_image_request(req)
    if violations:
        raise InvalidInput("built image request fails wire validation: " + "; ".join(violations))
    return req


def build_edit_request(previous_response_id: str, change_text: str,
                       extra_blobs: list[dict] | None = None) -> dict:
    """Bounded-patch strategy: chain from the prior response; never strict inpainting.

    The server carries the prior image via previous_response_id; we send only
    the bounded change description plus any new references. We do not claim
    pixel-exact inpainting semantics the API does not document.
    """
    if not previous_response_id or not previous_response_id.strip():
        raise InvalidInput("edit chains need the prior response id")
    if not change_text or not change_text.strip():
        raise InvalidInput("edit chains need a bounded change description")
    images = []
    for b in extra_blobs or []:
        if b.get("file_id"):
            images.append({"type": "input_image", "file_id": b["file_id"], "detail": "high"})
        else:
            images.append({"type": "input_image",
                           "image_url": W.data_url(b.get("mime") or "image/png",
                                                   b["bytes_b64"]), "detail": "high"})
    req = {"model": _model(), "previous_response_id": previous_response_id,
           "input": [{"role": "user", "content": [
               {"type": "input_text",
                "text": f"Bounded patch (preserve canvas/calibration outside the named region): {change_text}"},
               *images]}]}
    violations = W.validate_image_request(req)
    if violations:
        raise InvalidInput("built edit request fails wire validation: " + "; ".join(violations))
    return req


def parse_response(body: dict) -> dict:
    """Parse + validate a generation response. Returns images/usage/ids."""
    return W.parse_image_response(body)


def _materialize(raw: bytes) -> dict:
    from PIL import Image as _Image
    import io as _io
    try:
        img = _Image.open(_io.BytesIO(raw))
        img.load()
        w, h = img.size
        mime = { "PNG": "image/png", "JPEG": "image/jpeg",
                 "WEBP": "image/webp"}.get((img.format or "").upper(), "image/png")
        has_alpha = "A" in img.getbands()
    except Exception as e:
        raise ResponseInvalid(f"response_invalid: returned bytes are not a decodable image: {e}") from e
    return {"mime": mime, "width": w, "height": h, "has_alpha": has_alpha}


def submit(brief: dict, reference_blobs: list[dict], project_dir: str,
           idempotency_key: str, *, offline: bool = False,
           transport=None, timeout: float = 120.0,
           previous_response_id: str | None = None,
           job_offline: bool = False) -> dict:
    """Queue-or-send boundary for image generation.

    `job_offline` is the persisted job restriction when sending through the
    durable controller: a persisted offline job is never transmitted, even
    when this call requests a live send. Exactly one transport dispatch per
    call; ambiguous outcomes raise instead of retrying.
    """
    # The offline restriction travels as an explicit parameter, never inside
    # the brief dict (caller descriptions confer no authority).
    req = build_request(brief, reference_blobs, previous_response_id=previous_response_id)
    return submit_resolved(brief, reference_blobs, project_dir, idempotency_key,
                           req=req, offline=offline, transport=transport,
                           timeout=timeout,
                           previous_response_id=previous_response_id,
                           job_offline=bool(job_offline))


def submit_resolved(brief: dict, reference_blobs: list[dict], project_dir: str,
                    idempotency_key: str, *, req: dict | None = None,
                    offline: bool = False, transport=None, timeout: float = 120.0,
                    previous_response_id: str | None = None,
                    job_offline: bool = False, permit=None) -> dict:
    """Send pre-resolved references with exactly one dispatch.

    The persisted offline restriction is enforced at this lowest shared send
    boundary: job_offline=True refuses transmission regardless of the caller's
    offline flag.
    """
    from .base import _key, http_post
    from .ledger import record_artifact
    req = req if req is not None else build_request(
        brief, reference_blobs, previous_response_id=previous_response_id)
    redacted = W.redact_wire(req)
    if offline or not _key():
        digest = record_artifact(project_dir, "image_request",
                                 {"idempotency_key": idempotency_key, "request": redacted,
                                  "sent": False, "offline": bool(offline),
                                  "model": req["model"]},
                                 provider="image", model=req["model"])
        note = ("Offline mode: no request sent even though a key may be configured."
                if offline else
                "Set MODEL_API_KEY to send. No output fabricated; replay labels stay distinct from live.")
        return {"mode": "not_configured", "sent": False, "capability": "image-generation",
                "request_artifact": digest, "offline": bool(offline), "note": note,
                "origin": "not_configured",
                "wire_model": req["model"],
                "wire_image_parts": sum(1 for m in req["input"] for c in m["content"]
                                        if c.get("type") == "input_image")}
    if job_offline:
        raise InvalidInput("persisted offline restriction: transmission refused; "
                           "authorize an explicit live job instead")
    payload = req
    origin = "simulated-transport" if transport is not None else "live"
    req_digest = record_artifact(project_dir, "image_request",
                                 {"idempotency_key": idempotency_key, "request": redacted,
                                  "sent": True, "model": req["model"], "origin": origin},
                                 provider="image", model=req["model"])
    # Exactly one dispatch: a generation POST is not provably idempotent, so
    # an ambiguous outcome must surface as unknown (reconcile before another
    # spend), never as silent retries. Only explicit provider refusals
    # (permission/model/rate-limit/validation) propagate as typed errors.
    body = http_post(W.RESPONSE_PATH, payload, timeout=timeout,
                     idempotency_key=idempotency_key, transport=transport, permit=permit)
    parsed = parse_response(body)
    first = parsed["images"][0]
    meta = _materialize(first["bytes"])
    import hashlib as _h
    from .. import storage as S
    blob_digest = S.store_blob(project_dir, first["bytes"])
    digest = record_artifact(project_dir, "image_response",
                             {"idempotency_key": idempotency_key,
                              "request_artifact": req_digest,
                              "request": redacted, "sent": True,
                              "origin": origin,
                              "model": req["model"],
                              "response_id": parsed["response_id"],
                              "usage": parsed["usage"],
                              "output_bytes_sha256": _h.sha256(first["bytes"]).hexdigest(),
                              "output_blob": blob_digest,
                              "output_mime": meta["mime"], "output_size": [meta["width"], meta["height"]],
                              "output_has_alpha": meta["has_alpha"],
                              "image_items": len(parsed["images"])},
                             provider="image", model=req["model"],
                             request_id=str(parsed["response_id"] or ""))
    return {"mode": "live", "sent": True, "request_artifact": req_digest,
            "response_artifact": digest, "origin": origin,
            "response_id": parsed["response_id"], "usage": parsed["usage"],
            "output_blob": blob_digest, "output_mime": meta["mime"],
            "output_size": [meta["width"], meta["height"]],
            "output_bytes": first["bytes"], "image_count": len(parsed["images"])}
