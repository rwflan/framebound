"""Durable generation jobs: idempotent submit, server-resolved references, worker lifecycle.

Lifecycle: QUEUED -> RUNNING (leased claim) -> SUCCEEDED | FAILED |
NEEDS_ATTENTION (reconciliation/blocked) ; CANCELLED is terminal via guarded
cancel. Network calls happen outside long DB transactions: submit only queues;
the worker claims, sends, then completes. Restart-safe: attempt counts, budgets,
leases, signatures and payload fingerprints persist in the job row + Attempt
records; a restarted worker resumes rather than resetting them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput

MAX_TARGET_ATTEMPTS = 3

TERMINAL = {D.JobStatus.SUCCEEDED, D.JobStatus.FAILED,
            D.JobStatus.CANCELLED}


def _payload_hash(brief: dict, resolved_refs: list[dict]) -> str:
    """Complete request fingerprint: full brief plus sorted reference digests."""
    refs = sorted((r.get("asset_id", ""), r.get("byte_sha256", "")) for r in resolved_refs)
    return hashlib.sha256(json.dumps({"brief": brief, "references": refs},
                                      sort_keys=True).encode()).hexdigest()


def _resolve_references(project_dir: str, brief: dict,
                        caller_blobs: list[dict]) -> list[dict]:
    """Bind reference bytes server-side from frozen stored conditioning.

    The presented brief must carry the `compiled_brief_id` of a stored
    CompiledBrief and deep-equal its frozen bundle: caller-authored role
    labels, invented hashes, or zero-approval forgeries are refused before any
    transport. Pixels always come from the local store, never from
    caller-supplied bytes alone. Caller blobs are cross-checked when present
    and rejected on mismatch. The approved phase/pose guide image is resolved
    from the frozen binding and transmitted as `approved_phase` pixels — the
    model receives guide pixels, not just a text label.
    """
    from . import briefs as _B
    if not isinstance(brief, dict):
        raise InvalidInput("brief must be a compiled brief bundle, not a caller description")
    cbid = brief.get("compiled_brief_id")
    if not cbid:
        raise InvalidInput(
            "brief carries no compiled_brief_id: caller-authored briefs confer no "
            "authority; compile against stored human approval first")
    cb = _B.load_compiled_brief(project_dir, cbid)
    presented = {k: v for k, v in brief.items() if k != "compiled_brief_id"}
    frozen = dict(cb.brief)
    if hashlib.sha256(json.dumps(presented, sort_keys=True).encode()).hexdigest() != cb.brief_digest \
            and presented != frozen:
        raise InvalidInput("brief diverges from its frozen compiled conditioning: resubmission "
                           "of an altered brief is refused; recompile explicitly")
    # Frozen authority: exact approval/guide/phase-asset bindings.
    from . import approvals as _A
    con = S.connect(project_dir)
    try:
        try:
            apdata, _ = S.get(con, "reference_approvals", cb.approval_id)
        except KeyError:
            raise InvalidInput(f"brief approval {cb.approval_id} is no longer stored")
        ap = D.ReferenceApproval.model_validate_json(json.dumps(apdata))
        for aid in [*ap.identity_asset_ids, *ap.style_asset_ids, cb.phase_asset_id]:
            if ap.identity_asset_ids.__contains__(aid) or ap.style_asset_ids.__contains__(aid):
                expect = ap.asset_hashes.get(aid)
            else:
                expect = cb.phase_byte_sha256
            try:
                adata, _ = S.get(con, "assets", aid)
            except KeyError:
                raise InvalidInput(f"missing_input: frozen reference asset {aid} not stored")
            raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expect or digest != adata["byte_sha256"]:
                raise InvalidInput(f"frozen reference {aid}: bytes changed since human approval")
    finally:
        con.close()
    by_asset = {b.get("asset_id"): b for b in caller_blobs if isinstance(b, dict)}
    con = S.connect(project_dir)
    try:
        resolved = []
        plan = [("approved_identity", cb.identity_asset_id),
                ("approved_style", cb.style_asset_id),
                ("approved_phase", cb.phase_asset_id)]
        controls=cb.brief.get('repair_controls')
        if controls:
            from .animation_context import resolve_in
            contract=D.ClipContractRevision.model_validate(S.get(con,'contract_revisions',cb.contract_revision_id)[0])
            approved,_=resolve_in(con,project_dir,contract)
            op=D.AuthorizedOperation.model_validate(S.get(con,'authorized_operations',cb.brief['automatic_operation_id'])[0])
            if approved.id!=op.compiled_plan_id or controls['scope_sha256']!=approved.controls[op.slot].scope_sha256:
                raise InvalidInput('compiled redraw controls differ from approved operation')
            plan += [(role,controls[key]) for role,key in (('source_candidate','source_asset_id'),('editable_support','editable_mask_asset_id'),('protected_support','protected_mask_asset_id')) if controls.get(key)]
        for role, aid in plan:
            try:
                adata, _ = S.get(con, "assets", aid)
            except KeyError:
                raise InvalidInput(f"missing_input: frozen reference asset {aid} not stored")
            raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            entry = {"role": role, "asset_id": aid,
                     "byte_sha256": digest, "mime": adata.get("mime", "image/png"),
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
        if len(resolved) < 3:
            raise InvalidInput("frozen conditioning resolved without phase guide pixels")
        return resolved
    finally:
        con.close()


def _targets(brief: dict) -> list[str]:
    slot = brief.get("slot")
    cid = brief.get("contract_revision_id", "")
    if isinstance(slot, int):
        return [f"{cid}#slot-{slot}"]
    return [str(cid or "generation")]


def submit_generation(project_dir: str, brief: dict, reference_blobs: list[dict],
                      idempotency_key: str, *, offline: bool = False,
                      max_attempts: int = 3,
                      provider_settings: dict | None = None) -> D.ResultEnvelope:
    """Queue a generation job. Same key + same payload dedupes; different payload conflicts."""
    from ..providers import image as img
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise InvalidInput("idempotency_key is required")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) \
            or not (1 <= max_attempts <= 10):
        raise InvalidInput("max_attempts must be an int in 1..10")
    allowed_settings={'model','transport','base_url','grant_id','previous_response_id','edit_instruction',
                      'max_spend_usd','provider','source_asset_id','prompt'}
    if provider_settings is not None:
        if not isinstance(provider_settings,dict) or set(provider_settings)-allowed_settings:
            raise InvalidInput('unknown provider settings; credentials never belong in a job')
        if provider_settings.get('max_spend_usd') is not None:
            from decimal import Decimal,InvalidOperation
            try:amount=Decimal(str(provider_settings['max_spend_usd']).removeprefix('usd-'))
            except InvalidOperation as exc:raise InvalidInput('invalid money ceiling') from exc
            if not amount.is_finite() or amount<=0:raise InvalidInput('invalid/zero money ceiling')
    resolved = _resolve_references(project_dir, brief, reference_blobs or [])
    from ..providers import image as _imgmod
    provider=(provider_settings or {}).get('provider','image')
    if provider not in ('image','sam'):raise InvalidInput('unsupported specialist provider')
    from ..providers import sam
    import os
    default_model=(os.environ.get('FRAMEBOUND_SAM_MODEL') or sam.MODEL) if provider=='sam' else _imgmod._model()
    settings = {"model": default_model, "transport": "responses", **(provider_settings or {})}
    from ..providers.base import _base
    settings.setdefault('base_url', _base())
    if not isinstance(settings['model'],str) or not settings['model'].strip() or settings['transport']!='responses':
        raise InvalidInput('invalid frozen provider model/transport')
    if provider=='sam':
        con=S.connect(project_dir)
        try:
            try:source=D.Asset.model_validate(S.get(con,'assets',settings.get('source_asset_id',''))[0])
            except KeyError as exc:raise InvalidInput('SAM needs a stored source_asset_id') from exc
            raw=S.blob_path(project_dir,source.byte_sha256).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=source.byte_sha256:raise InvalidInput('SAM source changed')
        finally:con.close()
        settings.update(source_byte_sha256=source.byte_sha256,source_width=source.width,source_height=source.height)
        request=sam.build_request(base64.b64encode(raw).decode(),settings.get('prompt','figure'))
    else:
        request = (img.build_edit_request(settings['previous_response_id'],
                    settings.get('edit_instruction','bounded patch within approved support'),extra_blobs=resolved)
                   if settings.get('previous_response_id') else img.build_request(brief,resolved))
    request['model'] = settings['model']
    request_digest = hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    con = S.connect(project_dir)
    try:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]
        job = D.Job(id=f"job-{digest}", kind="segmentation" if provider=="sam" else "generation",
                    idempotency_key=idempotency_key,
                    payload_sha256=_payload_hash(brief, resolved),
                    provider=provider, targets=_targets(brief),
                    max_attempts=max_attempts,
                    budget_reserved=f"max_attempts={max_attempts}",
                    # The complete executable request is frozen at submit time:
                    # a restarted worker resumes from this row alone and no
                    # caller can substitute a different brief at send time.
                    request_brief={**dict(brief), '_frozen_provider_settings': settings},
                    provider_settings=settings, frozen_request=request,
                    frozen_request_sha256=request_digest,
                    offline=bool(offline))
        from .specialist_repair import validate_job_in
        validate_job_in(con,project_dir,job)
        job, created = S.create_job_idempotent(con, job)
        if not created:
            if job.offline != bool(offline) or job.max_attempts != max_attempts:
                raise S.ConflictError('job retry changed offline/attempt authority')
            if any(job.provider_settings.get(k) != v for k,v in (provider_settings or {}).items()):
                raise S.ConflictError('job retry changed frozen provider settings')
            return D.ResultEnvelope(ok=True, operation_id=f"op-{job.id}", revision_id=None,
                                     next_actions=["job_get"],
                                     artifacts=[{"id": job.id, "role": "job", "deduped": True,
                                                 "status": job.status.value}])
        # Record the exact not-yet-sent request for audit without transmitting.
        offline_req = bool(offline)
        from ..providers import base as _base
        if offline_req or not _base._key():
            from ..providers import ledger,wire
            res={'note':'Offline or credentials absent; no provider request sent.',
                 'request_artifact':ledger.record_artifact(project_dir,'provider_request_pending',
                    {'idempotency_key':idempotency_key,'request':wire.redact_wire(request),
                     'sent':False,'offline':bool(offline)},provider=provider,model=settings['model'])}
            job.request_artifact = res.get("request_artifact")
            S.update_mutable(con, "jobs", job, 1)
            return D.ResultEnvelope(ok=True, operation_id=f"op-{job.id}",
                                     issues=[{"code": "not_configured",
                                              "scope": "image-generation",
                                              "reason": res.get("note", "")}],
                                     artifacts=[{"id": job.id, "role": "job",
                                                 "status": job.status.value},
                                                {"id": res.get("request_artifact", ""),
                                                 "role": "request_artifact"}],
                                     next_actions=["provider_configure"])
        # Key present: stay QUEUED; the worker sends. Never transmit inside submit.
        return D.ResultEnvelope(ok=True, operation_id=f"op-{job.id}",
                                 artifacts=[{"id": job.id, "role": "job",
                                             "status": job.status.value}],
                                 next_actions=["job_claim"])
    finally:
        con.close()


def job_get(project_dir: str, job_id: str) -> dict:
    con = S.connect(project_dir)
    try:
        data, ver = S.get(con, "jobs", job_id)
    finally:
        con.close()
    return {"job": data, "version": ver}


def _lease_live(job: D.Job) -> bool:
    """True when the job holds an unexpired, well-formed lease."""
    if not job.lease_holder or not job.lease_expires:
        return False
    try:
        exp = datetime.fromisoformat(job.lease_expires)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > datetime.now(timezone.utc)
    except Exception:
        return False


def _check_fencing(job: D.Job, job_id: str, worker_id: str,
                   fencing_token: str | None) -> None:
    """Fencing for every mutating job transition: holder + token + live lease.

    An expired worker cannot finish or fail after reassignment; an arbitrary
    worker cannot touch another worker's job, nor an unclaimed queued job.
    """
    if job.status != D.JobStatus.RUNNING:
        raise InvalidInput(
            f"job {job_id} is {job.status.value}, not running: claim it before mutating")
    if not job.lease_holder or job.lease_holder != worker_id:
        raise InvalidInput(f"job {job_id} is held by {job.lease_holder or 'nobody'}, "
                           f"not {worker_id}: foreign-worker mutation refused")
    if not _lease_live(job):
        raise InvalidInput(f"job {job_id}: lease expired or malformed; "
                           "run job-reconcile before any further mutation")
    if job.fencing_token_sha256:
        import hashlib as _h
        if not fencing_token or _h.sha256(fencing_token.encode()).hexdigest() \
                != job.fencing_token_sha256:
            raise InvalidInput(f"job {job_id}: fencing token mismatch; "
                               "a stale or foreign worker cannot publish")


def job_claim(project_dir: str, job_id: str, worker_id: str,
              *, expected_version: int, lease_seconds: int = 300) -> dict:
    """QUEUED -> RUNNING with a fenced lease. Everything else refuses.

    Terminal, RUNNING, NEEDS_ATTENTION and CANCELLED jobs are never
    auto-claimed: expired RUNNING leases enter recovery via job_reconcile,
    and unknown/exhausted jobs need explicit reconciliation. A new claim
    mints a fencing token the worker must present to send/complete/fail.
    """
    if not worker_id or not worker_id.strip():
        raise InvalidInput("worker_id is required to claim a job")
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
        job = D.Job.model_validate_json(json.dumps(data))
        if job.status in TERMINAL:
            raise InvalidInput(f"job {job_id} is terminal ({job.status.value}); cannot claim")
        if job.status != D.JobStatus.QUEUED:
            if job.status == D.JobStatus.RUNNING and not _lease_live(job):
                raise InvalidInput(
                    f"job {job_id} lease expired while running: run job-reconcile "
                    "first; outcome is unknown until reconciled, never auto-reclaimed")
            raise InvalidInput(f"job {job_id} is {job.status.value}, not queued; "
                               "only queued jobs are claimable")
        if job.cancel_requested:
            job.status = D.JobStatus.CANCELLED
            nv = S.update_mutable(con, "jobs", job, expected_version)
            return {"job_id": job_id, "status": "cancelled", "version": nv}
        import secrets as _secrets
        import hashlib as _h
        token = _secrets.token_hex(16)
        job.status = D.JobStatus.RUNNING
        job.lease_holder = worker_id
        job.lease_expires = (datetime.now(timezone.utc)
                             + timedelta(seconds=lease_seconds)).isoformat()
        job.fencing_token_sha256 = _h.sha256(token.encode()).hexdigest()
        job.updated_at = datetime.now(timezone.utc).isoformat()
        nv = S.update_mutable(con, "jobs", job, expected_version)
        return {"job_id": job_id, "status": "running", "lease_holder": worker_id,
                "lease_expires": job.lease_expires, "fencing_token": token,
                "version": nv}
    finally:
        con.close()


def _record_attempt(project_dir: str, con, job: D.Job, *, result: str,
                    request_sha: str, response_ref: str | None,
                    candidate_ids: list[str], signature: str | None,
                    cost: str = "unknown") -> str:
    aid = f"att-{job.id}-{job.attempt_count + 1:02d}-{uuid.uuid4().hex[:6]}"
    result = (result[:61] + "...") if len(result) > 64 else result
    att = D.Attempt(id=aid, baseline_revision_id=job.id,
                    brief_id=(job.targets[0] if job.targets else job.id),
                    provider=job.provider, request_sha256=request_sha,
                    response_ref=response_ref, candidate_asset_ids=candidate_ids,
                    cost=cost, result=result,
                    no_progress_signature=signature)
    S.stage(con, att)  # staged: commits with the caller's atomic block
    return aid


def job_complete_success(project_dir: str, job_id: str, *, worker_id: str,
                         expected_version: int, image_bytes: bytes,
                         mime: str, provider_response_id: str | None,
                         usage: dict | None, output_asset_id: str | None = None,
                         fencing_token: str | None = None, origin: str = 'unknown') -> dict:
    """Persist provider output as a generated asset and mark SUCCEEDED.

    Fenced: holder + token + live lease + RUNNING status, all enforced.
    A successful send consumes exactly one attempt.
    """
    from ..media.canonical import canonical_pixels, pixel_sha256
    from PIL import Image as _Image
    import io as _io
    if not image_bytes:
        raise InvalidInput("cannot complete a job with empty output bytes")
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
        job = D.Job.model_validate_json(json.dumps(data))
        if job.status in TERMINAL:
            raise InvalidInput(f"job {job_id} is terminal ({job.status.value})")
        _check_fencing(job, job_id, worker_id, fencing_token)
        try:
            img = _Image.open(_io.BytesIO(image_bytes))
            img.load()
            w, h = img.size
            canon = canonical_pixels(img)
            pix = pixel_sha256(canon)
        except Exception as e:
            raise InvalidInput(f"provider output is not a decodable image: {e}") from e
        aid = output_asset_id or f"{job_id}-out-{job.attempt_count + 1:02d}"
        raw_digest = S.store_blob(project_dir, image_bytes)
        from .. import domain as _D
        rights='unknown'
        if job.provider_settings.get('grant_id'):
            rights=S.get(con,'provider_grants',job.provider_settings['grant_id'])[0].get('output_rights','unknown')
        parents=[]
        cbid=job.request_brief.get('compiled_brief_id')
        if cbid:
            cb=D.CompiledBrief.model_validate(S.get(con,'compiled_briefs',cbid)[0])
            parents=[cb.identity_asset_id,cb.style_asset_id,cb.phase_asset_id]
            controls=cb.brief.get('repair_controls') or {}
            parents += [controls[key] for key in ('source_asset_id','editable_mask_asset_id','protected_mask_asset_id') if controls.get(key)]
            parents=list(dict.fromkeys(parents))
            inherited={rights}|{S.get(con,'assets',parent)[0].get('rights','unknown') for parent in parents}
            rights=next(iter(inherited)) if len(inherited)==1 else 'unknown' if 'unknown' in inherited else 'mixed'
        asset = _D.Asset(id=aid, byte_sha256=raw_digest, pixel_sha256=pix,
                         mime=mime or "image/png", width=w, height=h,
                         source_kind="generated", rights=rights,source_job_id=job.id,origin=origin,parent_asset_ids=parents,
                         eligible_roles=[])
        with S.atomic(con):
            S.stage(con, asset)
            job.dispatch_inflight = False
            job.provider_response_id=provider_response_id
            job.provider_outcome='image'
            job.status = D.JobStatus.SUCCEEDED
            job.output_asset_ids = [*job.output_asset_ids, aid]
            # request_artifact is the pre-send intent; the response link lives
            # in response_artifact and must never overwrite it.
            job.cost_actual = json.dumps(usage or {})[:200]
            job.attempt_count = job.attempt_count + 1
            job.lease_holder = None
            job.lease_expires = None
            job.fencing_token_sha256 = ""
            job.reconciliation_required = False
            job.updated_at = datetime.now(timezone.utc).isoformat()
            data2, ver2 = S.get(con, "jobs", job_id)
            if ver2 != expected_version:
                raise S.StaleRevisionError(
                    f"stale_revision: jobs/{job_id} at version {ver2}, writer expected {expected_version}")
            _record_attempt(project_dir, con, job, result="succeeded",
                            request_sha=job.payload_sha256,
                            response_ref=provider_response_id,
                            candidate_ids=[aid], signature=None,
                            cost=json.dumps(usage or {})[:200])
            nv = S.stage_update(con, "jobs", job, expected_version)
        return {"job_id": job_id, "status": "succeeded", "asset_id": aid,
                "version": nv, "size": [w, h],
                "response_id": provider_response_id}
    finally:
        con.close()


def job_complete_segmentation(project_dir: str, job_id: str, *, worker_id: str,
                              expected_version: int, result: dict,
                              fencing_token: str | None) -> dict:
    """Commit source-bound model proposals and the one reserved attempt together."""
    from PIL import Image
    from ..media.canonical import canonical_pixels,pixel_sha256
    import io
    con=S.connect(project_dir)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            data,version=S.get(con,'jobs',job_id);job=D.Job.model_validate(data)
            if version!=expected_version:raise S.StaleRevisionError('segmentation completion is stale')
            _check_fencing(job,job_id,worker_id,fencing_token)
            source=D.Asset.model_validate(S.get(con,'assets',job.provider_settings['source_asset_id'])[0])
            if source.byte_sha256!=job.provider_settings['source_byte_sha256']:
                raise InvalidInput('SAM source no longer matches the frozen request')
            outcome=result.get('outcome');usable=outcome=='mask'
            records=result.get('records',[])
            if len(records)>32:raise InvalidInput('segmentation exceeds 32 native parts')
            ids=[];annotations=[]
            grant=(S.get(con,'provider_grants',job.provider_settings['grant_id'])[0]
                   if job.provider_settings.get('grant_id') else {})
            rights='original' if source.rights=='original' and grant.get('output_rights')=='original' else 'unknown'
            if usable:
                cb=D.CompiledBrief.model_validate(S.get(con,'compiled_briefs',job.request_brief['compiled_brief_id'])[0])
                contract=S.get(con,'contract_revisions',cb.contract_revision_id)[0]
                for index,record in enumerate(records):
                    mask=record['mask'];w,h=mask['width'],mask['height'];raster=bytes(mask['raster'])
                    if record['frame']!=0 or (w,h)!=(source.width,source.height) or len(raster)!=w*h:
                        raise InvalidInput('segmentation geometry differs from frozen source')
                    image=Image.frombytes('L',(w,h),bytes(255 if v else 0 for v in raster)).convert('RGBA')
                    buf=io.BytesIO();image.save(buf,format='PNG');aid=f'{job_id}-mask-{index}'
                    asset=D.Asset(id=aid,byte_sha256=S.store_blob(project_dir,buf.getvalue()),
                        pixel_sha256=pixel_sha256(canonical_pixels(image)),mime='image/png',width=w,height=h,
                        source_kind='derived',rights=rights,parent_asset_ids=[source.id],source_job_id=job_id,
                        origin=result.get('origin','unknown'),derivation={'operator':'segmentation','response':result.get('response_id')})
                    S.stage_identical(con,asset);ids.append(aid)
                    ann=D.AnnotationRevision(id=f'{aid}-annotation',source_asset_id=source.id,
                        source_pixel_sha256=source.pixel_sha256 or source.byte_sha256,
                        view=contract['action']['view'],mask_asset_id=aid,annotator_type='model_proposed')
                    S.stage_identical(con,ann);annotations.append(ann.id)
            job.origin=result.get('origin','unknown');job.provider_outcome=outcome
            job.provider_response_id=result.get('response_id');job.response_artifact=result.get('response_artifact')
            job.status=D.JobStatus.SUCCEEDED if outcome in ('mask','no_match') else D.JobStatus.FAILED
            job.output_asset_ids=ids;job.output_annotation_ids=annotations
            job.dispatch_inflight=False;job.attempt_count+=1
            job.lease_holder=None;job.lease_expires=None;job.fencing_token_sha256=''
            job.error=None if job.status==D.JobStatus.SUCCEEDED else str(result.get('reason',outcome))
            _record_attempt(project_dir,con,job,result=f'SAM {outcome}',request_sha=job.payload_sha256,
                response_ref=result.get('response_id'),candidate_ids=ids,signature=None)
            new_version=S.stage_update(con,'jobs',job,version)
            return {'job_id':job_id,'status':job.status.value,'version':new_version,
                    'asset_ids':ids,'annotation_ids':annotations,'outcome':outcome,'usable':usable}
    finally:con.close()


def job_complete_failure(project_dir: str, job_id: str, *, worker_id: str,
                         expected_version: int, error: str,
                         retryable: bool = False,
                         fencing_token: str | None = None) -> dict:
    """Record a failed attempt; retryable errors requeue while budget remains.

    Fenced like success: an arbitrary worker cannot fail another worker's job.
    """
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
        job = D.Job.model_validate_json(json.dumps(data))
        if job.status in TERMINAL:
            raise InvalidInput(f"job {job_id} is terminal ({job.status.value})")
        _check_fencing(job, job_id, worker_id, fencing_token)
        job.attempt_count = job.attempt_count + 1
        sig = hashlib.sha256(error.encode()).hexdigest()[:16]
        with S.atomic(con):
            _record_attempt(project_dir, con, job, result=f"failed: {error[:120]}",
                            request_sha=job.payload_sha256, response_ref=None,
                            candidate_ids=[], signature=sig)
            job.no_progress_signatures = [*job.no_progress_signatures, sig]
            job.dispatch_inflight = False
            job.error = error[:2000]
            job.lease_holder = None
            job.lease_expires = None
            job.fencing_token_sha256 = ""
            job.updated_at = datetime.now(timezone.utc).isoformat()
            if retryable and job.attempt_count < job.max_attempts:
                job.status = D.JobStatus.QUEUED
                nv = S.stage_update(con, "jobs", job, expected_version)
                return {"job_id": job_id, "status": "queued",
                        "attempt": job.attempt_count, "max_attempts": job.max_attempts,
                        "version": nv}
            job.status = D.JobStatus.NEEDS_ATTENTION
            job.reconciliation_required = not retryable
            nv = S.stage_update(con, "jobs", job, expected_version)
            return {"job_id": job_id, "status": "needs_attention",
                    "attempt": job.attempt_count, "reason": error[:500], "version": nv}
    finally:
        con.close()


def job_mark_unknown_outcome(project_dir: str, job_id: str, *, worker_id: str,
                             expected_version: int, detail: str,
                             fencing_token: str | None = None) -> dict:
    """Ambiguous timeout: one dispatch becomes durable unknown-outcome.

    Never blindly retried, never left invisible-queued, never reclaimable
    without explicit reconciliation. Fenced like every other mutation.
    """
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
        job = D.Job.model_validate_json(json.dumps(data))
        if job.status in TERMINAL:
            raise InvalidInput(f"job {job_id} is terminal ({job.status.value})")
        _check_fencing(job, job_id, worker_id, fencing_token)
        job.attempt_count = job.attempt_count + 1
        with S.atomic(con):
            _record_attempt(project_dir, con, job, result=f"unknown_outcome: {detail[:120]}",
                            request_sha=job.payload_sha256, response_ref=None,
                            candidate_ids=[], signature="unknown-outcome")
            job.status = D.JobStatus.NEEDS_ATTENTION
            job.reconciliation_required = True
            job.error = f"unknown provider outcome after ambiguous timeout; reconcile before retry: {detail[:500]}"
            job.lease_holder = None
            job.lease_expires = None
            job.fencing_token_sha256 = ""
            job.updated_at = datetime.now(timezone.utc).isoformat()
            nv = S.stage_update(con, "jobs", job, expected_version)
        return {"job_id": job_id, "status": "needs_attention",
                "reconciliation_required": True, "version": nv}
    finally:
        con.close()


def job_cancel(project_dir: str, job_id: str, expected_version: int) -> dict:
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
        job = D.Job.model_validate_json(json.dumps(data))
        if job.status in TERMINAL:
            raise InvalidInput(f"job {job_id} is already terminal ({job.status.value}); "
                               "cancellation is a no-op, not a transition")
        job.status = D.JobStatus.CANCELLED
        job.cancel_requested = True
        job.lease_holder = None
        job.lease_expires = None
        job.fencing_token_sha256 = ""
        job.updated_at = datetime.now(timezone.utc).isoformat()
        nv = S.update_mutable(con, "jobs", job, expected_version)
    finally:
        con.close()
    return {"job_id": job_id, "status": "cancelled", "version": nv}


def job_reconcile(project_dir: str, *, worker_id: str = "reconciler",
                  lease_grace_seconds: int = 0) -> dict:
    """Crash recovery: expired-lease RUNNING -> NEEDS_ATTENTION (reconcile).

    Never auto-retries an unknown outcome and never silently requeues.
    """
    now = datetime.now(timezone.utc)
    touched = []
    con = S.connect(project_dir)
    try:
        rows = con.execute("SELECT data, version FROM jobs").fetchall()
        for r in rows:
            job = D.Job.model_validate_json(r["data"])
            ver = r["version"]
            if job.status != D.JobStatus.RUNNING:
                continue
            expired = True
            if job.lease_expires:
                try:
                    exp = datetime.fromisoformat(job.lease_expires)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    expired = exp <= now
                except Exception:
                    expired = True
            if not expired:
                continue
            job.status = D.JobStatus.NEEDS_ATTENTION
            job.reconciliation_required = True
            job.error = (job.error or "") + "; reconciler: RUNNING lease expired, outcome unknown"
            job.error = job.error[:2000]
            job.lease_holder = None
            job.lease_expires = None
            job.fencing_token_sha256 = ""
            job.updated_at = now.isoformat()
            try:
                nv = S.update_mutable(con, "jobs", job, ver)
                touched.append({"job_id": job.id, "status": "needs_attention",
                                "version": nv})
            except S.StaleRevisionError:
                continue
    finally:
        con.close()
    return {"reconciled": touched, "count": len(touched)}
