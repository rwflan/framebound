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
                    fencing_token: str | None, offline: bool, *, simulation_mode: bool | None = None) -> tuple:
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
    # Stage E: queued model/settings are immutable. Environment changes
    # cannot alter a queued request; a mutated provider_settings is refused.
    _frozen_settings = (job.request_brief or {}).get("_frozen_provider_settings")
    if _frozen_settings is not None and job.provider_settings != _frozen_settings:
        # Edit chains submit new jobs with their own frozen settings; in-place
        # mutation of a queued job is never allowed (allows previous_response
        # chains only via explicit new submissions, never silent swaps).
        # Allow the single legitimate edit-chain field when it was frozen at
        # submit? No: submit never includes previous_response_id, so any
        # present value proves a post-submit mutation -> refuse.
        raise InvalidInput(f"job {job_id}: provider settings changed after submit; "
                             "queued model/settings are immutable: resubmit with a new key")
    stored_brief = {k: v for k, v in (job.request_brief or {}).items()
                    if not k.startswith("_frozen_")}
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
    if simulation_mode is not None:
        import hashlib
        if not job.frozen_request or hashlib.sha256(json.dumps(job.frozen_request,sort_keys=True).encode()).hexdigest()!=job.frozen_request_sha256:
            raise InvalidInput('legacy or altered frozen wire request: resubmit explicitly')

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
    # Stage E: numeric spend gate. A zero/exhausted cap fails closed; string
    # notes never authorize spend. New keys cannot reset the same target's
    # allowance (enforced below via target-level accounting).
    import os
    from decimal import Decimal, InvalidOperation
    caps = [(job.provider_settings or {}).get('max_spend_usd'),os.environ.get('FRAMEBOUND_SPEND_CEILING')]
    for cap in caps:
        if cap is None: continue
        try:
            amount = Decimal(str(cap).removeprefix('calls-').removeprefix('usd-'))
            if not amount.is_finite() or amount <= 0:
                raise InvalidInput('spend ceiling allows no dispatch')
        except (InvalidOperation,ValueError) as exc:
            raise InvalidInput('invalid spend ceiling') from exc
    if str(job.budget_reserved) in ('usd-0','usd_0','usd-0.0','usd_0.0'):
        raise InvalidInput('zero spend cap allows no dispatch')
    # Stage E: run-level ceiling enforced at authorize time (not just at
    # run_once entry) so two jobs in a run capped at one cannot both dispatch.
    if run.attempts_used >= run.max_attempts:
        raise InvalidInput(f"run {run_id}: attempt ceiling {run.attempts_used}/{run.max_attempts} exhausted")
    # Reserve job, run and target units under one write lock, before I/O.
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            job2, v2 = _get_job(con, job_id)
            live_run, rv = S.get(con, 'runs', run_id)
            run = D.Run.model_validate(live_run)
            if v2 != jver:
                raise S.StaleRevisionError('job changed during authorization')
            J._check_fencing(job2, job_id, worker_id, fencing_token)
            if job2.dispatch_inflight:
                raise InvalidInput('dispatch already in flight; reconcile before another send')
            if run.status != 'running' or run.attempts_used >= run.max_attempts:
                raise InvalidInput('run attempt ceiling exhausted')
            grant_id=job2.provider_settings.get('grant_id')
            target_limit=J.MAX_TARGET_ATTEMPTS
            if grant_id:
                try:target_limit=S.get(con,'provider_grants',grant_id)[0]['max_dispatches']
                except KeyError as exc:raise InvalidInput('provider grant not found') from exc
            tried=0;project_calls=0
            for row in con.execute('SELECT data FROM jobs'):
                other=D.Job.model_validate_json(row['data']);project_calls+=other.dispatch_count
                if set(other.targets)&set(job2.targets) and (not grant_id or other.provider_settings.get('grant_id')==grant_id):
                    tried+=other.dispatch_count
            if not grant_id and tried>=target_limit:raise InvalidInput('shared target attempt ceiling exhausted')
            cap=os.environ.get('FRAMEBOUND_SPEND_CEILING','')
            if cap.startswith('calls-') and project_calls>=int(cap[6:]):
                raise InvalidInput('project call ceiling exhausted')
            from .specialist_repair import validate_job_in
            validate_job_in(con,project_dir,job2,sending=True)
            from .provider_grants import reserve_in, DispatchPermit
            reserve_in(con,job2,simulation_mode)
            import secrets, hashlib
            token=secrets.token_hex(24)
            job2.dispatch_token_sha256=hashlib.sha256(token.encode()).hexdigest()
            job2.wire_started=False
            job2.dispatch_inflight = True
            job2.dispatch_count += 1
            if not job2.provider_settings.get('grant_id'):
                job2.reserved_cost = 'reserved:simulation-dispatch-unit:no-provider-charge'
            job2.updated_at = _utc()
            run.attempts_used += 1
            run.updated_at = _utc()
            nv = S.stage_update(con,'jobs',job2,v2)
            rver = S.stage_update(con,'runs',run,rv)
        permit=DispatchPermit(project_dir,job_id,token,job2.frozen_request_sha256,
                              job2.provider_settings.get('base_url','https://api.meta.ai/v1'),simulation_mode is not False)
        return run, rver, job2, nv, effective, resolved, permit
    finally:
        con.close()


def _mark_dispatched(project_dir: str, job_id: str, expected_version: int) -> int:
    """Verify the reservation still holds; dispatch was counted at authorize.

    Stage E: exactly one dispatch per reservation. The count was incremented
    atomically in _authorize_send; this verifies no intervening write slipped
    in, without double-counting.
    """
    con = S.connect(project_dir)
    try:
        job, v = _get_job(con, job_id)
        if v != expected_version:
            raise S.StaleRevisionError(
                f"stale_revision: jobs/{job_id} changed between reserve and dispatch")
        return v
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
        run, rver, job, jver, effective, resolved, permit = _authorize_send(
            project_dir, run_id, job_id, brief, worker_id, fencing_token, offline, simulation_mode=transport is not None)
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
    # An edit-chain job refines its prior response instead of regenerating.
    if not job.frozen_request or not job.frozen_request_sha256:
        raise InvalidInput('legacy job lacks a frozen wire request: resubmit explicitly')
    req = dict(job.frozen_request)
    import hashlib
    if hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest() != job.frozen_request_sha256:
        raise InvalidInput('frozen wire request changed')
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
        job_i.request_artifact = intent
        job_i.updated_at = _utc()
        jver = S.update_mutable(con, "jobs", job_i, v_i)
    finally:
        con.close()
    jver = _mark_dispatched(project_dir, job_id, jver)
    try:
        if job.provider=='sam':
            from ..providers import sam
            res=sam.submit('',job.provider_settings.get('prompt','figure'),project_dir,
                    source_width=job.provider_settings['source_width'],source_height=job.provider_settings['source_height'],
                    req=req,permit=permit,transport=transport,timeout=timeout)
        else:
            res = img.submit_resolved(effective, resolved, project_dir,
                                      job.idempotency_key, req=req,
                                      job_offline=job.offline,
                                      transport=transport, timeout=timeout, permit=permit)
    except InvalidInput as e:
        jver=permit.wire_version or jver
        out = J.job_complete_failure(project_dir, job_id, worker_id=worker_id,
                                     expected_version=jver, error=str(e),
                                     retryable=False, fencing_token=fencing_token)
        _bump_run(project_dir, run_id)
        return {"run_id": run_id, "job_id": job_id, "action": "attempt", **out}
    except Exception as e:
        jver=permit.wire_version or jver
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
    jver=permit.wire_version or jver
    # Live send succeeded at HTTP level: complete with parsed bytes.
    try:
        if job.provider=='sam':
            done=J.job_complete_segmentation(project_dir,job_id,worker_id=worker_id,
                 expected_version=jver,result=res,fencing_token=fencing_token)
        else:
            done = J.job_complete_success(
                project_dir, job_id, worker_id=worker_id, expected_version=jver,
                image_bytes=res["output_bytes"], mime=res.get("output_mime", "image/png"),
                provider_response_id=res.get("response_id"),
                usage=res.get("usage") if isinstance(res.get("usage"), dict) else None,
                fencing_token=fencing_token,origin=res.get("origin","unknown"))
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
        # Explicit execution origin travels with the job: simulated transports
        # are never live provider evidence (exports enforce this).
        if res.get("origin"):
            job3.origin = res["origin"]
        job3.cost_actual = json.dumps(res.get("usage") or {})[:200]
        if job3.payload_sha256 not in job3.no_progress_signatures:
            job3.no_progress_signatures = [*job3.no_progress_signatures, job3.payload_sha256]
        S.update_mutable(con, "jobs", job3, v3)
    finally:
        con.close()
    _bump_run(project_dir, run_id)
    out = {"run_id": run_id, "job_id": job_id,
           "action": "succeeded" if done.get('status')=='succeeded' else 'failed', **done}
    # Surface the provider response identity for edit chains and receipts,
    # even when the completion envelope omits it.
    if not out.get("response_id"):
        con = S.connect(project_dir)
        try:
            job4, _ = _get_job(con, job_id)
        finally:
            con.close()
        if job4.response_artifact:
            from ..providers import ledger as _ledger
            try:
                payload = _ledger.load_artifact(project_dir,
                                                job4.response_artifact).get("payload", {})
                out["response_id"] = payload.get("request_id") or payload.get("response_id")
            except Exception:
                pass
    return out


def _bump_run(project_dir: str, run_id: str) -> None:
    con = S.connect(project_dir)
    try:
        try:
            rdata, rver = S.get(con, "runs", run_id)
        except KeyError:
            return
        run = D.Run.model_validate_json(json.dumps(rdata))
        run.updated_at = _utc()
        if run.attempts_used >= run.max_attempts:
            run.status = "halted"
            run.halt_reason = f"budget exhausted: {run.attempts_used}/{run.max_attempts}"
        S.update_mutable(con, "runs", run, rver)
    finally:
        con.close()
