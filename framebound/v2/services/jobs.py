"""Durable generation jobs: idempotent submit, server-resolved references, no silent reuse."""
from __future__ import annotations

import base64
import hashlib
import json

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput


def _payload_hash(brief: dict, resolved_refs: list[dict]) -> str:
    """Complete request fingerprint: full brief plus sorted reference digests."""
    refs = sorted((r.get("asset_id", ""), r.get("byte_sha256", "")) for r in resolved_refs)
    return hashlib.sha256(json.dumps({"brief": brief, "references": refs},
                                      sort_keys=True).encode()).hexdigest()


def _resolve_references(project_dir: str, brief: dict,
                        caller_blobs: list[dict]) -> list[dict]:
    """Bind reference bytes server-side from the blob store, hash-verified.

    The brief carries role/asset_id/byte_sha256 from stored authority; pixels
    always come from the local store, never from caller-supplied bytes alone.
    Caller blobs are cross-checked when present and rejected on mismatch.
    """
    inputs = brief.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise InvalidInput("brief has no reference inputs: compile it from stored approval first")
    by_asset = {b.get("asset_id"): b for b in caller_blobs if isinstance(b, dict)}
    con = S.connect(project_dir)
    try:
        resolved = []
        for item in inputs:
            aid = item.get("asset_id")
            if not aid:
                continue  # phase_authority entries carry no pixels here
            try:
                adata, _ = S.get(con, "assets", aid)
            except KeyError:
                raise InvalidInput(f"missing_input: brief reference asset {aid} not stored")
            raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != item.get("byte_sha256") or digest != adata["byte_sha256"]:
                raise InvalidInput(f"brief reference {aid}: hash drift since approval")
            entry = {"role": item.get("role", "reference"), "asset_id": aid,
                     "byte_sha256": digest,
                     "bytes_b64": base64.b64encode(raw).decode()}
            if aid in by_asset:
                claimed = by_asset[aid]
                if claimed.get("byte_sha256") and claimed["byte_sha256"] != digest:
                    raise InvalidInput(f"caller blob for {aid} does not match stored bytes")
                if claimed.get("bytes_b64"):
                    try:
                        if hashlib.sha256(base64.b64decode(claimed["bytes_b64"])).hexdigest() != digest:
                            raise InvalidInput(f"caller bytes for {aid} do not match stored bytes")
                    except InvalidInput:
                        raise
                    except Exception:
                        raise InvalidInput(f"caller bytes for {aid} are not valid base64")
            resolved.append(entry)
        if not resolved:
            raise InvalidInput("brief resolved to zero reference assets")
        return resolved
    finally:
        con.close()


def submit_generation(project_dir: str, brief: dict, reference_blobs: list[dict],
                      idempotency_key: str) -> D.ResultEnvelope:
    from ..providers import image as img
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise InvalidInput("idempotency_key is required")
    resolved = _resolve_references(project_dir, brief, reference_blobs or [])
    con = S.connect(project_dir)
    try:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]
        job = D.Job(id=f"job-{digest}",
                     kind="generation", idempotency_key=idempotency_key,
                     payload_sha256=_payload_hash(brief, resolved))
        job, created = S.create_job_idempotent(con, job)
        if not created:
            return D.ResultEnvelope(ok=True, operation_id=f"op-{job.id}", revision_id=None,
                                     next_actions=["job_get"],
                                     artifacts=[{"id": job.id, "role": "job", "deduped": True}])
        res = img.submit(brief, resolved, project_dir, idempotency_key)
        job.status = D.JobStatus.NEEDS_ATTENTION if res["mode"] == "not_configured" else D.JobStatus.RUNNING
        job.lease_holder = None
        S.update_mutable(con, "jobs", job, expected_version=1)
        action = "provider_configure" if res["mode"] == "not_configured" else "job_get"
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-{job.id}",
                            issues=[] if res["sent"] else [{"code": "not_configured",
                                    "scope": "image-generation", "reason": res["note"]}],
                            artifacts=[{"id": job.id, "role": "job"},
                                       {"id": res.get("request_artifact", ""), "role": "request_artifact"}],
                            next_actions=[action])


def job_get(project_dir: str, job_id: str) -> dict:
    con = S.connect(project_dir)
    try:
        data, ver = S.get(con, "jobs", job_id)
    finally:
        con.close()
    return {"job": data, "version": ver}


def job_cancel(project_dir: str, job_id: str, expected_version: int) -> dict:
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
        job = D.Job.model_validate_json(json.dumps(data))
        job.status = D.JobStatus.CANCELLED
        nv = S.update_mutable(con, "jobs", job, expected_version)
    finally:
        con.close()
    return {"job_id": job_id, "status": "cancelled", "version": nv}
