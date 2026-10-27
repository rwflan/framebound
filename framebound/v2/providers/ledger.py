"""Provider ledger: every request/response artifact persisted, cost recorded, estimates marked."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import storage as S


def record_artifact(project_dir: str | Path, kind: str, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True).encode()
    digest = S.store_blob(project_dir, raw)
    return digest


def attempt_fingerprint(provider: str, conditioning_sha256: str, target_ids: list[str],
                        candidate_hashes: list[str], metrics: dict) -> str:
    return hashlib.sha256(json.dumps({
        "provider": provider, "conditioning": conditioning_sha256, "targets": sorted(target_ids),
        "candidates": sorted(candidate_hashes), "metrics": metrics}, sort_keys=True).encode()).hexdigest()
