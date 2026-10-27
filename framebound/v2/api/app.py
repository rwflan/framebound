"""FastAPI review API. Human writes require a reviewer session token; orchestrator tokens get 403.

Reviewer sessions come from an explicit localhost pairing ceremony
(`framebound reviewer-pair` / `reviewer-open`, or POST /api/reviewer/*):
nobody becomes a reviewer by setting a request header. Reads and the model
queue (GET /api/corrections) stay open to the orchestrator. Mutating the same
revision concurrently is refused; stale views yield 409 stale_revision.
Binds 127.0.0.1 by default; a remotely exposed writer needs real authentication
(P0: local only).

Threat boundary: these checks protect the API transport. A process with
unrestricted filesystem access to the project database can rewrite it
directly; no HTTP role check claims to prevent that.
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

from .. import domain as D
from .. import storage as S
from ..services.authz import Actor
from ..services.errors import AuthorizationError, InvalidInput, StaleRevision as SvcStale


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


class PairBody(D.Strict):
    reviewer_id: str = Field(min_length=1, max_length=200)


class OpenBody(D.Strict):
    pairing_code: str = Field(min_length=1, max_length=256)


def create_app(project_dir: str) -> FastAPI:
    app = FastAPI(title="Framebound v2 review API", version="2.0.0a1")
    app.state.project_dir = project_dir

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

    @app.post("/api/reviewer/pair", status_code=201)
    def reviewer_pair(body: PairBody):
        """Local operator pairs a human reviewer id; returns a single-use code."""
        from ..services import sessions as SN
        try:
            return SN.pair_reviewer(project_dir, body.reviewer_id)
        except InvalidInput as e:
            raise HTTPException(422, str(e))

    @app.post("/api/reviewer/open", status_code=201)
    def reviewer_open(body: OpenBody):
        """Exchange a pairing code for a reviewer session token (shown once)."""
        from ..services import sessions as SN
        try:
            return SN.open_session(project_dir, body.pairing_code)
        except AuthorizationError as e:
            raise HTTPException(403, str(e))
        except InvalidInput as e:
            raise HTTPException(422, str(e))

    @app.get("/api/project")
    def project():
        from ..services import projects
        return {"summary": projects.get_summary(project_dir)}

    @app.get("/api/packets")
    def packets():
        con = S.connect(project_dir)
        try:
            rows = con.execute("SELECT data FROM review_packets").fetchall()
            return {"packets": [json.loads(r["data"]) for r in rows]}
        finally:
            con.close()

    @app.get("/api/packet/{packet_id}")
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
                             "phase": fi.phase, "hold_ticks": fi.hold_ticks})
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

    @app.get("/api/corrections")
    def corrections():
        from ..services import corrections as C
        return C.list_open(project_dir)

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
        """Orchestrator submits a replacement: child revision + evaluation + comparison packet."""
        actor(x_session_token, x_actor_id)  # authenticated principal; lease checks land in R4
        from ..services import clips
        con = S.connect(project_dir)
        try:
            tdata, tver = S.get(con, "correction_tasks", task_id)
            task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
        except KeyError:
            raise HTTPException(404, "unknown correction task")
        finally:
            con.close()
        try:
            slot_assets = {int(k): v for k, v in (body.slot_assets or {}).items()}
        except ValueError:
            raise HTTPException(422, "slot_assets keys must be integer slot ids")
        recipe = body.recipe
        new_id = body.new_revision_id or f"{task.baseline_revision_id}-r1"
        try:
            out = clips.register_candidate(project_dir, task.baseline_revision_id, new_id,
                                           slot_assets, recipe)
        except S.ConflictError as e:
            raise HTTPException(409, str(e))
        ev_out = clips.evaluate(project_dir, new_id)
        from ..services import packets as P
        pkt = P.create_packet(project_dir, f"pkt-{new_id}", new_id,
                              ev_out.artifacts[0]["id"] if ev_out.artifacts else new_id,
                              f"correction for {task_id}", comparison_revision_id=task.baseline_revision_id)
        con = S.connect(project_dir)
        try:
            data, ver = S.get(con, "correction_tasks", task_id)
            t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
            t2.status = D.CorrectionStatus.AWAITING_COMPARISON
            t2.attempt_ids = [*t2.attempt_ids, new_id]
            with S.atomic(con):
                S.stage_update(con, "correction_tasks", t2, ver)
        finally:
            con.close()
        publish({"type": "comparison_ready", "task_id": task_id, "revision_id": new_id})
        return {"revision": out.model_dump(), "evaluation": ev_out.model_dump(), "packet": pkt.model_dump()}

    @app.post("/api/jobs", status_code=201)
    def jobs_submit(body: dict):
        from ..services import jobs as J
        try:
            brief = body.get("brief") or {}
            refs = body.get("references") or brief.get("_reference_blobs", [])
            env = J.submit_generation(project_dir, brief, refs,
                                      str(body.get("idempotency_key", "")),
                                      offline=bool(body.get("offline", False)),
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
        brief = body.get("brief") or {}
        try:
            return O.orchestrator_send(project_dir, str(body.get("run_id")),
                                       str(body.get("job_id")), brief,
                                       worker_id=act.id,
                                       offline=bool(body.get("offline", False)))
        except S.StaleRevisionError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/capabilities")
    def capabilities():
        from ..services import capabilities as C
        return C.table()

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

    # Serve the built review desk LAST so the "/" mount cannot shadow /api routes.
    dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="desk")
    return app
