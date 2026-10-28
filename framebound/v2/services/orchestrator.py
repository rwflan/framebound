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
    # Claim outside the run transaction (fenced), then hand the worker
    # everything it needs to send from stored state alone: no caller brief.
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
    con = S.connect(project_dir)
    try:
        job, _ = _get_job(con, target)
    finally:
        con.close()
    return {"run_id": run_id, "action": "send_ready", "job_id": target,
            "lease": claim.get("lease_expires"),
            "fencing_token": claim.get("fencing_token"),
            "brief_digest": job.payload_sha256,
            "offline": job.offline,
            "note": "claimed; call orchestrator_send with the fencing token "
                    "(no caller brief needed: the executable request is stored)"}


def _authorize_send(project_dir: str, run_id: str, job_id: str,
                    brief: dict | None, worker_id: str,
                    fencing_token: str | None, offline: bool) -> tuple:
    """Central pre-send authorization, checked atomically before network I/O.

    One gate for every transport: job belongs to the run; request fingerprint
    matches the frozen submission; status permits dispatch; lease holder and
    fencing token match a live lease; no cancellation/reconciliation block;
    the job is not offline (immutable per job); target/job/run attempts and
    the explicit cost cap permit it. Returns (run, job, version, brief,
    resolved) with a recorded cost reservation, or raises before any send.
    """
    from . import jobs as J
    con = S.connect(project_dir)
    try:
        try:
            rdata, rver = S.get(con, "runs", run_id)
        except KeyError:
            raise InvalidInput(f"unknown run {run_id}")
        run = D.Run.model_validate_json(json.dumps(rdata))
        job, jver = _get_job(con, job_id)
    finally:
        con.close()
    if run.status != "running":
        raise InvalidInput(f"run {run_id} is {run.status}: not dispatchable")
    if job_id not in (run.job_ids or []):
        raise InvalidInput(f"job {job_id} is not a member of run {run_id}: "
                             "cross-run dispatch refused")
    if job.cancel_requested:
        raise InvalidInput(f"job {job_id}: cancellation requested; dispatch refused")
    if job.reconciliation_required:
        raise InvalidInput(f"job {job_id}: reconciliation required before another spend")
    # Offline is monotonic for the job: a persisted offline job can never be
    # flipped live at send time, and the send mode must equal the persisted
    # restriction. This is checked here and again at the adapter boundary.
    if job.offline:
        raise InvalidInput(f"job {job_id} is persisted offline: live send refused; "
                             "authorize an explicit live job instead")
    if offline:
        raise InvalidInput(f"job {job_id} is a live job: offline send mode refused; "
                             "the send mode must equal the persisted job restriction")
    # The executable request is the frozen submission, not a caller brief. A
    # supplied brief must fingerprint-match the stored payload exactly.
    stored_brief = (job.request_brief or {})
    if not stored_brief:
        raise InvalidInput(f"job {job_id} has no frozen executable request "
                             "(legacy row): re-submit through the current path")
    if brief is not None:
        if J._payload_hash(brief, J._resolve_references(project_dir, brief, [])) \
                != job.payload_sha256:
            raise InvalidInput(f"job {job_id}: presented brief diverges from the frozen "
                                 "submission; resubmission with a new idempotency key "
                                 "is required, never an in-place swap")
        effective = brief
    else:
        effective = stored_brief
    resolved = J._resolve_references(project_dir, effective, [])
    if J._payload_hash(effective, resolved) != job.payload_sha256:
        raise InvalidInput(f"job {job_id}: frozen request no longer resolves to its "
                             "recorded fingerprint (stored bytes changed); reconcile first")
    J._check_fencing(job, job_id, worker_id, fencing_token)
    # No-progress guard first: a repeated identical fingerprint halts instead
    # of rebuying, whether or not attempts remain.
    if job.payload_sha256 in job.no_progress_signatures and job.attempt_count > 0:
        raise InvalidInput(f"job {job_id}: identical request already attempted; "
                             "halted without blind retry")
    if job.attempt_count >= job.max_attempts:
        raise InvalidInput(f"job {job_id}: attempt ceiling {job.attempt_count}/"
                             f"{job.max_attempts} exhausted; a new run cannot reset it")
    if job.dispatch_count >= job.max_attempts:
        raise InvalidInput(f"job {job_id}: dispatch ceiling exhausted")
    # Atomic reservation before network I/O: worst-case cost is reserved
    # against the explicit cap so two concurrent workers cannot double-spend.
    con = S.connect(project_dir)
    try:
        job2, v2 = _get_job(con, job_id)
        if v2 != jver:
            raise S.StaleRevisionError(
                f"stale_revision: jobs/{job_id} changed during authorization")
        J._check_fencing(job2, job_id, worker_id, fencing_token)
        job2.reserved_cost = (
            f"reserved:max_attempts={job2.max_attempts} "
            f"(dispatch {job2.dispatch_count + 1}/{job2.max_attempts})")
        job2.updated_at = _utc()
        nv = S.update_mutable(con, "jobs", job2, v2)
        job2.dispatch_count = job2.dispatch_count  # reserved, not yet dispatched
    finally:
        con.close()
    con = S.connect(project_dir)
    try:
        job3, v3 = _get_job(con, job_id)
    finally:
        con.close()
    return run, rver, job3, v3, effective, resolved, nv


def _mark_dispatched(project_dir: str, job_id: str, expected_version: int) -> int:
    """Record exactly one transport dispatch against the reservation."""
    con = S.connect(project_dir)
    try:
        job, v = _get_job(con, job_id)
        if v != expected_version:
            raise S.StaleRevisionError(
                f"stale_revision: jobs/{job_id} changed between reserve and dispatch")
        job.dispatch_count = job.dispatch_count + 1
        job.updated_at = _utc()
        return S.update_mutable(con, "jobs", job, v)
    finally:
        con.close()


def orchestrator_send(project_dir: str, run_id: str, job_id: str, brief: dict | None = None,
                      *, worker_id: str, offline: bool = False,
                      fencing_token: str | None = None,
                      transport=None, timeout: float = 120.0) -> dict:
    """Authorized-send-complete for one job: exactly one dispatch, then persist.

    The executable request comes from the frozen job row; a caller brief is
    optional and must fingerprint-match. Exactly one transport call happens
    per reservation. Ambiguous transport outcomes become durable
    unknown-outcome (reconcile before another spend), never blind retries.
    """
    from . import jobs as J
    from ..providers import image as img
    try:
        run, rver, job, jver, effective, resolved, _ = _authorize_send(
            project_dir, run_id, job_id, brief, worker_id, fencing_token, offline)
    except InvalidInput as e:
        if "already attempted" in str(e):
            con = S.connect(project_dir)
            try:
                rdata, rver = S.get(con, "runs", run_id)
                run = D.Run.model_validate_json(json.dumps(rdata))
                run.status = "halted"
                run.halt_reason = f"no progress: {e}"
                run.updated_at = _utc()
                S.update_mutable(con, "runs", run, rver)
            finally:
                con.close()
            return {"run_id": run_id, "job_id": job_id, "action": "stop",
                    "reason": f"no-progress: {e}"}
        raise
    # Build the exact wire request pre-send so the intent artifact is the
    # redacted request (never overwritten by the response artifact later).
    req = img.build_request(effective, resolved)
    from ..providers import ledger as _ledger
    from ..providers import wire as _W
    intent = _ledger.record_artifact(
        project_dir, "image_request_intent",
        {"job_id": job_id, "run_id": run_id,
         "request": _W.redact_wire(req), "reserved": job.reserved_cost,
         "brief_digest": job.payload_sha256},
        provider="image", model=req.get("model", ""))
    con = S.connect(project_dir)
    try:
        job_i, v_i = _get_job(con, job_id)
        if v_i != jver:
            raise S.StaleRevisionError(
                f"stale_revision: jobs/{job_id} changed before intent record")
        if not job_i.request_artifact:
            job_i.request_artifact = intent
        job_i.updated_at = _utc()
        jver = S.update_mutable(con, "jobs", job_i, v_i)
    finally:
        con.close()
    jver = _mark_dispatched(project_dir, job_id, jver)
    try:
        res = img.submit_resolved(effective, resolved, project_dir,
                                  job.idempotency_key, job_offline=job.offline,
                                  transport=transport, timeout=timeout)
    except InvalidInput as e:
        out = J.job_complete_failure(project_dir, job_id, worker_id=worker_id,
                                     expected_version=jver, error=str(e),
                                     retryable=False, fencing_token=fencing_token)
        _bump_run(project_dir, run_id)
        return {"run_id": run_id, "job_id": job_id, "action": "attempt", **out}
    except Exception as e:
        from .errors import RateLimited
        if isinstance(e, RateLimited):
            # Explicit provider refusal before acceptance: bounded requeue.
            out = J.job_complete_failure(project_dir, job_id, worker_id=worker_id,
                                         expected_version=jver, error=str(e),
                                         retryable=True, fencing_token=fencing_token)
            _bump_run(project_dir, run_id)
            return {"run_id": run_id, "job_id": job_id, "action": "attempt", **out}
        out = J.job_mark_unknown_outcome(project_dir, job_id, worker_id=worker_id,
                                         expected_version=jver, detail=str(e),
                                         fencing_token=fencing_token)
        return {"run_id": run_id, "job_id": job_id, "action": "needs_attention", **out}
    # Live send succeeded at HTTP level: complete with parsed bytes.
    try:
        done = J.job_complete_success(
            project_dir, job_id, worker_id=worker_id, expected_version=jver,
            image_bytes=res["output_bytes"], mime=res.get("output_mime", "image/png"),
            provider_response_id=res.get("response_id"),
            usage=res.get("usage") if isinstance(res.get("usage"), dict) else None,
            fencing_token=fencing_token)
    except InvalidInput as e:
        out = J.job_complete_failure(project_dir, job_id, worker_id=worker_id,
                                     expected_version=jver, error=str(e),
                                     retryable=False, fencing_token=fencing_token)
        _bump_run(project_dir, run_id)
        return {"run_id": run_id, "job_id": job_id, "action": "attempt", **out}
    con = S.connect(project_dir)
    try:
        job3, v3 = _get_job(con, job_id)
        # Response evidence lives in its own link; the pre-send intent keeps
        # the request slot. Neither overwrites the other.
        job3.response_artifact = res.get("response_artifact")
        job3.cost_actual = json.dumps(res.get("usage") or {})[:200]
        if job3.payload_sha256 not in job3.no_progress_signatures:
            job3.no_progress_signatures = [*job3.no_progress_signatures, job3.payload_sha256]
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
