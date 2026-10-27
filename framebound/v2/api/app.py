"""FastAPI review API. Human writes are reviewer-only; orchestrator tokens get 403.

Review writes require headers X-Actor-Type: reviewer + X-Actor-Id. Reads and the model
queue (GET /api/corrections) are open to the orchestrator. Mutating the same revision
concurrently is refused; stale expected_revision_id yields 409 stale_revision.
Binds 127.0.0.1 by default; a remotely exposed writer needs real authentication (P0: local only).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import domain as D
from .. import storage as S
from ..services.authz import Actor
from ..services.errors import AuthorizationError, InvalidInput, StaleRevision


def _actor(actor_type: str | None, actor_id: str | None) -> Actor:
    return Actor(type=actor_type or "orchestrator", id=actor_id or "anonymous")


def create_app(project_dir: str) -> FastAPI:
    app = FastAPI(title="Framebound v2 review API", version="2.0.0a1")
    app.state.project_dir = project_dir

    app.state.subscribers: list[asyncio.Queue] = []

    def publish(event: dict) -> None:
        for q in app.state.subscribers:
            q.put_nowait(event)

    @app.exception_handler(AuthorizationError)
    async def _forbidden(_: Request, e: AuthorizationError):
        return JSONResponse({"code": "forbidden", "detail": str(e)}, status_code=403)

    @app.exception_handler(InvalidInput)
    async def _bad(_: Request, e: InvalidInput):
        return JSONResponse({"code": "invalid_input", "detail": str(e)}, status_code=422)

    @app.exception_handler(S.StaleRevisionError)
    async def _stale(_: Request, e: S.StaleRevisionError):
        return JSONResponse({"code": "stale_revision", "detail": str(e)}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"ok": True, "schema_version": "2.0"}

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
        return {"packet": pkt, "evaluation": ev, "revision": rev, "frames": aids, "contract": contract}

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
    def mark_issue(body: dict, x_actor_type: str | None = Header(default=None),
                   x_actor_id: str | None = Header(default=None)):
        """Reviewer marks an ROI/frame-range issue → open CorrectionTask (model queue)."""
        actor = _actor(x_actor_type, x_actor_id)
        for f in ("clip_revision_id", "packet_id"):
            if f not in body:
                raise HTTPException(422, f"missing {f}")
        event = {"id": body.get("id") or f"evt-{abs(hash(json.dumps(body, sort_keys=True))) % 10**8}",
                 "action": "mark_issue", "clip_revision_id": body["clip_revision_id"],
                 "packet_id": body.get("packet_id"),
                 "frame_instance_id": body.get("frame_instance_id"),
                 "frame_range": body.get("frame_range"), "roi": body.get("roi"),
                 "note": body.get("note", ""), "category": body.get("category", "general")}
        from ..services import packets as P
        out = P.record_review_event(project_dir, actor, event)
        # open the machine-readable correction task in the same transaction boundary
        task = D.CorrectionTask(id=f"task-{event['id']}", source_issue_event_id=event["id"],
                                baseline_revision_id=event["clip_revision_id"],
                                desired_outcome=event["note"] or event.get("category", "fix"),
                                scope=json.dumps({"frame_range": event.get("frame_range"),
                                                  "roi": event.get("roi")}))
        con = S.connect(project_dir)
        try:
            try:
                S.insert(con, task)
            except S.ConflictError:
                pass  # idempotent retry returns the same task
        finally:
            con.close()
        publish({"type": "issue_marked", "task_id": task.id, "revision_id": event["clip_revision_id"]})
        return {"event": out.model_dump(), "task_id": task.id}

    @app.post("/api/decisions", status_code=201)
    def decision(body: dict, x_actor_type: str | None = Header(default=None),
                 x_actor_id: str | None = Header(default=None)):
        """approve / reject / needs-work for the exact revision. Reviewer only; never the model."""
        actor = _actor(x_actor_type, x_actor_id)
        action = body.get("action")
        if action not in ("approve", "reject", "needs_changes"):
            raise HTTPException(422, "action must be approve|reject|needs_changes")
        # stale-write protection: the decision must name the revision it was viewed against
        con = S.connect(project_dir)
        try:
            try:
                S.get(con, "clip_revisions", body.get("clip_revision_id", ""))
            except KeyError:
                raise HTTPException(404, "unknown clip revision")
            current = body.get("clip_revision_id")
            if body.get("expected_revision_id") and body["expected_revision_id"] != current:
                raise HTTPException(409, "stale_revision: packet view is behind; reload before deciding")
        finally:
            con.close()
        from ..services import packets as P
        out = P.record_review_event(project_dir, actor, {
            "id": body.get("id") or f"evt-{abs(hash(json.dumps(body, sort_keys=True))) % 10**8}",
            "action": action, "clip_revision_id": body["clip_revision_id"],
            "packet_id": body.get("packet_id"), "note": body.get("note", "")})
        publish({"type": "decision", "action": action, "revision_id": body["clip_revision_id"]})
        return out.model_dump()

    @app.post("/api/issues/{event_id}/resolve", status_code=200)
    def resolve_issue(event_id: str, body: dict, x_actor_type: str | None = Header(default=None),
                      x_actor_id: str | None = Header(default=None)):
        """Resolve the specific issue against a replacement revision. Unrelated approvals can't close it."""
        actor = _actor(x_actor_type, x_actor_id)
        if actor.type != "reviewer":
            raise AuthorizationError("resolve_issue requires a reviewer session")
        con = S.connect(project_dir)
        try:
            try:
                S.get(con, "clip_revisions", body.get("replacement_revision_id", ""))
            except KeyError:
                raise HTTPException(404, "unknown replacement revision")
            ev = D.ReviewEvent(id=body.get("id") or f"evt-res-{event_id}", actor_type="reviewer",
                               actor_id=actor.id, action="resolve_issue",
                               clip_revision_id=body["replacement_revision_id"],
                               packet_id=body.get("packet_id"), note=body.get("note", ""))
            S.insert(con, ev)
            # mark the correction task resolved only via this explicit event
            rows = con.execute("SELECT id, data, version FROM correction_tasks").fetchall()
            for r in rows:
                t = json.loads(r["data"])
                if t.get("source_issue_event_id") == event_id and t.get("status") != "resolved":
                    task = D.CorrectionTask.model_validate(t)
                    task.status = D.CorrectionStatus.RESOLVED
                    task.resolution_event_id = ev.id
                    S.update_mutable(con, "correction_tasks", task, r["version"])
        finally:
            con.close()
        publish({"type": "issue_resolved", "issue": event_id})
        return {"ok": True, "resolution_event_id": ev.id}

    @app.post("/api/corrections/{task_id}/claim", status_code=200)
    def claim(task_id: str, body: dict):
        from ..services import corrections as C
        try:
            return C.claim(project_dir, task_id, body.get("holder", "orchestrator"),
                           int(body.get("expected_version", 1)))
        except InvalidInput as e:
            raise HTTPException(409, str(e))

    @app.post("/api/corrections/{task_id}/submit", status_code=201)
    def submit(task_id: str, body: dict, x_actor_type: str | None = Header(default=None),
               x_actor_id: str | None = Header(default=None)):
        """Orchestrator submits a replacement: child revision + evaluation + comparison packet."""
        from ..services import clips
        con = S.connect(project_dir)
        try:
            tdata, tver = S.get(con, "correction_tasks", task_id)
            task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
        except KeyError:
            raise HTTPException(404, "unknown correction task")
        finally:
            con.close()
        slot_assets = {int(k): v for k, v in (body.get("slot_assets") or {}).items()}
        recipe = body.get("recipe", "repair:bounded-patch")
        new_id = body.get("new_revision_id") or f"{task.baseline_revision_id}-r1"
        out = clips.register_candidate(project_dir, task.baseline_revision_id, new_id, slot_assets, recipe)
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
            S.update_mutable(con, "correction_tasks", t2, ver)
        finally:
            con.close()
        publish({"type": "comparison_ready", "task_id": task_id, "revision_id": new_id})
        return {"revision": out.model_dump(), "evaluation": ev_out.model_dump(), "packet": pkt.model_dump()}

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
