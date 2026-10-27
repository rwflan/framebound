"""Correction tasks: atomic issue+task creation, holder-bound claims, explicit resolution.

All multi-record transitions commit as one unit. A fault between the issue
event and its task (or between resolution and the task update) rolls back
instead of leaving orphaned rows.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from .. import domain as D
from .. import storage as S
from . import packets as P
from .authz import Actor, require_reviewer
from .errors import InvalidInput


def open_task(project_dir: str, task: D.CorrectionTask) -> None:
    con = S.connect(project_dir)
    try:
        S.insert(con, task)
    finally:
        con.close()


def list_open(project_dir: str) -> dict:
    con = S.connect(project_dir)
    try:
        rows = con.execute("SELECT data FROM correction_tasks").fetchall()
    finally:
        con.close()
    tasks = [json.loads(r["data"]) for r in rows]
    open_tasks = [t for t in tasks if t["status"] in ("open", "reopened")]
    return {"open": open_tasks, "count": len(open_tasks)}


def open_issue(project_dir: str, actor: Actor, event: dict) -> tuple[D.ResultEnvelope, D.CorrectionTask]:
    """Record a mark_issue event and open its correction task atomically."""
    if event.get("action", "mark_issue") != "mark_issue":
        raise InvalidInput("open_issue only records mark_issue events")
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            stored = P._stage_event(con, project_dir, actor, event)
            try:
                tdata, _ = S.get(con, "correction_tasks", f"task-{stored.id}")
                task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
                dup = True
            except KeyError:
                task = D.CorrectionTask(
                    id=f"task-{stored.id}", source_issue_event_id=stored.id,
                    baseline_revision_id=stored.clip_revision_id,
                    desired_outcome=stored.note or stored.category,
                    scope=json.dumps({"frame_range": stored.frame_range,
                                      "roi": stored.roi.model_dump() if stored.roi else None,
                                      "frame_instance_id": stored.frame_instance_id,
                                      "category": stored.category}))
                S.stage(con, task)
                dup = False
    finally:
        con.close()
    env = D.ResultEnvelope(ok=True, operation_id=f"op-event-{stored.id}",
                           revision_id=stored.clip_revision_id, next_actions=["corrections_list"])
    if dup:
        env.artifacts.append({"id": stored.id, "role": "review_event", "deduped": True})
    return env, task


def claim(project_dir: str, actor: Actor, task_id: str, expected_version: int,
          lease_minutes: int = 30) -> dict:
    """Claim an open task. The holder is the authenticated caller, and a claim
    token (shown once) must be presented at submit time (enforced in R4)."""
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "correction_tasks", task_id)
        task = D.CorrectionTask.model_validate_json(json.dumps(data))
        if task.status not in (D.CorrectionStatus.OPEN, D.CorrectionStatus.REOPENED):
            raise InvalidInput(f"task {task_id} is {task.status}, not claimable")
        token = secrets.token_hex(16)
        import hashlib as _h
        task.status = D.CorrectionStatus.CLAIMED
        task.claim_holder = actor.id
        task.claim_token_sha256 = _h.sha256(token.encode()).hexdigest()
        task.claim_lease = (datetime.now(timezone.utc)
                            + timedelta(minutes=lease_minutes)).isoformat()
        with S.atomic(con):
            nv = S.stage_update(con, "correction_tasks", task, expected_version)
    finally:
        con.close()
    return {"task_id": task_id, "status": "claimed", "holder": actor.id,
            "claim_token": token, "lease": task.claim_lease, "version": nv}


def resolve_issue(project_dir: str, actor: Actor, issue_event_id: str,
                  replacement_revision_id: str, packet_id: str | None = None,
                  note: str = "", event_id: str | None = None) -> dict:
    """Resolve the exact source issue against a same-contract replacement."""
    require_reviewer(actor, "resolve_issue")
    con = S.connect(project_dir)
    try:
        try:
            idata, _ = S.get(con, "review_events", issue_event_id)
        except KeyError:
            raise InvalidInput(f"unknown issue event {issue_event_id}")
        issue = D.ReviewEvent.model_validate_json(json.dumps(idata))
        if issue.action != "mark_issue":
            raise InvalidInput(f"event {issue_event_id} is {issue.action}, not an openable issue")
        task = None
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            t = D.CorrectionTask.model_validate_json(r["data"])
            if t.source_issue_event_id == issue_event_id:
                task = t
                break
        if task is None:
            raise InvalidInput(f"no correction task for issue {issue_event_id}")
        if task.status == D.CorrectionStatus.RESOLVED:
            return {"ok": True, "resolution_event_id": task.resolution_event_id, "deduped": True}
        base_rev, _ = P._resolve_revision(con, issue.clip_revision_id)
        new_rev, _ = P._resolve_revision(con, replacement_revision_id)
        if new_rev.contract_revision_id != base_rev.contract_revision_id:
            raise InvalidInput("replacement is from a different contract: not a resolution of this issue")
        if packet_id:
            P._check_packet_addresses(con, packet_id, replacement_revision_id)
        eid = event_id or f"evt-res-{uuid.uuid4().hex[:12]}"
        with S.atomic(con):
            try:
                edata, _ = S.get(con, "review_events", eid)
                existing = D.ReviewEvent.model_validate_json(json.dumps(edata))
                if existing.action != "resolve_issue" or \
                        existing.clip_revision_id != replacement_revision_id:
                    raise S.ConflictError(f"event id {eid} already recorded differently")
                rid = existing.id
            except KeyError:
                rev_ev = D.ReviewEvent(id=eid, actor_type="reviewer", actor_id=actor.id,
                                       action="resolve_issue",
                                       clip_revision_id=replacement_revision_id,
                                       packet_id=packet_id, note=note)
                S.stage(con, rev_ev)
                rid = eid
            data, ver = S.get(con, "correction_tasks", task.id)
            t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
            if t2.status != D.CorrectionStatus.RESOLVED:
                t2.status = D.CorrectionStatus.RESOLVED
                t2.resolution_event_id = rid
                S.stage_update(con, "correction_tasks", t2, ver)
    finally:
        con.close()
    return {"ok": True, "resolution_event_id": rid}
