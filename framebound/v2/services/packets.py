"""Review packets + review events with server-resolved relationship validation.

Every write validates the full tuple (packet -> revision -> contract ->
character, evaluation -> revision, issue -> packet/scope) against stored
records. Caller-supplied ids that disagree with stored relationships are
rejected; identical retries return the stored result; same id with a different
command is a conflict.
"""
from __future__ import annotations

import json
import uuid

from .. import domain as D
from .. import storage as S
from .authz import Actor, require_reviewer
from .errors import InvalidInput, StaleRevision


def _resolve_revision(con, revision_id: str) -> tuple[D.ClipRevision, D.ClipContractRevision]:
    try:
        rdata, _ = S.get(con, "clip_revisions", revision_id)
    except KeyError:
        raise InvalidInput(f"unknown clip revision {revision_id}")
    rev = D.ClipRevision.model_validate_json(json.dumps(rdata))
    try:
        cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
    except KeyError:
        raise InvalidInput(f"revision {revision_id}: contract {rev.contract_revision_id} missing")
    return rev, D.ClipContractRevision.model_validate_json(json.dumps(cdata))


def _check_packet_addresses(con, packet_id: str, revision_id: str) -> tuple[dict, D.Evaluation]:
    try:
        pdata, _ = S.get(con, "review_packets", packet_id)
    except KeyError:
        raise InvalidInput(f"unknown review packet {packet_id}")
    pkt = D.ReviewPacket.model_validate_json(json.dumps(pdata))
    if pkt.clip_revision_id != revision_id:
        raise InvalidInput(
            f"packet {packet_id} addresses revision {pkt.clip_revision_id}, "
            f"not the claimed {revision_id}: mismatched approval rejected")
    try:
        edata, _ = S.get(con, "evaluations", pkt.evaluation_id)
    except KeyError:
        raise InvalidInput(f"packet {packet_id}: evaluation {pkt.evaluation_id} missing")
    ev = D.Evaluation.model_validate_json(json.dumps(edata))
    if ev.clip_revision_id != revision_id:
        raise InvalidInput(f"packet {packet_id}: evaluation addresses {ev.clip_revision_id}, not {revision_id}")
    return pkt, ev


def latest_evaluation(con, revision_id: str) -> D.Evaluation | None:
    mine = []
    for r in con.execute("SELECT data FROM evaluations").fetchall():
        try:
            ev = D.Evaluation.model_validate_json(r["data"])
        except Exception:
            continue
        if ev.clip_revision_id == revision_id:
            mine.append(ev)
    if not mine:
        return None
    mine.sort(key=lambda e: (e.created_at, e.id))
    return mine[-1]


def create_packet(project_dir: str, packet_id: str, revision_id: str, evaluation_id: str,
                  intent: str, comparison_revision_id: str | None = None, *, connection=None) -> D.ResultEnvelope:
    owned = connection is None
    con = connection if connection is not None else S.connect(project_dir)
    try:
        try:
            pdata, _ = S.get(con, "review_packets", packet_id)
            pkt = D.ReviewPacket.model_validate_json(json.dumps(pdata))
            if pkt.clip_revision_id == revision_id and pkt.evaluation_id == evaluation_id:
                return D.ResultEnvelope(ok=True, operation_id=f"op-packet-{packet_id}",
                                        revision_id=revision_id, next_actions=["human_review"],
                                        artifacts=[{"id": packet_id, "role": "review_packet",
                                                    "deduped": True}])
            raise S.ConflictError(f"packet id {packet_id} already curates a different revision/evaluation")
        except KeyError:
            pass
        rev, contract = _resolve_revision(con, revision_id)
        try:
            edata, _ = S.get(con, "evaluations", evaluation_id)
        except KeyError:
            raise InvalidInput(f"unknown evaluation {evaluation_id}")
        ev = D.Evaluation.model_validate_json(json.dumps(edata))
        if ev.clip_revision_id != revision_id:
            raise InvalidInput("packet evaluation does not address this revision: stale evidence rejected")
        if comparison_revision_id:
            comp_rev, _ = _resolve_revision(con, comparison_revision_id)
            if comp_rev.contract_revision_id != rev.contract_revision_id:
                raise InvalidInput("comparison revision is from a different contract: not comparable")
        issues = sorted({r.constraint_id for r in ev.results if r.outcome in ("fail", "error")})
        uncovered = sorted({r.constraint_id for r in ev.results if r.outcome in ("unmeasured", "not_applicable")})
        pkt = D.ReviewPacket(id=packet_id, clip_revision_id=revision_id, evaluation_id=evaluation_id,
                             intent=intent, comparison_revision_id=comparison_revision_id,
                             issue_ids=issues, unresolved_coverage=uncovered)
        S.stage(con, pkt)
        if owned:
            con.commit()
    finally:
        if owned:
            con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-packet-{packet_id}", revision_id=revision_id,
                            technical_status=ev.technical_status,
                            issues=[{"code": c} for c in issues],
                            artifacts=[{"id": packet_id, "role": "review_packet"}],
                            next_actions=["human_review"])


def _build_event(event: dict, actor: Actor) -> D.ReviewEvent:
    eid = event.get("id") or f"evt-{uuid.uuid4().hex[:12]}"
    try:
        return D.ReviewEvent(
            id=eid, actor_type=actor.type, actor_id=actor.id,
            action=event.get("action", "mark_issue"),
            packet_id=event.get("packet_id"),
            clip_revision_id=event["clip_revision_id"],
            frame_instance_id=event.get("frame_instance_id"),
            frame_range=event.get("frame_range"),
            roi=D.Roi.model_validate(event["roi"]) if event.get("roi") else None,
            note=event.get("note", ""),
            category=event.get("category", "general"),visual_annotations=event.get("visual_annotations",[]))
    except KeyError as e:
        raise InvalidInput(f"review event missing {e}")
    except Exception as e:
        raise InvalidInput(f"review event invalid: {e}") from e


def _validate_relationships(con, project_dir: str, ev: D.ReviewEvent, raw: dict) -> None:
    rev, contract = _resolve_revision(con, ev.clip_revision_id)
    if ev.visual_annotations:
        from ...v3.services.studio import Stroke
        for raw in ev.visual_annotations:
            stroke=Stroke.model_validate(raw)
            if stroke.slot>=len(rev.frame_instance_ids) or any(not (0<=x<contract.canvas.width and 0<=y<contract.canvas.height) for x,y in stroke.points):raise InvalidInput("Annotation exceeds native frame")
    pkt = None
    if ev.packet_id:
        pkt, _ = _check_packet_addresses(con, ev.packet_id, ev.clip_revision_id)
    if ev.action in ("approve", "reject", "needs_changes"):
        # decisions need stored technical evidence for the exact revision
        target = latest_evaluation(con, ev.clip_revision_id)
        if target is None:
            raise InvalidInput(f"cannot decide on {ev.clip_revision_id}: no stored evaluation")
        want = raw.get("expected_evaluation_id") or (pkt.evaluation_id if pkt else None)
        if want and want != target.id:
            raise StaleRevision(
                f"stale view: expected evaluation {want}, current is {target.id}; reload before deciding")
        if raw.get("expected_revision_id") and raw["expected_revision_id"] != ev.clip_revision_id:
            raise StaleRevision("stale_revision: viewed revision differs from the submitted one")
    if ev.action == "mark_issue":
        if ev.frame_instance_id:
            try:
                fdata, _ = S.get(con, "frame_instances", ev.frame_instance_id)
            except KeyError:
                raise InvalidInput(f"unknown frame instance {ev.frame_instance_id}")
            fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
            if fi.clip_revision_id != ev.clip_revision_id:
                raise InvalidInput("issue frame belongs to a different revision")
        if ev.frame_range is not None:
            total = contract.timing.total_ticks()
            if ev.frame_range[1] >= total:
                raise InvalidInput(
                    f"frame_range end {ev.frame_range[1]} outside 0..{total - 1} for this contract")
        if ev.roi is not None:
            w, h = contract.canvas.width, contract.canvas.height
            if ev.roi.right > w or ev.roi.bottom > h:
                raise InvalidInput(
                    f"ROI {ev.roi} extends outside the {w}x{h} canvas")


def _stage_event(con, project_dir: str, actor: Actor, event: dict) -> D.ReviewEvent:
    action = event.get("action", "mark_issue")
    # Stage D: machine-detected faults are system/orchestrator events, never
    # fabricated human issues. They authorize bounded automatic work under the
    # frozen contract, not artistic acceptance.
    if action=='machine_fault':
        from .errors import AuthorizationError
        if actor.type!='system':raise AuthorizationError('machine faults must come from measured framework work')
    else:
        require_reviewer(actor, action)
    if action == "approve_reference":
        raise InvalidInput("reference approval requires the stored-approval flow, not a bare event")
    if action not in ("approve", "reject", "needs_changes", "mark_issue", "resolve_issue", "reopen_issue",
                        "approve_mask", "machine_fault"):
        raise InvalidInput(f"unknown review action {action!r}")
    ev = _build_event(event, actor)
    _validate_relationships(con, project_dir, ev, event)
    try:
        S.stage(con, ev)
    except S.ConflictError:
        existing = D.ReviewEvent.model_validate_json(
            json.dumps(S.get(con, "review_events", ev.id)[0]))
        if existing.model_dump(exclude={'created_at'})==ev.model_dump(exclude={'created_at'}):
            return existing
        raise S.ConflictError(f"event id {ev.id} already recorded with a different action/subject")
    return ev


def record_review_event(project_dir: str, actor: Actor, event: dict) -> D.ResultEnvelope:
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            stored = _stage_event(con, project_dir, actor, event)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-event-{stored.id}", revision_id=stored.clip_revision_id,
                            next_actions=["corrections_list"] if stored.action == "mark_issue"
                            else ["review_packet_get"])


def record_decision(project_dir: str, actor: Actor, event: dict) -> D.ResultEnvelope:
    """approve/reject/needs_changes with server-resolved staleness. Returns dedupe flag."""
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            before = None
            try:
                edata, _ = S.get(con, "review_events", event.get("id", ""))
                before = D.ReviewEvent.model_validate_json(json.dumps(edata))
            except (KeyError, Exception):
                before = None
            stored = _stage_event(con, project_dir, actor, event)
            dup = before is not None and before.id == stored.id
    finally:
        con.close()
    env = D.ResultEnvelope(ok=True, operation_id=f"op-event-{stored.id}",
                           revision_id=stored.clip_revision_id, next_actions=["review_packet_get"])
    if dup:
        env.artifacts.append({"id": stored.id, "role": "review_event", "deduped": True})
    return env
