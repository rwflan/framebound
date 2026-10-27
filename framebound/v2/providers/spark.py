"""Muse Spark adapter: structured tool loop + advisory critique. Critique never gates."""
from __future__ import annotations

import json
import os
import urllib.request

BASE = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.environ.get("FRAMEBOUND_VISION_MODEL", "muse-spark-1.3")


def critique_request(contract_summary: str, fault_codes: list[str], frame_refs: list[dict]) -> dict:
    return {
        "model": MODEL, "endpoint": "POST /responses (structured output, validated server-side)",
        "input": [
            {"role": "system", "content": "Review animation frames against the frozen contract. "
             "Name visible inconsistencies with frame/time ids, uncertainty, and evidence refs. "
             "Do not approve art; a technical pass is not acceptance."},
            {"role": "user", "content": [
                {"type": "text", "text": f"Contract: {contract_summary}\nDeterministic findings: {fault_codes}"},
                *[{"type": "input_image", "frame": f["slot"], "asset_id": f["asset_id"]} for f in frame_refs],
            ]},
        ],
    }


def submit_critique(contract_summary: str, fault_codes: list[str], frame_refs: list[dict],
                    project_dir: str) -> dict:
    from .base import _key
    from .ledger import record_artifact
    req = critique_request(contract_summary, fault_codes, frame_refs)
    if not _key():
        digest = record_artifact(project_dir, "spark_request", {"request": req, "sent": False})
        return {"mode": "not_configured", "sent": False, "request_artifact": digest,
                "note": "Advisory only; deterministic checks remain the gate."}
    http = urllib.request.Request(BASE.rstrip("/") + "/responses", data=json.dumps(req).encode(),
                                  headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(http, timeout=120) as resp:
        body = json.loads(resp.read().decode())
    digest = record_artifact(project_dir, "spark_response", {"request": req, "response": body, "sent": True})
    return {"mode": "live", "sent": True, "response_artifact": digest, "response": body}
