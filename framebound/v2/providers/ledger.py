"""Provider ledger: versioned, redacted request/response artifacts; costs recorded, estimates marked."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import storage as S

SCHEMA_VERSION = "2.0"


def _redact_for_store(payload: dict) -> dict:
    from . import wire as W
    red = W.redact_wire(payload)
    # Defense in depth: scrub any stray secret-looking keys at any depth.
    def _scrub(o):
        if isinstance(o, dict):
            return {k: ("<secret-redacted>" if k.lower() in
                         ("authorization", "api_key", "model_api_key", "bearer")
                         else _scrub(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [_scrub(i) for i in o]
        return o
    return _scrub(red)


def record_artifact(project_dir: str | Path, kind: str, payload: dict, *,
                    provider: str = "", model: str = "",
                    request_id: str = "") -> str:
    envelope = {"schema_version": SCHEMA_VERSION, "kind": kind,
                "provider": provider, "model": model,
                "request_id": request_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "payload": _redact_for_store(payload)}
    raw = json.dumps(envelope, sort_keys=True).encode()
    return S.store_blob(project_dir, raw)


def load_artifact(project_dir: str | Path, digest: str) -> dict:
    return json.loads(S.blob_path(project_dir, digest).read_bytes().decode())


def attempt_fingerprint(provider: str, conditioning_sha256: str, target_ids: list[str],
                        candidate_hashes: list[str], metrics: dict) -> str:
    return hashlib.sha256(json.dumps({
        "provider": provider, "conditioning": conditioning_sha256, "targets": sorted(target_ids),
        "candidates": sorted(candidate_hashes), "metrics": metrics}, sort_keys=True).encode()).hexdigest()
