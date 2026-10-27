from __future__ import annotations

import hashlib
import json

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def submit_generation(project_dir: str, brief: dict, reference_blobs: list[dict],
                      idempotency_key: str) -> D.ResultEnvelope:
    from ..providers import image as img
    con = S.connect(project_dir)
    try:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]
        job = D.Job(id=f"job-{digest}",
                     kind="generation", idempotency_key=idempotency_key,
                     payload_sha256=_payload_hash({"brief": brief.get("conditioning_sha256")}))
        job, created = S.create_job_idempotent(con, job)
        if not created:
            return D.ResultEnvelope(ok=True, operation_id=f"op-{job.id}", revision_id=None,
                                     next_actions=["job_get"],
                                     artifacts=[{"id": job.id, "role": "job", "deduped": True}])
        res = img.submit(brief, reference_blobs, project_dir, idempotency_key)
        job.status = D.JobStatus.NEEDS_ATTENTION if res["mode"] == "not_configured" else D.JobStatus.RUNNING
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
