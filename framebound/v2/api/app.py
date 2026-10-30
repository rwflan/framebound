"""Local review API. Browser review uses an automatic same-origin HttpOnly session.
Machine actor headers remain orchestrator credentials. Human decisions still bind
exact immutable revisions/evaluations and enforce all service authority checks.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import Field

from ...v3.domain import TaskSpec, TaskRecord
from ...v3.services.exports import ExportSelection
from ...v3.services.interventions import MarkRequest, ResolveRequest, DecisionRequest
from .. import domain as D
from .. import storage as S
from ..services.authz import Actor
from .dto import (ActivityPageDto, CompareBundleDto, CorrectionsListDto, EligibilityDto, ExportResultDto, IssueDetailDto, PacketBundleDto, ProjectSummaryDto, TaskStatusDto)
from ..services.errors import AuthorizationError, InvalidInput, StaleRevision as SvcStale
from .dto import ReferencesDto, ReferenceApproveBodyDto as ReferenceBody
from .dto import ChangesDto, DeskSessionDto
from .dto import (AnimationStartBodyDto,AnimationRunDto,ProviderGrantDto,ProviderGrantViewDto,
                  ProviderGrantRevokeResultDto,ExpectedVersionBodyDto,ProviderReceiptBodyDto,
                  ProviderReconcileResultDto,ReferenceRevokeBodyDto,ReferenceRevokeResultDto,JobSubmitRequestDto)


class AgentSatisfactionBody(D.Strict):
    revision_id: str = Field(min_length=1, max_length=90)
    evaluation_id: str = Field(min_length=1, max_length=128)
    note: str = Field(default='', max_length=2000)


class HandoffRebaseBody(D.Strict):
    expected_revision_id: str = Field(min_length=1, max_length=90)
    expected_feedback_id: str = Field(min_length=1, max_length=256)


class AgentRunStartBody(D.Strict):
    task_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)


class AgentCancelBody(D.Strict):
    reason: str = Field(min_length=1, max_length=2000)


class AgentSubmissionBody(D.Strict):
    revision_id: str = Field(min_length=1, max_length=90)
    frame_asset_ids: list[str] = Field(min_length=1, max_length=512)
    parent_revision_id: str | None = None
    feedback_id: str | None = None
    presented_holds: list[D.StrictInt] | None = None
    generation_metadata: dict | None = None


class IssueBody(D.Strict):
    id: str | None = Field(default=None, min_length=1, max_length=128)
    clip_revision_id: str = Field(min_length=1, max_length=128)
    packet_id: str | None = Field(default=None, min_length=1, max_length=128)
    frame_instance_id: str | None = Field(default=None, min_length=1, max_length=128)
    frame_range: list[D.StrictInt] | None = None
    roi: D.Roi | None = None
    category: str = Field(default="general", min_length=1, max_length=64)
    note: str = Field(default="", max_length=2000)


class DecisionBody(D.Strict):
    id: str | None = Field(default=None, min_length=1, max_length=128)
    action: Literal["approve", "reject", "needs_changes"]
    clip_revision_id: str = Field(min_length=1, max_length=128)
    packet_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_revision_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_evaluation_id: str | None = Field(default=None, min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)


class ResolveBody(D.Strict):
    id: str | None = Field(default=None, min_length=1, max_length=128)
    replacement_revision_id: str = Field(min_length=1, max_length=128)
    packet_id: str | None = Field(default=None, min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)


class ClaimBody(D.Strict):
    expected_version: D.StrictInt = 1


class SubmitBody(D.Strict):
    slot_assets: dict[str, str] = Field(default_factory=dict)
    recipe: str = Field(default="repair:bounded-patch", min_length=1, max_length=500)
    new_revision_id: str | None = Field(default=None, min_length=1, max_length=128)
    claim_token: str | None = Field(default=None, min_length=1, max_length=256)
    transform: dict | None = None
    baseline_evaluation_id: str | None = Field(default=None, min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)
    expected_version: D.StrictInt = 1


class MaskBody(D.Strict):
    issue_event_id: str = Field(min_length=1, max_length=128)
    mask_asset_id: str = Field(min_length=1, max_length=128)
    covered_slots: list[D.StrictInt] = Field(min_length=1)


class ReopenBody(D.Strict):
    note: str = Field(default="", max_length=2000)


def create_app(project_dir: str) -> FastAPI:
    app = FastAPI(title="Framebound v2 review API", version="2.0.0a1")
    app.state.project_dir = project_dir


    @app.get('/v3/reader-capabilities')
    def reader_capabilities():
        return {'schema_versions':['2.0','3.0'],'dataset_versions':['2.3','3.0'],
                'label_views':['human_accepted','automatically_verified','research','withheld'],
                'automatic_labels_are_human_acceptance':False}

    @app.post('/v3/exports/preview')
    def agent_export_preview(body: ExportSelection):
        from ...v3.services import exports
        return exports.plan(project_dir,body.model_dump())

    @app.post('/v3/exports')
    def agent_export_build(body: ExportSelection):
        from ...v3.services import exports
        return exports.build(project_dir,body.model_dump())

    @app.get('/v3/desk')
    def agent_desk():
        from ...v3.services import desk
        return desk.snapshot(project_dir)

    @app.get('/v3/desk/revisions/{revision_id}')
    def agent_desk_revision(revision_id: str):
        from ...v3.services import desk
        return desk.revision(project_dir,revision_id)

    @app.post('/v3/runs/{run_id}/agent-satisfaction')
    def agent_satisfaction(run_id: str, body: AgentSatisfactionBody, x_actor_id: str | None = Header(default=None)):
        from ...v3.services import interventions as I
        return I.agent_satisfied(project_dir, Actor(type='orchestrator',id=x_actor_id or 'http-parent-agent'),run_id, **body.model_dump())

    @app.post('/v3/runs/{run_id}/interventions')
    def agent_mark(run_id: str, body: MarkRequest, x_session_token: str | None = Header(default=None),
                   x_actor_id: str | None = Header(default=None)):
        from ...v3.services import interventions as I
        result = I.mark(project_dir, actor(x_session_token, x_actor_id), run_id, body.model_dump(mode='json'))
        publish({'type':'agent_intervention_saved','run_id':run_id,'intervention_id':result['id']})
        return result

    @app.get('/v3/interventions/{intervention_id}')
    def agent_intervention_get(intervention_id: str):
        from ...v3.services import interventions as I
        return I.get(project_dir, intervention_id)

    @app.post('/v3/interventions/{intervention_id}/resolve')
    def agent_intervention_resolve(intervention_id: str, body: ResolveRequest,
                                  x_session_token: str | None = Header(default=None),
                                  x_actor_id: str | None = Header(default=None)):
        from ...v3.services import interventions as I
        result = I.resolve(project_dir, actor(x_session_token,x_actor_id), intervention_id, body.model_dump(mode='json'))
        publish({'type':'agent_intervention_resolved','intervention_id':intervention_id})
        return result

    @app.post('/v3/interventions/{intervention_id}/reopen')
    def agent_intervention_reopen(intervention_id: str, body: ResolveRequest,
                                 x_session_token: str | None = Header(default=None),
                                 x_actor_id: str | None = Header(default=None)):
        from ...v3.services import interventions as I
        result = I.resolve(project_dir, actor(x_session_token,x_actor_id), intervention_id, body.model_dump(mode='json'), reopen=True)
        publish({'type':'agent_intervention_reopened','intervention_id':intervention_id})
        return result

    @app.post('/v3/runs/{run_id}/decisions')
    def agent_decision(run_id: str, body: DecisionRequest, x_session_token: str | None = Header(default=None),
                       x_actor_id: str | None = Header(default=None)):
        from ...v3.services import interventions as I
        result = I.decision(project_dir, actor(x_session_token,x_actor_id), run_id, body.model_dump(mode='json'))
        publish({'type':'agent_decision_saved','run_id':run_id})
        return result

    @app.get('/v3/feedback/{feedback_id}')
    def agent_handoff(feedback_id: str):
        from ...v3.services import interventions as I
        return I.handoff(project_dir, feedback_id)

    @app.get('/v3/feedback/{feedback_id}/text')
    def agent_handoff_download(feedback_id: str):
        from ...v3.services import interventions as I
        result = I.handoff(project_dir, feedback_id)
        return Response(result['text'], media_type='text/plain', headers={
            'Content-Disposition':'attachment; filename="framebound-instructions.txt"',
            'X-Framebound-Handoff-Stale':str(result['stale']).lower()})

    @app.post('/v3/feedback/{feedback_id}/rebase')
    def agent_handoff_rebase(feedback_id: str, body: HandoffRebaseBody,
                            x_session_token: str | None = Header(default=None),
                            x_actor_id: str | None = Header(default=None)):
        from ...v3.services import interventions as I
        result = I.rebase(project_dir, actor(x_session_token,x_actor_id), feedback_id, **body.model_dump())
        publish({'type':'agent_handoff_rebased','run_id':result['run_id']})
        return result

    @app.get('/v3/revisions/{revision_id}')
    def agent_revision_get(revision_id: str):
        from ...v3.services import loop
        return loop.revision_get(project_dir, revision_id)

    @app.post('/v3/runs')
    def agent_run_start(body: AgentRunStartBody):
        from ...v3.services import loop
        return loop.start(project_dir, body.task_id, body.run_id)

    @app.get('/v3/runs/{run_id}')
    def agent_run_get(run_id: str):
        from ...v3.services import loop
        return loop.get(project_dir, run_id)

    @app.get('/v3/runs/{run_id}/eligibility')
    def agent_run_eligibility(run_id: str):
        from ...v3.services import loop
        return loop.eligibility(project_dir, run_id)

    @app.post('/v3/runs/{run_id}/cancel')
    def agent_run_cancel(run_id: str, body: AgentCancelBody):
        from ...v3.services import loop
        return loop.cancel(project_dir, run_id, body.reason)

    @app.post('/v3/runs/{run_id}/submissions')
    def agent_run_submit(run_id: str, body: AgentSubmissionBody):
        from ...v3.services import loop
        return loop.submit(project_dir, run_id, **body.model_dump())

    @app.post('/v3/tasks', response_model=TaskRecord)
    def task_create(spec: TaskSpec):
        from ...v3.services import tasks
        return tasks.create(project_dir, spec.model_dump(mode='json'))

    @app.get('/v3/tasks/{task_id}', response_model=TaskRecord)
    def task_get(task_id: str):
        from ...v3.services import tasks
        return tasks.get(project_dir, task_id)

    @app.get('/v3/tasks/{task_id}/inputs')
    def task_inputs(task_id: str):
        from ...v3.services import tasks
        return tasks.compile_inputs(project_dir, task_id)


    app.state.subscribers: list[asyncio.Queue] = []

    def publish(event: dict) -> None:
        for q in app.state.subscribers:
            q.put_nowait(event)

    def actor(x_session_token: str | None, x_actor_id: str | None) -> Actor:
        if x_session_token:
            from ..services import sessions as SN
            rid = SN.resolve_session(project_dir, x_session_token)
            if rid is None:
                raise HTTPException(401, "invalid or expired reviewer session token")
            return Actor(type="reviewer", id=rid)
        return Actor(type="orchestrator", id=(x_actor_id or "anonymous")[:200] or "anonymous")

    @app.exception_handler(AuthorizationError)
    async def _forbidden(_: Request, e: AuthorizationError):
        return JSONResponse({"code": "forbidden", "detail": str(e)}, status_code=403)

    @app.exception_handler(InvalidInput)
    async def _bad(_: Request, e: InvalidInput):
        return JSONResponse({"code": "invalid_input", "detail": str(e)}, status_code=422)

    @app.exception_handler(S.StaleRevisionError)
    async def _stale(_: Request, e: S.StaleRevisionError):
        return JSONResponse({"code": "stale_revision", "detail": str(e)}, status_code=409)

    @app.exception_handler(SvcStale)
    async def _stale2(_: Request, e: SvcStale):
        return JSONResponse({"code": "stale_revision", "detail": str(e)}, status_code=409)

    @app.exception_handler(S.ConflictError)
    async def _conflict(_: Request, e: S.ConflictError):
        return JSONResponse({"code": "conflict", "detail": str(e)}, status_code=409)

    @app.exception_handler(S.FrozenRevisionError)
    async def _frozen(_: Request, e: S.FrozenRevisionError):
        return JSONResponse({"code": "frozen_revision", "detail": str(e)}, status_code=409)

    from ..services import errors as _E

    @app.exception_handler(_E.PermissionDenied)
    async def _perm(_: Request, e: _E.PermissionDenied):
        return JSONResponse({"code": "permission_denied", "detail": str(e)}, status_code=403)

    @app.exception_handler(_E.ModelUnavailable)
    async def _noun(_: Request, e: _E.ModelUnavailable):
        return JSONResponse({"code": "model_unavailable", "detail": str(e)}, status_code=502)

    @app.exception_handler(_E.ResponseInvalid)
    async def _rinv(_: Request, e: _E.ResponseInvalid):
        return JSONResponse({"code": "response_invalid", "detail": str(e)}, status_code=502)

    @app.exception_handler(_E.TransportError)
    async def _terr(_: Request, e: _E.TransportError):
        return JSONResponse({"code": "transport_error", "detail": str(e)}, status_code=503)

    @app.exception_handler(_E.ProviderTimeout)
    async def _pto(_: Request, e: _E.ProviderTimeout):
        return JSONResponse({"code": "provider_timeout", "detail": str(e)}, status_code=504)

    @app.exception_handler(_E.RateLimited)
    async def _rl(_: Request, e: _E.RateLimited):
        return JSONResponse({"code": "rate_limited", "detail": str(e)}, status_code=429)

    @app.get("/api/health")
    def health():
        return {"ok": True, "schema_version": "2.0"}

    @app.post("/api/reviewer/revoke", status_code=200)
    def reviewer_revoke(body: dict,
                        x_operator_secret: str | None = Header(default=None)):
        """Operator revokes a reviewer session token so it stops authorizing."""
        from ..services import sessions as SN
        try:
            return SN.revoke_session(project_dir, str(body.get("session_token", "")),
                                     operator_credential=x_operator_secret or "")
        except AuthorizationError as e:
            raise HTTPException(403, str(e))
        except InvalidInput as e:
            raise HTTPException(422, str(e))

    def local_browser(request: Request) -> None:
        from urllib.parse import urlsplit
        import ipaddress
        peer = request.client.host if request.client else ""
        try:
            local_peer = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            local_peer = False
        host = request.url.hostname or ""
        try:
            local_host = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local_host = host == "localhost"
        origin = urlsplit(request.headers.get("origin", ""))
        if (not local_peer or not local_host or origin.scheme != request.url.scheme
                or origin.netloc != request.url.netloc
                or request.headers.get("x-framebound-desk") != "1"
                or request.headers.get("sec-fetch-site") != "same-origin"
                or request.headers.get("x-actor-id")):
            raise HTTPException(403, "local same-origin browser required")

    @app.middleware("http")
    async def browser_credentials(request: Request, call_next):
        token = request.cookies.get("fb_desk_review")
        if (token and request.method not in {"GET", "HEAD", "OPTIONS"}
                and not request.headers.get("x-session-token")
                and not request.headers.get("x-actor-id")
                and not request.headers.get("x-operator-secret")):
            try:
                local_browser(request)
            except HTTPException as e:
                return JSONResponse({"code": "forbidden", "detail": e.detail}, status_code=e.status_code)
            request.scope["headers"] = [*request.scope["headers"],
                (b"x-session-token", token.encode())]
        return await call_next(request)

    @app.post("/api/desk/session", response_model=DeskSessionDto)
    def browser_session(request: Request, response: Response):
        from ..services import sessions as SN
        local_browser(request)
        token = request.cookies.get("fb_desk_review")
        reviewer = SN.resolve_session(project_dir, token)
        if not reviewer:
            session = SN.create_session(project_dir)
            token, reviewer = session["session_token"], session["reviewer_id"]
        # Both /api (reviewed guide) and /v3 (agent runs) use the same local reviewer boundary.
        response.delete_cookie("fb_desk_review", path="/api")
        response.set_cookie("fb_desk_review", token, httponly=True,
            samesite="strict", secure=request.url.scheme == "https", path="/",
            max_age=SN.SESSION_TTL_HOURS * 3600)
        response.headers["Cache-Control"] = "no-store"
        return {"ready": True}

    @app.get("/api/changes", response_model=ChangesDto)
    def changes(response: Response):
        import hashlib
        marks = []
        for name in ("framebound.sqlite3", "framebound.sqlite3-wal"):
            try:
                stat = (Path(project_dir) / name).stat()
                marks.append((name, stat.st_mtime_ns, stat.st_size) if stat.st_size else (name, 0, 0))
            except FileNotFoundError:
                marks.append((name, 0, 0))
        response.headers["Cache-Control"] = "no-store"
        return {"revision": hashlib.sha256(repr(marks).encode()).hexdigest()}

    @app.get("/api/project", response_model=ProjectSummaryDto)
    def project():
        from ..services import projects
        con = S.connect(project_dir)
        try:
            entries = [json.loads(r["data"]) for r in con.execute("SELECT data FROM projects")]
        finally:
            con.close()
        return {"summary": projects.get_summary(project_dir),
                "projects": [{"id": p["id"], "name": p["name"]} for p in entries]}

    @app.post('/api/animation/runs',response_model=AnimationRunDto)
    def animation_start(body: AnimationStartBodyDto):
        from ..services.auto_repair import start_run
        return start_run(project_dir,body.revision_id,body.idempotency_key,provider_settings=body.provider_settings,offline=body.offline)

    @app.post('/api/animation/runs/{run_id}/step',response_model=AnimationRunDto)
    def animation_step(run_id: str):
        from ..services.auto_repair import step_run
        return step_run(project_dir,run_id)

    @app.get('/api/animation/runs/{run_id}',response_model=AnimationRunDto)
    def animation_get(run_id: str):
        from ..services.auto_repair import get_run
        return get_run(project_dir,run_id)

    @app.get('/api/references', response_model=ReferencesDto)
    def references():
        con = S.connect(project_dir)
        try:
            from ..services.approvals import revoked_approval_ids_in,active_guide_approval_ids_in
            return {**{table:[json.loads(r['data']) for r in con.execute(f'SELECT data FROM {table}')]
                    for table in ('character_revisions','motion_guides','reference_approvals','assets')},
                    'revoked_approval_ids':sorted(revoked_approval_ids_in(con)),'active_approval_ids':active_guide_approval_ids_in(con)}
        finally:
            con.close()

    @app.post('/api/jobs/{job_id}/operator-reconcile',response_model=ProviderReconcileResultDto)
    def provider_reconcile(job_id: str, body: ProviderReceiptBodyDto, x_operator_secret: str | None = Header(default=None)):
        from ..services.provider_recovery import reconcile
        return reconcile(project_dir,job_id,body.model_dump(),x_operator_secret or '')

    @app.get('/api/provider-grants/{grant_id}',response_model=ProviderGrantViewDto)
    def provider_grant_get(grant_id: str):
        from ..services.provider_grants import get_grant
        return get_grant(project_dir,grant_id)

    @app.post('/api/provider-grants/{grant_id}/revoke',response_model=ProviderGrantRevokeResultDto)
    def provider_grant_revoke(grant_id: str,body: ExpectedVersionBodyDto,x_operator_secret: str | None = Header(default=None)):
        from ..services.provider_grants import revoke
        return revoke(project_dir,grant_id,body.expected_version,x_operator_secret or '')

    @app.post('/api/provider-grants', status_code=201,response_model=ProviderGrantDto)
    def provider_grant(body: ProviderGrantDto, x_operator_secret: str | None = Header(default=None)):
        from ..services.provider_grants import issue
        return issue(project_dir,body.model_dump(),x_operator_secret or '')

    @app.post('/api/references/{approval_id}/revoke',response_model=ReferenceRevokeResultDto)
    def revoke_reference(approval_id: str, body: ReferenceRevokeBodyDto,
                         x_session_token: str | None = Header(default=None),x_actor_id: str | None = Header(default=None)):
        from ..services.approvals import revoke_reference
        return revoke_reference(project_dir,actor(x_session_token,x_actor_id),approval_id,body.event_id,body.note)

    @app.post('/api/references/approve')
    def approve_references(body: ReferenceBody,
                           x_session_token: str | None = Header(default=None),
                           x_actor_id: str | None = Header(default=None)):
        from ..services import approvals
        return approvals.approve_reference(project_dir, actor(x_session_token,x_actor_id),
                    body.character_revision_id,body.motion_guide_id,body.event_id).model_dump()

    @app.get("/api/packets")
    def packets():
        con = S.connect(project_dir)
        try:
            rows = con.execute("SELECT data FROM review_packets").fetchall()
            return {"packets": [json.loads(r["data"]) for r in rows]}
        finally:
            con.close()

    @app.get("/api/packet/{packet_id}", response_model=PacketBundleDto)
    def packet(packet_id: str):
        con = S.connect(project_dir)
        try:
            pkt, _ = S.get(con, "review_packets", packet_id)
            ev, _ = S.get(con, "evaluations", pkt["evaluation_id"])
            rev, _ = S.get(con, "clip_revisions", pkt["clip_revision_id"])
            aids = []
            for fid in rev["frame_instance_ids"]:
                f, _ = S.get(con, "frame_instances", fid)
                fi = D.FrameInstance.model_validate(f)
                aids.append({"frame_instance_id": fi.id, "slot": fi.slot, "asset_id": fi.asset_id,
                             "phase": fi.phase, "hold_ticks": fi.hold_ticks,
                             "asset_url": f"/api/asset/{fi.asset_id}"})
            contract, _ = S.get(con, "contract_revisions", rev["contract_revision_id"])
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            con.close()
        from ..services import review_state as RS
        return {"packet": pkt, "evaluation": ev, "revision": rev, "frames": aids,
                "contract": contract,
                "current_decision": RS.current_state(project_dir, rev["id"])}

    @app.get("/api/asset/{asset_id}")
    def asset(asset_id: str):
        con = S.connect(project_dir)
        try:
            data, _ = S.get(con, "assets", asset_id)
            a = json.loads(data) if isinstance(data, str) else data
            blob = S.blob_path(project_dir, a["byte_sha256"])
            if not blob.is_file():
                raise HTTPException(410, f"asset {asset_id}: blob missing; source sequence retained in store")
            raw = blob.read_bytes()
        except KeyError:
            raise HTTPException(404, f"unknown asset {asset_id}")
        finally:
            con.close()
        return Response(content=raw, media_type="image/png",
                        headers={"Cache-Control": "immutable, max-age=31536000", "X-Asset-ID": asset_id})

    @app.get("/api/corrections", response_model=CorrectionsListDto)
    def corrections(status: str = "open"):
        """Correction queue. Default stays open-only; status=all (or a CSV) keeps
        awaiting-comparison and blocked tasks visible instead of disappearing."""
        from ..services import corrections as C
        if status == "open":
            return C.list_open(project_dir)
        if status == "all":
            return C.list_tasks(project_dir)
        return C.list_tasks(project_dir, [s.strip() for s in status.split(",")])

    @app.post("/api/issues", status_code=201)
    def mark_issue(body: IssueBody, x_session_token: str | None = Header(default=None),
                   x_actor_id: str | None = Header(default=None)):
        """Reviewer marks an ROI/frame-range issue → open CorrectionTask, atomically."""
        act = actor(x_session_token, x_actor_id)
        from ..services import corrections as C
        try:
            env, task = C.open_issue(project_dir, act, {
                "id": body.id, "action": "mark_issue",
                "clip_revision_id": body.clip_revision_id, "packet_id": body.packet_id,
                "frame_instance_id": body.frame_instance_id,
                "frame_range": body.frame_range,
                "roi": body.roi.model_dump() if body.roi else None,
                "note": body.note, "category": body.category})
        except S.ConflictError as e:
            raise HTTPException(409, str(e))
        publish({"type": "issue_marked", "task_id": task.id, "revision_id": body.clip_revision_id})
        return {"event": {"operation_id": env.operation_id,
                          "artifacts": env.artifacts}, "task_id": task.id}

    @app.post("/api/decisions", status_code=201)
    def decision(body: DecisionBody, x_session_token: str | None = Header(default=None),
                 x_actor_id: str | None = Header(default=None)):
        """approve / reject / needs_changes for the exact revision. Reviewer only; never the model."""
        act = actor(x_session_token, x_actor_id)
        from ..services import packets as P
        try:
            out = P.record_decision(project_dir, act, {
                "id": body.id, "action": body.action,
                "clip_revision_id": body.clip_revision_id, "packet_id": body.packet_id,
                "expected_revision_id": body.expected_revision_id,
                "expected_evaluation_id": body.expected_evaluation_id, "note": body.note})
        except S.ConflictError as e:
            raise HTTPException(409, str(e))
        publish({"type": "decision", "action": body.action, "revision_id": body.clip_revision_id})
        return out.model_dump()

    @app.post("/api/issues/{event_id}/resolve", status_code=200)
    def resolve_issue(event_id: str, body: ResolveBody,
                      x_session_token: str | None = Header(default=None),
                      x_actor_id: str | None = Header(default=None)):
        """Resolve the specific issue against a replacement revision. Reviewer only."""
        act = actor(x_session_token, x_actor_id)
        from ..services import corrections as C
        try:
            out = C.resolve_issue(project_dir, act, event_id, body.replacement_revision_id,
                                  body.packet_id, body.note, body.id)
        except S.ConflictError as e:
            raise HTTPException(409, str(e))
        publish({"type": "issue_resolved", "issue": event_id})
        return out

    @app.post("/api/corrections/{task_id}/claim", status_code=200)
    def claim(task_id: str, body: ClaimBody,
              x_session_token: str | None = Header(default=None),
              x_actor_id: str | None = Header(default=None)):
        """Claim an open task. The holder is the authenticated caller, not a body field."""
        from ..services import corrections as C
        try:
            return C.claim(project_dir, actor(x_session_token, x_actor_id), task_id,
                           int(body.expected_version))
        except InvalidInput as e:
            raise HTTPException(409, str(e))

    @app.post("/api/corrections/{task_id}/submit", status_code=201)
    def submit(task_id: str, body: SubmitBody,
               x_session_token: str | None = Header(default=None),
               x_actor_id: str | None = Header(default=None)):
        """Gated repair submit: holder + token + lease + baseline + scope + matrix.

        Unclaimed, foreign-holder, expired-lease and stale-baseline submits are
        refused with 422 and write nothing. Out-of-scope pixels and matrix
        regressions are refused. Failures land as failed attempts (200-class
        envelope with ok:false), never orphaned revisions.
        """
        from ..services import corrections as C
        act = actor(x_session_token, x_actor_id)  # authenticated principal
        try:
            slot_assets = {int(k): v for k, v in (body.slot_assets or {}).items()}
        except ValueError:
            raise HTTPException(422, "slot_assets keys must be integer slot ids")
        try:
            out = C.submit_correction(
                project_dir, act, task_id, claim_token=body.claim_token or "",
                expected_version=int(body.expected_version),
                new_revision_id=body.new_revision_id or f"{task_id}-r1",
                slot_asset_ids=slot_assets, recipe=body.recipe,
                transform=body.transform,
                baseline_evaluation_id=body.baseline_evaluation_id or "",
                idempotency_key=body.idempotency_key or "")
        except S.ConflictError as e:
            raise HTTPException(409, str(e))
        if out.get("ok"):
            publish({"type": "comparison_ready", "task_id": task_id,
                     "revision_id": out.get("revision_id")})
            return out
        return JSONResponse(status_code=200, content=out)

    @app.get("/api/corrections/{task_id}", response_model=TaskStatusDto)
    def correction_get(task_id: str):
        from ..services import corrections as C
        return C.get_task(project_dir, task_id)

    @app.post("/api/masks", status_code=201)
    def mask_approve(body: MaskBody,
                     x_session_token: str | None = Header(default=None),
                     x_actor_id: str | None = Header(default=None)):
        """Reviewer approves an edit mask for an issue. Orchestrators are refused."""
        from ..services import masks as M
        act = actor(x_session_token, x_actor_id)
        mask = M.approve_mask(project_dir, act, body.issue_event_id,
                              body.mask_asset_id, [int(s) for s in body.covered_slots])
        return json.loads(mask.model_dump_json())

    @app.post("/api/issues/{event_id}/reopen", status_code=200)
    def reopen(event_id: str, body: ReopenBody,
               x_session_token: str | None = Header(default=None),
               x_actor_id: str | None = Header(default=None)):
        """Reviewer reopens a resolved issue; the task returns to the queue visibly."""
        from ..services import corrections as C
        return C.reopen_issue(project_dir, actor(x_session_token, x_actor_id),
                              event_id, body.note)

    @app.post("/api/world-trace", status_code=201)
    def world_trace(body: dict):
        """Store frozen per-tick world grounding (positions + planted per tick).

        Length must equal the contract's total held ticks; evaluation binds
        it to world_sliding/declared_contacts instead of passing silently.
        """
        from ..services import clips as _CL
        try:
            wt = _CL.record_world_trace(
                project_dir, str(body.get("revision_id", "")),
                list(body.get("positions", [])), list(body.get("planted", [])),
                str(body.get("units", "world_units")))
        except InvalidInput as e:
            raise HTTPException(422, str(e))
        return json.loads(wt.model_dump_json())

    @app.get("/api/eligibility/{revision_id}", response_model=EligibilityDto)
    def eligibility(revision_id: str):
        from ..services import eligibility as E
        return E.release_eligibility(project_dir, revision_id)

    @app.post("/api/jobs", status_code=201)
    def jobs_submit(body: JobSubmitRequestDto):
        from ..services import jobs as J
        body=body.model_dump()
        try:
            brief = body.get("brief") or {}
            refs = body.get("references") or brief.get("_reference_blobs", [])
            env = J.submit_generation(project_dir, brief, refs,
                                      str(body.get("idempotency_key", "")),
                                      offline=bool(body.get("offline", False)),
            provider_settings=body.get("provider_settings"),
                                      max_attempts=int(body.get("max_attempts", 3)))
        except S.ConflictError as e:
            raise HTTPException(409, str(e))
        return env.model_dump()

    @app.get("/api/jobs/{job_id}")
    def jobs_get(job_id: str):
        from ..services import jobs as J
        try:
            return J.job_get(project_dir, job_id)
        except KeyError:
            raise HTTPException(404, f"unknown job {job_id}")

    @app.post("/api/jobs/{job_id}/claim", status_code=200)
    def jobs_claim(job_id: str, body: dict,
                   x_session_token: str | None = Header(default=None),
                   x_actor_id: str | None = Header(default=None)):
        from ..services import jobs as J
        act = actor(x_session_token, x_actor_id)
        try:
            return J.job_claim(project_dir, job_id, act.id,
                               expected_version=int(body.get("expected_version", 1)))
        except S.StaleRevisionError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/jobs/{job_id}/cancel", status_code=200)
    def jobs_cancel(job_id: str, body: dict,
                    x_session_token: str | None = Header(default=None),
                    x_actor_id: str | None = Header(default=None)):
        from ..services import jobs as J
        actor(x_session_token, x_actor_id)  # authenticated principal
        try:
            return J.job_cancel(project_dir, job_id,
                                int(body.get("expected_version", 1)))
        except S.StaleRevisionError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/jobs/reconcile", status_code=200)
    def jobs_reconcile():
        from ..services import jobs as J
        return J.job_reconcile(project_dir)

    @app.post("/api/orchestrator/runs", status_code=201)
    def orch_runs(body: dict):
        from ..services import orchestrator as O
        return O.start_run(project_dir, list(body.get("job_ids", [])),
                           max_attempts=int(body.get("max_attempts", 3)))

    @app.post("/api/orchestrator/send", status_code=200)
    def orch_send(body: dict,
                  x_session_token: str | None = Header(default=None),
                  x_actor_id: str | None = Header(default=None)):
        from ..services import orchestrator as O
        act = actor(x_session_token, x_actor_id)
        # The executable request is the frozen job row: no caller brief is
        # needed. A supplied brief must fingerprint-match the submission.
        brief = body.get("brief")
        try:
            return O.orchestrator_send(project_dir, str(body.get("run_id")),
                                       str(body.get("job_id")), brief,
                                       worker_id=act.id,
                                       fencing_token=body.get("fencing_token"),
                                       offline=bool(body.get("offline", False)))
        except S.StaleRevisionError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/capabilities")
    def capabilities():
        from ..services import capabilities as C
        return C.table()

    @app.get("/api/compare", response_model=CompareBundleDto)
    def compare(base: str, other: str):
        """Side-by-side comparison bundle: both immutable revisions, media, evals, timing.

        Same contract required (comparison packets enforce it). Frame index
        equality is synchronization only when holds match; otherwise the desk
        must map by elapsed authored time (see timing_note).
        """
        from ..services import packets as _P
        from . import dto as _DTO
        con = S.connect(project_dir)
        try:
            brev, bcontract = _P._resolve_revision(con, base)
            orev, ocontract = _P._resolve_revision(con, other)
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            con.close()
        if bcontract.character_revision_id != ocontract.character_revision_id:
            raise HTTPException(422, "comparison needs one character: "
                                    f"{bcontract.character_revision_id} vs "
                                    f"{ocontract.character_revision_id}")
        if (bcontract.action.name, bcontract.action.view) != (ocontract.action.name, ocontract.action.view):
            raise HTTPException(422, "comparison needs the same action/view: "
                                    f"{bcontract.action.name}/{bcontract.action.view} vs "
                                    f"{ocontract.action.name}/{ocontract.action.view}")
        def side(rev, contract):
            con2 = S.connect(project_dir)
            try:
                latest = _P.latest_evaluation(con2, rev.id)
                frames = []
                for fid in rev.frame_instance_ids:
                    fdata, _ = S.get(con2, "frame_instances", fid)
                    fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
                    frames.append({"frame_instance_id": fi.id, "slot": fi.slot,
                                   "asset_id": fi.asset_id, "phase": fi.phase,
                                   "hold_ticks": fi.hold_ticks,
                                   "asset_url": f"/api/asset/{fi.asset_id}"})
            finally:
                con2.close()
            return {"revision_id": rev.id, "contract_id": contract.id,
                    "evaluation_id": latest.id if latest else None,
                    "technical_status": latest.technical_status.value if latest else "unevaluated",
                    "frames": sorted(frames, key=lambda f: f["slot"]),
                    "holds": contract.timing.holds,
                    "ticks_per_second": contract.timing.ticks_per_second,
                    "loop": contract.action.loop}
        b, o = side(brev, bcontract), side(orev, ocontract)
        equal = (b["holds"] == o["holds"] and
                 b["ticks_per_second"] == o["ticks_per_second"] and b["loop"] == o["loop"])
        return _DTO.CompareBundleDto.model_validate({
            "base": b, "other": o,
            "same_contract": bcontract.id == ocontract.id, "timing_equal": equal,
            "timing_note": ("identical timing: frame index equality is synchronization"
                            if equal else
                            "RETIMED: holds differ; map by elapsed authored time, "
                            f"base total {sum(b['holds'])} vs other total {sum(o['holds'])}")}).model_dump()

    @app.get("/api/issues", response_model=list[IssueDetailDto])
    def issues(revision: str | None = None, packet: str | None = None):
        """Full issue detail: category/ROI/range, attempts, findings, coverage, decision."""
        from ..services import corrections as _C
        from ..services import packets as _P
        from ..services import review_state as _RS
        from . import dto as _DTO
        con = S.connect(project_dir)
        try:
            rows = con.execute(
                "SELECT data FROM review_events ORDER BY data").fetchall()
        finally:
            con.close()
        out = []
        for r in rows:
            raw = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            if raw.get("action") != "mark_issue":
                continue
            if revision and raw.get("clip_revision_id") != revision:
                continue
            if packet and raw.get("packet_id") != packet:
                continue
            ev = D.ReviewEvent.model_validate(raw)
            task = None
            con2 = S.connect(project_dir)
            try:
                for trow in con2.execute("SELECT data FROM correction_tasks").fetchall():
                    t = D.CorrectionTask.model_validate(
                        json.loads(trow["data"]) if isinstance(trow["data"], str) else trow["data"])
                    if t.source_issue_event_id == ev.id:
                        task = t
                        break
                base_ev = _P.latest_evaluation(con2, ev.clip_revision_id)
            finally:
                con2.close()
            attempts = _C._attempts_for(project_dir, task.id) if task else []
            cands = []
            for a in attempts:
                for cid in a.candidate_asset_ids or []:
                    con3 = S.connect(project_dir)
                    try:
                        try:
                            _P._resolve_revision(con3, cid)
                        except Exception:
                            continue
                        latest = _P.latest_evaluation(con3, cid)
                    finally:
                        con3.close()
                    cands.append({"revision_id": cid,
                                  "technical_status": latest.technical_status.value if latest else "unevaluated",
                                  "evaluation_id": latest.id if latest else None,
                                  "attempt_id": a.id, "attempt_result": a.result})
            findings = [x for x in (base_ev.results if base_ev else [])
                        if x.outcome.value in ("fail", "error", "unmeasured")]
            st = _RS.current_state(project_dir, ev.clip_revision_id)
            out.append(_DTO.IssueDetailDto.model_validate({
                "event_id": ev.id, "clip_revision_id": ev.clip_revision_id,
                "packet_id": ev.packet_id, "frame_instance_id": ev.frame_instance_id,
                "frame_range": ev.frame_range,
                "roi": ev.roi.model_dump() if ev.roi else None,
                "category": ev.category, "note": ev.note, "actor_id": ev.actor_id,
                "created_at": ev.created_at,
                "task_id": task.id if task else None,
                "task_status": task.status.value if task else None,
                "lease_valid": _C._lease_valid(task) if task and task.status in (
                    D.CorrectionStatus.CLAIMED, D.CorrectionStatus.ATTEMPTING) else False,
                "attempts": [{"id": a.id, "result": a.result,
                              "candidates": a.candidate_asset_ids or []} for a in attempts],
                "baseline_evaluation_id": task.baseline_evaluation_id if task else None,
                "candidate_revisions": cands,
                "findings": [{"constraint_id": x.constraint_id, "scope": x.scope,
                              "outcome": x.outcome.value, "reason": x.reason} for x in findings],
                "coverage": base_ev.coverage_status.value if base_ev else "unevaluated",
                "current_acceptance": st["acceptance"],
                "resolution_event_id": task.resolution_event_id if task else None}).model_dump())
        return out

    @app.get("/api/packet/{packet_id}/contact-sheet")
    def contact_sheet(packet_id: str):
        """Deterministic contact sheet PNG for a packet's revision (immutable bytes)."""
        import hashlib as _h
        from PIL import Image as _Image
        con = S.connect(project_dir)
        try:
            try:
                pdata, _ = S.get(con, "review_packets", packet_id)
            except KeyError:
                raise HTTPException(404, f"unknown packet {packet_id}")
            pkt = D.ReviewPacket.model_validate_json(json.dumps(pdata))
            rev, _ = S.get(con, "clip_revisions", pkt.clip_revision_id)
            rev = D.ClipRevision.model_validate_json(json.dumps(rev))
            imgs = []
            for fid in rev.frame_instance_ids:
                fdata, _ = S.get(con, "frame_instances", fid)
                fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
                adata, _ = S.get(con, "assets", fi.asset_id)
                raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
                from ..media.canonical import load_native_image
                imgs.append((load_native_image(raw),
                             fi.slot, fi.asset_id))
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            con.close()
        imgs.sort(key=lambda t: t[1])
        cols = 4
        rows = (len(imgs) + cols - 1) // cols
        cw, chh = imgs[0][0].size
        sheet = _Image.new("RGBA", (cols * cw, rows * chh), (0, 0, 0, 0))
        for i, (im, slot, aid) in enumerate(imgs):
            sheet.paste(im, ((i % cols) * cw, (i // cols) * chh))
        buf = __import__("io").BytesIO()
        sheet.save(buf, format="PNG")
        raw = buf.getvalue()
        return Response(content=raw, media_type="image/png",
                        headers={"Cache-Control": "immutable, max-age=31536000",
                                 "X-Content-SHA256": _h.sha256(raw).hexdigest(),
                                 "X-Revision-ID": rev.id, "X-Slots": str(len(imgs))})

    @app.post("/api/packet/{packet_id}/preview", status_code=201)
    def packet_preview(packet_id: str):
        """Deterministic frame->time video preview (PNG sequence is source truth).

        Holds expand to repeated frames at the contract tick rate. 501 when no
        ffmpeg binary is available; never a fake video.
        """
        import shutil as _sh, subprocess as _sp, tempfile as _tf
        if _sh.which("ffmpeg") is None:
            raise HTTPException(501, "ffmpeg unavailable: video preview unsupported here")
        from ..services import packets as _P
        con = S.connect(project_dir)
        try:
            try:
                pdata, _ = S.get(con, "review_packets", packet_id)
            except KeyError:
                raise HTTPException(404, f"unknown packet {packet_id}")
            pkt = D.ReviewPacket.model_validate_json(json.dumps(pdata))
            rev, contract = _P._resolve_revision(con, pkt.clip_revision_id)
            seq = []
            for fid in rev.frame_instance_ids:
                fdata, _ = S.get(con, "frame_instances", fid)
                fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
                adata, _ = S.get(con, "assets", fi.asset_id)
                seq.append((fi.slot, adata["byte_sha256"], fi.hold_ticks))
        except KeyError as e:
            raise HTTPException(404, str(e))
        finally:
            con.close()
        seq.sort(key=lambda t: t[0])
        work = Path(_tf.mkdtemp(prefix="fb-preview-"))
        try:
            n = 0
            for slot, digest, hold in seq:
                raw = S.blob_path(project_dir, digest).read_bytes()
                for _ in range(hold):
                    (work / f"f{n:05d}.png").write_bytes(raw)
                    n += 1
            tps = contract.timing.ticks_per_second
            out = work / "preview.mp4"
            cmd = ["ffmpeg", "-y", "-framerate", str(tps), "-i", str(work / "f%05d.png"),
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
            r = _sp.run(cmd, capture_output=True, timeout=180)
            if r.returncode != 0 or not out.is_file():
                raise HTTPException(502, f"ffmpeg failed: {r.stderr.decode()[-500:]}")
            data = out.read_bytes()
            import hashlib as _h
            dest_dir = Path(project_dir) / "previews"
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / f"{packet_id}.mp4"
            dest.write_bytes(data)
            (dest_dir / f"{packet_id}.json").write_text(json.dumps(
                {"packet_id": packet_id, "revision_id": rev.id, "frames": n,
                 "ticks_per_second": tps, "total_ticks": n,
                 "ffmpeg_command": " ".join(cmd),
                 "content_sha256": _h.sha256(data).hexdigest()}) + "\n")
        finally:
            __import__("shutil").rmtree(work, ignore_errors=True)
        import hashlib as _hh
        return {"packet_id": packet_id, "revision_id": rev.id,
                "artifact": f"previews/{packet_id}.mp4",
                "video_url": f"/api/previews/{packet_id}.mp4",
                "frames": n, "ticks_per_second": tps, "total_ticks": n,
                "ffmpeg_command": " ".join(cmd),
                "content_sha256": _hh.sha256(data).hexdigest()}

    @app.get("/api/previews/{packet_id}.mp4")
    def preview_file(packet_id: str):
        p = Path(project_dir) / "previews" / f"{packet_id}.mp4"
        if not p.is_file():
            raise HTTPException(404, f"no preview for packet {packet_id}")
        return Response(content=p.read_bytes(), media_type="video/mp4",
                        headers={"Cache-Control": "immutable, max-age=31536000"})

    @app.get("/api/activity", response_model=ActivityPageDto)
    def activity(since: str = "", limit: int = 200):
        """DB-backed activity log with cursor catch-up (survives restarts; SSE does not)."""
        from . import dto as _DTO
        con = S.connect(project_dir)
        try:
            rows = con.execute("SELECT data FROM review_events").fetchall()
        finally:
            con.close()
        evs = []
        for r in rows:
            raw = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            try:
                evs.append(D.ReviewEvent.model_validate(raw))
            except Exception:
                continue
        evs.sort(key=lambda e: (e.created_at, e.id))
        if since:
            idx = next((i for i, e in enumerate(evs) if e.id == since), None)
            evs = evs[idx + 1:] if idx is not None else evs
        page = evs[:max(1, min(limit, 500))]
        return _DTO.ActivityPageDto.model_validate({
            "events": [{"id": e.id, "action": e.action, "actor_type": e.actor_type,
                        "actor_id": e.actor_id, "clip_revision_id": e.clip_revision_id,
                        "packet_id": e.packet_id, "created_at": e.created_at,
                        "note": e.note} for e in page],
            "cursor": page[-1].id if page else (since or None)}).model_dump()

    @app.post("/api/exports", status_code=201, response_model=ExportResultDto)
    def exports_build(body: dict):
        """Build a portable training snapshot through the desk (R5 semantics)."""
        from ..exports import build_snapshot, validate_snapshot
        name = str(body.get("name") or "").strip()
        revs = body.get("revisions") or []
        policy = body.get("policy") or {}
        if not name or not revs:
            raise HTTPException(422, "exports needs a name and a revision list")
        out = str(Path(project_dir) / "exports" / name)
        try:
            man = build_snapshot(project_dir, name, list(revs), out, dict(policy))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except (S.ConflictError, FileExistsError, ValueError) as e:
            raise HTTPException(409, str(e))
        rep = validate_snapshot(out)
        return {"name": name, "ok": rep["ok"], "issues": rep["issues"],
                "skipped": rep.get("skipped", []), "counts": rep["counts"],
                "exclusions": rep["exclusions"]}

    @app.get("/api/exports/{name}", response_model=ExportResultDto)
    def exports_get(name: str):
        """Revalidate a desk-built export in place."""
        from ..exports import validate_snapshot
        out = Path(project_dir) / "exports" / name
        if not (out / "manifest.json").is_file():
            raise HTTPException(404, f"unknown export {name}")
        rep = validate_snapshot(str(out))
        return {"name": name, "ok": rep["ok"], "issues": rep["issues"],
                "skipped": rep.get("skipped", []), "counts": rep["counts"],
                "exclusions": rep["exclusions"]}

    @app.get("/api/events")
    async def events():
        q: asyncio.Queue = asyncio.Queue()
        app.state.subscribers.append(q)

        async def gen():
            try:
                while True:
                    msg = await q.get()
                    yield f"data: {json.dumps(msg)}\n\n"
            finally:
                app.state.subscribers.remove(q)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/build-identity")
    def build_identity():
        from ..checks import evaluate as _EV
        ident = _EV.lock_identity()
        desk = _desk_dir() is not None
        return {"lock": ident, "desk_build_present": desk,
                "schema_version": "2.0"}

    # Serve the built review desk LAST so the "/" mount cannot shadow /api routes.
    dist = _desk_dir()
    if dist is not None:
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="desk")
    return app


def _desk_dir():
    """Resolve the review-desk build without searching unrelated parents.

    Prefer a freshly built source checkout over an older wheel staging copy.
    Installed wheels use `framebound/desk`, with a source-layout fallback.
    Returns None when
    neither exists so / returns 404 JSON instead of an unrelated directory.
    """
    root = Path(__file__).resolve().parents[3]
    candidate = root / "web" / "dist"
    if (root / ".git").exists() and (root / "web" / "package.json").is_file() and (candidate / "index.html").is_file():
        return candidate
    try:
        from importlib import resources as _res
        desk = _res.files("framebound") / "desk" / "index.html"
        if desk.is_file():
            return desk.parent
    except Exception:
        pass
    if (candidate / "index.html").is_file():
        return candidate
    return None
