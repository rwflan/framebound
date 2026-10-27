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
    """Record a mark_issue event and open its correction task atomically.

    The task binds the current baseline evidence: corrections need something
    trustworthy to repair from, and the submit gate later refuses stale views.
    """
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
                base_ev = P.latest_evaluation(con, stored.clip_revision_id)
                if base_ev is None:
                    raise InvalidInput(
                        f"cannot open an issue on {stored.clip_revision_id}: "
                        "no stored evaluation to repair from")
                task = D.CorrectionTask(
                    id=f"task-{stored.id}", source_issue_event_id=stored.id,
                    baseline_revision_id=stored.clip_revision_id,
                    baseline_evaluation_id=base_ev.id,
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


# ---------------------------------------------------------------- R4: gated submit

MAX_CORRECTION_ATTEMPTS = 3


def _lease_valid(task: D.CorrectionTask) -> bool:
    if not task.claim_lease:
        return False
    try:
        exp = datetime.fromisoformat(task.claim_lease)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > datetime.now(timezone.utc)
    except Exception:
        return False


def _attempts_for(project_dir: str, task_id: str) -> list[D.Attempt]:
    con = S.connect(project_dir)
    try:
        out = []
        for r in con.execute("SELECT data FROM attempts").fetchall():
            try:
                a = D.Attempt.model_validate_json(r["data"])
            except Exception:
                continue
            if a.brief_id == task_id:
                out.append(a)
        return out
    finally:
        con.close()


def get_task(project_dir: str, task_id: str) -> dict:
    """Explicit status for every correction state; lease validity resolved."""
    con = S.connect(project_dir)
    try:
        try:
            tdata, ver = S.get(con, "correction_tasks", task_id)
        except KeyError:
            raise InvalidInput(f"unknown correction task {task_id}")
        task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
        try:
            idata, _ = S.get(con, "review_events", task.source_issue_event_id)
            issue = idata
        except KeyError:
            issue = None
    finally:
        con.close()
    attempts = _attempts_for(project_dir, task_id)
    return {"task": json.loads(task.model_dump_json()), "version": ver,
            "lease_valid": _lease_valid(task) if task.status in (
                D.CorrectionStatus.CLAIMED, D.CorrectionStatus.ATTEMPTING) else False,
            "attempts": [{"id": a.id, "result": a.result,
                          "candidates": a.candidate_asset_ids} for a in attempts],
            "issue": issue}


def list_tasks(project_dir: str, statuses: list[str] | None = None) -> dict:
    con = S.connect(project_dir)
    try:
        rows = con.execute("SELECT data FROM correction_tasks").fetchall()
    finally:
        con.close()
    tasks = [json.loads(r["data"]) for r in rows]
    if statuses is not None:
        tasks = [t for t in tasks if t["status"] in set(statuses)]
    return {"tasks": tasks, "count": len(tasks)}


def _requeue_if_expired(project_dir: str, con, task: D.CorrectionTask, ver: int) -> None:
    """Expired claims return to OPEN with attempts intact; nothing is discarded."""
    if task.status in (D.CorrectionStatus.CLAIMED, D.CorrectionStatus.ATTEMPTING) \
            and not _lease_valid(task):
        task.status = D.CorrectionStatus.OPEN
        task.claim_holder = None
        task.claim_token_sha256 = None
        task.claim_lease = None
        task.last_error = "claim lease expired; task requeued, attempts preserved"
        S.stage_update(con, "correction_tasks", task, ver)


def _payload_hash(payload: dict) -> str:
    import hashlib as _h
    return _h.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def submit_correction(project_dir: str, actor: Actor, task_id: str, *,
                      claim_token: str, expected_version: int,
                      new_revision_id: str, slot_asset_ids: dict[int, str],
                      recipe: str, transform: dict | None = None,
                      baseline_evaluation_id: str,
                      idempotency_key: str) -> dict:
    """The single gated repair use case used by every transport.

    Verifies holder identity, claim token, lease, task state and baseline
    evidence before any write; routes replacements through pixel-scope and
    full-matrix selection; commits candidate+attempt+packet+task idempotently.
    Failures land as failed attempts, never orphaned revisions or lost tasks.
    """
    import hashlib as _h
    from . import clips as _clips
    from . import repair as _R
    if not claim_token or not idempotency_key or not new_revision_id:
        raise InvalidInput("submit needs claim_token, idempotency_key and new_revision_id")
    if not isinstance(slot_asset_ids, dict) or not slot_asset_ids:
        raise InvalidInput("submit needs a non-empty slot_asset_ids map")
    slots: dict[int, str] = {}
    for k, v in slot_asset_ids.items():
        try:
            s = int(k)
        except (TypeError, ValueError):
            raise InvalidInput(f"slot key {k!r} is not an integer slot id")
        if isinstance(s, bool) or s < 0 or not isinstance(v, str) or not v:
            raise InvalidInput(f"slot entry {k!r} is not a valid slot->asset mapping")
        slots[s] = v
    att_id = f"att-{_h.sha256(f'{task_id}:{idempotency_key}'.encode()).hexdigest()[:24]}"
    payload_hash = _payload_hash({"slots": slots, "recipe": recipe,
                                  "transform": transform,
                                  "baseline_evaluation_id": baseline_evaluation_id,
                                  "new_revision_id": new_revision_id})
    con = S.connect(project_dir)
    try:
        try:
            tdata, ver = S.get(con, "correction_tasks", task_id)
        except KeyError:
            raise InvalidInput(f"unknown correction task {task_id}")
        task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
        # crash-recovery idempotency first: the same key+payload replays the
        # stored result instead of conflicting on already-written rows, even
        # when the caller retries with a stale expected version.
        try:
            adata, _ = S.get(con, "attempts", att_id)
            prior = D.Attempt.model_validate_json(json.dumps(adata))
            if prior.no_progress_signature != payload_hash:
                raise S.ConflictError(
                    f"idempotency key already used with a different payload for {task_id}")
            return _replay_submit(project_dir, task, prior)
        except KeyError:
            pass
        if ver != expected_version:
            raise S.StaleRevisionError(
                f"stale_revision: correction_tasks/{task_id} at version {ver}, "
                f"writer expected {expected_version}")
        if task.status not in (D.CorrectionStatus.CLAIMED, D.CorrectionStatus.ATTEMPTING):
            raise InvalidInput(f"task {task_id} is {task.status.value}: claim it before submitting")
        if task.claim_holder != actor.id:
            raise InvalidInput(f"task {task_id} is claimed by {task.claim_holder}, "
                               f"not {actor.id}: foreign-holder submit refused")
        if not task.claim_token_sha256 or \
                _h.sha256(claim_token.encode()).hexdigest() != task.claim_token_sha256:
            raise InvalidInput("claim token mismatch: submit refused")
        if not _lease_valid(task):
            with S.atomic(con):
                data, v2 = S.get(con, "correction_tasks", task_id)
                t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
                _requeue_if_expired(project_dir, con, t2, v2)
            raise InvalidInput("claim lease expired: task requeued to open, attempts preserved")
        if task.baseline_evaluation_id != baseline_evaluation_id:
            raise InvalidInput(f"stale baseline: task binds {task.baseline_evaluation_id}, "
                               f"submit presents {baseline_evaluation_id}")
        base_ev = P.latest_evaluation(con, task.baseline_revision_id)
        if base_ev is None or base_ev.id != task.baseline_evaluation_id:
            raise InvalidInput("baseline evidence superseded since the claim: re-claim first")
        budget = [a for a in _attempts_for(project_dir, task_id)
                  if (a.result or "").startswith("failed")]
        if len(budget) >= MAX_CORRECTION_ATTEMPTS:
            with S.atomic(con):
                data, v2 = S.get(con, "correction_tasks", task_id)
                t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
                t2.status = D.CorrectionStatus.BLOCKED
                t2.last_error = f"attempt budget exhausted ({len(budget)} failures)"
                S.stage_update(con, "correction_tasks", t2, v2)
            raise InvalidInput(f"task {task_id} is blocked: attempt budget exhausted")
    finally:
        con.close()
    # Pixel scope BEFORE any write: the 1x1-ROI whole-frame swap dies here.
    scope = _R.verify_scope(project_dir, task.baseline_revision_id, slots, task)
    # Register + evaluate (each step idempotent: retries converge).
    try:
        _clips.register_candidate(project_dir, task.baseline_revision_id,
                                  new_revision_id, slots, recipe,
                                  transform=transform)
    except S.ConflictError as e:
        raise InvalidInput(f"candidate registration refused: {e}")
    cand_env = _clips.evaluate(project_dir, new_revision_id)
    cand_ev_id = cand_env.artifacts[0]["id"]
    con = S.connect(project_dir)
    try:
        bdata, _ = S.get(con, "contract_revisions",
                          P._resolve_revision(con, task.baseline_revision_id)[1].id)
        base_contract = D.ClipContractRevision.model_validate_json(json.dumps(bdata))
        cdata, _ = S.get(con, "contract_revisions",
                          P._resolve_revision(con, new_revision_id)[1].id)
        cand_contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        cand_ev = D.Evaluation.model_validate_json(
            json.dumps(S.get(con, "evaluations", cand_ev_id)[0]))
    finally:
        con.close()
    required_ids = {c.id for c in base_contract.constraints if c.required}
    base_targets = sorted({r.constraint_id for r in base_ev.results
                           if r.outcome in ("fail", "error")
                           and r.constraint_id in required_ids})
    subjective = base_ev.technical_status == D.TechnicalStatus.PASS
    sel = _R.evaluate_selection(base_ev, cand_ev, base_targets, subjective=subjective,
                                baseline_contract=base_contract,
                                candidate_contract=cand_contract)
    pkt = None
    if sel.get("selected"):
        # Idempotent on its own transaction: retries converge instead of
        # conflicting, and no nested connection ever blocks the atomic block.
        pkt = P.create_packet(project_dir, f"pkt-{new_revision_id}", new_revision_id,
                              cand_ev_id,
                              f"correction for {task_id}: {task.desired_outcome[:120]}",
                              comparison_revision_id=task.baseline_revision_id)
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            att = D.Attempt(id=att_id, baseline_revision_id=task.baseline_revision_id,
                            brief_id=task_id, provider="repair",
                            request_sha256=payload_hash[:64] if len(payload_hash) >= 64
                            else payload_hash.ljust(64, "0"),
                            response_ref=None, candidate_asset_ids=[new_revision_id],
                            repair_mask_id=task.edit_mask_id,
                            targeted_issue_ids=[task.source_issue_event_id],
                            result="succeeded" if sel.get("selected") else
                            f"failed: {sel.get('reason', 'not selected')[:52]}",
                            no_progress_signature=payload_hash)
            try:
                S.stage(con, att)
            except S.ConflictError:
                adata, _ = S.get(con, "attempts", att_id)
                prior = D.Attempt.model_validate_json(json.dumps(adata))
                if prior.no_progress_signature != payload_hash:
                    raise S.ConflictError(
                        f"idempotency key already used with a different payload for {task_id}")
                return _replay_submit(project_dir, task, prior)
            data, ver = S.get(con, "correction_tasks", task_id)
            t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
            if not sel.get("selected"):
                t2.status = D.CorrectionStatus.ATTEMPTING
                t2.last_error = str(sel.get("reason", ""))[:2000]
                t2.attempt_ids = [*t2.attempt_ids, att_id]
                S.stage_update(con, "correction_tasks", t2, ver)
                if sel.get("needs_attention"):
                    t2.status = D.CorrectionStatus.BLOCKED
                    S.stage_update(con, "correction_tasks", t2, ver + 1)
                return {"ok": False, "attempt_id": att_id,
                        "reason": sel.get("reason"), "task_status": t2.status.value}
            assert pkt is not None
            att.response_ref = pkt.artifacts[0]["id"]
            data, ver = S.get(con, "correction_tasks", task_id)
            t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
            t2.status = D.CorrectionStatus.AWAITING_COMPARISON
            t2.last_error = None
            t2.attempt_ids = [*t2.attempt_ids, att_id]
            S.stage_update(con, "correction_tasks", t2, ver)
    finally:
        con.close()
    return {"ok": True, "attempt_id": att_id, "revision_id": new_revision_id,
            "evaluation": cand_env.model_dump(), "packet": pkt.model_dump(),
            "subjective": subjective,
            "awaiting_human_comparison": bool(sel.get("awaiting_human_comparison")),
            "scope": scope}


def _replay_submit(project_dir: str, task: D.CorrectionTask, prior: D.Attempt) -> dict:
    """Crash-recovery replay: rebuild the stored envelope from durable rows."""
    new_id = prior.candidate_asset_ids[0] if prior.candidate_asset_ids else None
    if new_id is None:
        return {"ok": False, "attempt_id": prior.id, "reason": prior.result,
                "task_status": task.status.value, "deduped": True}
    con = S.connect(project_dir)
    try:
        latest = P.latest_evaluation(con, new_id)
        pkt = None
        if prior.response_ref:
            try:
                pdata, _ = S.get(con, "review_packets", prior.response_ref)
                pkt = json.loads(pdata)
            except KeyError:
                pkt = None
    finally:
        con.close()
    if latest is None:
        return {"ok": False, "attempt_id": prior.id, "reason": prior.result,
                "task_status": task.status.value, "deduped": True}
    return {"ok": prior.result == "succeeded", "attempt_id": prior.id,
            "revision_id": new_id, "evaluation_id": latest.id,
            "evaluation": {"id": latest.id,
                           "technical_status": latest.technical_status.value},
            "packet": pkt,
            "reason": None if prior.result == "succeeded" else prior.result,
            "deduped": True}


def reopen_issue(project_dir: str, actor: Actor, issue_event_id: str,
                 note: str = "") -> dict:
    """Reviewer reopens a resolved issue; the task returns to the open queue."""
    require_reviewer(actor, "reopen_issue")
    con = S.connect(project_dir)
    try:
        try:
            idata, _ = S.get(con, "review_events", issue_event_id)
        except KeyError:
            raise InvalidInput(f"unknown issue event {issue_event_id}")
        issue = D.ReviewEvent.model_validate_json(json.dumps(idata))
        if issue.action != "mark_issue":
            raise InvalidInput(f"event {issue_event_id} is {issue.action}, not an issue")
        task = None
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            t = D.CorrectionTask.model_validate_json(r["data"])
            if t.source_issue_event_id == issue_event_id:
                task = t
                break
        if task is None:
            raise InvalidInput(f"no correction task for issue {issue_event_id}")
        if task.status != D.CorrectionStatus.RESOLVED:
            raise InvalidInput(f"task {task.id} is {task.status.value}, not resolved")
        with S.atomic(con):
            ev = P._stage_event(con, project_dir, actor,
                                {"action": "reopen_issue",
                                 "clip_revision_id": issue.clip_revision_id,
                                 "packet_id": issue.packet_id, "note": note or "reopened"})
            data, ver = S.get(con, "correction_tasks", task.id)
            t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
            t2.status = D.CorrectionStatus.REOPENED
            t2.resolution_event_id = None
            t2.claim_holder = None
            t2.claim_token_sha256 = None
            t2.claim_lease = None
            S.stage_update(con, "correction_tasks", t2, ver)
    finally:
        con.close()
    return {"ok": True, "task_id": task.id, "status": "reopened", "event_id": ev.id}
