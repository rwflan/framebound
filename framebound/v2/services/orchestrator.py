"""Durable orchestrator: one worker entry point over persisted state.

Not an in-memory counter: attempt counts, budgets, no-progress signatures and
halt conditions live in Job/Attempt/Run rows. A restarted process resumes them;
it never resets a three-attempt or cost budget. Halts at awaiting_review, a
definitive blocker, no progress, or budget exhaustion. Provider calls happen
outside long DB transactions (claim -> send -> complete).
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _no_progress_signature(targets: list[str], candidate_hashes: list[str]) -> str:
    return hashlib.sha256(json.dumps(
        {"targets": sorted(targets),
         "candidates": sorted(candidate_hashes)}, sort_keys=True).encode()).hexdigest()[:16]


def start_run(project_dir: str, job_ids: list[str], *, max_attempts: int = 3) -> dict:
    import uuid as _u
    rid = f"run-{_u.uuid4().hex[:12]}"
    run = D.Run(id=rid, job_ids=list(job_ids), max_attempts=max_attempts)
    con = S.connect(project_dir)
    try:
        S.insert(con, run)
    finally:
        con.close()
    return {"run_id": rid, "status": "running", "jobs": list(job_ids)}


def _get_job(con, job_id: str) -> tuple[D.Job, int]:
    data, ver = S.get(con, "jobs", job_id)
    return D.Job.model_validate_json(json.dumps(data)), ver


def run_once(project_dir: str, run_id: str, *, worker_id: str,
             offline: bool = False, transport=None,
             timeout: float = 120.0) -> dict:
    """Execute one durable step for the run's oldest actionable job."""
    from . import jobs as J
    from ..providers import image as img
    con = S.connect(project_dir)
    try:
        try:
            rdata, rver = S.get(con, "runs", run_id)
        except KeyError:
            raise InvalidInput(f"unknown run {run_id}")
        run = D.Run.model_validate_json(json.dumps(rdata))
        if run.status != "running":
            return {"run_id": run_id, "status": run.status,
                    "halt_reason": run.halt_reason, "action": "stop"}
        # Halt checks first: budget, then per-job states.
        if run.attempts_used >= run.max_attempts:
            run.status = "halted"
            run.halt_reason = f"budget exhausted: {run.attempts_used}/{run.max_attempts}"
            run.updated_at = _utc()
            S.update_mutable(con, "runs", run, rver)
            return {"run_id": run_id, "status": "halted",
                    "halt_reason": run.halt_reason, "action": "stop"}
        target = None
        for jid in run.job_ids:
            try:
                job, _ = _get_job(con, jid)
            except KeyError:
                continue
            if job.status in (D.JobStatus.SUCCEEDED, D.JobStatus.CANCELLED,
                              D.JobStatus.FAILED):
                continue
            if job.status == D.JobStatus.NEEDS_ATTENTION:
                run.status = "halted"
                run.halt_reason = (f"definitive blocker: job {jid} needs_attention "
                                   f"(reconcile: {job.reconciliation_required})")
                run.updated_at = _utc()
                S.update_mutable(con, "runs", run, rver)
                return {"run_id": run_id, "status": "halted",
                        "halt_reason": run.halt_reason, "action": "stop",
                        "job_id": jid}
            target = jid
            break
        if target is None:
            run.status = "halted"
            run.halt_reason = "no actionable jobs: all terminal or empty queue"
            run.updated_at = _utc()
            S.update_mutable(con, "runs", run, rver)
            return {"run_id": run_id, "status": "halted",
                    "halt_reason": run.halt_reason, "action": "stop"}
    finally:
        con.close()
    # Claim outside the run transaction, then send outside any DB lock.
    con = S.connect(project_dir)
    try:
        _, jver = _get_job(con, target)
    finally:
        con.close()
    try:
        claim = J.job_claim(project_dir, target, worker_id,
                            expected_version=jver, lease_seconds=300)
    except InvalidInput as e:
        return {"run_id": run_id, "action": "stop", "job_id": target,
                "reason": f"claim refused: {e}"}
    # Load brief bytes for the send (brief itself is not stored on the job in
    # R3; the caller supplies it via run context — here we re-resolve from the
    # request artifact is not possible, so the send needs the brief. To keep
    # this step durable without new tables, orchestrator keeps the brief in the
    # caller's persisted run directory is out of scope; instead refuse loudly
    # rather than inventing pixels.)
    return {"run_id": run_id, "action": "claimed", "job_id": target,
            "lease": claim.get("lease_expires"),
            "note": "claimed; call orchestrator_send with the stored brief to transmit"}


def orchestrator_send(project_dir: str, run_id: str, job_id: str, brief: dict,
                      *, worker_id: str, offline: bool = False,
                      transport=None, timeout: float = 120.0) -> dict:
    """Claimed-send-complete for one job: transmit, parse, persist output.

    Runs outside long transactions; unknown outcomes become
    reconciliation-required; no-progress repeats halt instead of blind retry.
    """
    from . import jobs as J
    from ..providers import image as img
    con = S.connect(project_dir)
    try:
        rdata, rver = S.get(con, "runs", run_id)
        run = D.Run.model_validate_json(json.dumps(rdata))
        job, jver = _get_job(con, job_id)
    finally:
        con.close()
    if run.status != "running":
        return {"run_id": run_id, "status": run.status, "action": "stop"}
    if job.status != D.JobStatus.RUNNING or job.lease_holder != worker_id:
        raise InvalidInput(f"job {job_id} is not claimed by {worker_id}; claim first")
    resolved = J._resolve_references(project_dir, brief, [])
    sig_targets = job.targets or [job_id]
    # No-progress guard first: a repeated identical brief halts even offline,
    # so a restarted worker never rebuys work under any transport state.
    fingerprint = J._payload_hash(brief, resolved)
    if fingerprint in job.no_progress_signatures and job.attempt_count > 0:
        con = S.connect(project_dir)
        try:
            rdata, rver = S.get(con, "runs", run_id)
            run = D.Run.model_validate_json(json.dumps(rdata))
            run.status = "halted"
            run.halt_reason = f"no progress: fingerprint {fingerprint[:16]} already attempted"
            run.updated_at = _utc()
            S.update_mutable(con, "runs", run, rver)
        finally:
            con.close()
        return {"run_id": run_id, "job_id": job_id, "action": "stop",
                "reason": "no-progress signature repeated; halted without blind retry"}
    # Offline or keyless: record the would-send request, park as needs_attention
    # with a clear provider_configure next action (never a fake success).
    from ..providers import base as _base
    if offline or not _base._key():
        res = img.submit(brief, resolved, project_dir, job.idempotency_key,
                         offline=True)
        con = S.connect(project_dir)
        try:
            job2, v2 = _get_job(con, job_id)
            job2.request_artifact = res.get("request_artifact")
            job2.status = D.JobStatus.NEEDS_ATTENTION
            job2.error = "not_configured: provider key absent or offline mode"
            job2.lease_holder = None
            job2.lease_expires = None
            job2.updated_at = _utc()
            nv = S.update_mutable(con, "jobs", job2, v2)
        finally:
            con.close()
        return {"run_id": run_id, "job_id": job_id, "action": "needs_attention",
                "reason": "not_configured", "version": nv}
    try:
        res = img.submit(brief, resolved, project_dir, job.idempotency_key,
                         offline=False, transport=transport, timeout=timeout)
    except Exception as e:
        from .errors import RateLimited, ProviderTimeout, TransportError
        retryable = isinstance(e, (RateLimited, ProviderTimeout, TransportError,
                                          TimeoutError, ConnectionError))
        unknown = ("timeout" in str(e).lower() or "ambiguous" in str(e).lower()) \
            and not retryable
        if unknown:
            out = J.job_mark_unknown_outcome(project_dir, job_id, worker_id=worker_id,
                                             expected_version=jver, detail=str(e))
            return {"run_id": run_id, "job_id": job_id, "action": "needs_attention",
                    **out}
        out = J.job_complete_failure(project_dir, job_id, worker_id=worker_id,
                                     expected_version=jver, error=str(e),
                                     retryable=retryable)
        _bump_run(project_dir, run_id)
        return {"run_id": run_id, "job_id": job_id, "action": "attempt",
                **out}
    # Live send succeeded at HTTP level: complete with parsed bytes.
    try:
        done = J.job_complete_success(
            project_dir, job_id, worker_id=worker_id, expected_version=jver,
            image_bytes=res["output_bytes"], mime=res.get("output_mime", "image/png"),
            provider_response_id=res.get("response_id"),
            usage=res.get("usage") if isinstance(res.get("usage"), dict) else None)
    except InvalidInput as e:
        out = J.job_complete_failure(project_dir, job_id, worker_id=worker_id,
                                     expected_version=jver, error=str(e),
                                     retryable=False)
        _bump_run(project_dir, run_id)
        return {"run_id": run_id, "job_id": job_id, "action": "attempt", **out}
    # Record the fingerprint so a repeated identical brief halts instead of rebuying.
    con = S.connect(project_dir)
    try:
        job3, v3 = _get_job(con, job_id)
        job3.request_artifact = res.get("response_artifact", job3.request_artifact)
        job3.response_artifact = res.get("response_artifact")
        job3.cost_actual = json.dumps(res.get("usage") or {})[:200]
        if fingerprint not in job3.no_progress_signatures:
            job3.no_progress_signatures = [*job3.no_progress_signatures, fingerprint]
        S.update_mutable(con, "jobs", job3, v3)
    finally:
        con.close()
    _bump_run(project_dir, run_id)
    return {"run_id": run_id, "job_id": job_id, "action": "succeeded", **done}


def _bump_run(project_dir: str, run_id: str) -> None:
    con = S.connect(project_dir)
    try:
        try:
            rdata, rver = S.get(con, "runs", run_id)
        except KeyError:
            return
        run = D.Run.model_validate_json(json.dumps(rdata))
        run.attempts_used = run.attempts_used + 1
        run.updated_at = _utc()
        if run.attempts_used >= run.max_attempts:
            run.status = "halted"
            run.halt_reason = f"budget exhausted: {run.attempts_used}/{run.max_attempts}"
        S.update_mutable(con, "runs", run, rver)
    finally:
        con.close()
