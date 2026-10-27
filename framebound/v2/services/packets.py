from __future__ import annotations

import json

from .. import domain as D
from .. import storage as S
from .authz import Actor, require_reviewer
from .errors import InvalidInput


def create_packet(project_dir: str, packet_id: str, revision_id: str, evaluation_id: str,
                  intent: str, comparison_revision_id: str | None = None) -> D.ResultEnvelope:
    con = S.connect(project_dir)
    try:
        S.get(con, "clip_revisions", revision_id)
        edata, _ = S.get(con, "evaluations", evaluation_id)
        ev = D.Evaluation.model_validate_json(json.dumps(edata))
        if ev.clip_revision_id != revision_id:
            raise InvalidInput("packet evaluation does not address this revision: stale evidence rejected")
        issues = sorted({r.constraint_id for r in ev.results if r.outcome in ("fail", "error")})
        uncovered = sorted({r.constraint_id for r in ev.results if r.outcome in ("unmeasured", "not_applicable")})
        pkt = D.ReviewPacket(id=packet_id, clip_revision_id=revision_id, evaluation_id=evaluation_id,
                             intent=intent, comparison_revision_id=comparison_revision_id,
                             issue_ids=issues, unresolved_coverage=uncovered)
        S.insert(con, pkt)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-packet-{packet_id}", revision_id=revision_id,
                            technical_status=ev.technical_status,
                            issues=[{"code": c} for c in issues],
                            artifacts=[{"id": packet_id, "role": "review_packet"}],
                            next_actions=["human_review"])


def record_review_event(project_dir: str, actor: Actor, event: dict) -> D.ResultEnvelope:
    require_reviewer(actor, event.get("action", ""))
    ev = D.ReviewEvent(id=event["id"], actor_type=actor.type, actor_id=actor.id,
                       action=event["action"], clip_revision_id=event["clip_revision_id"],
                       packet_id=event.get("packet_id"), frame_instance_id=event.get("frame_instance_id"),
                       frame_range=event.get("frame_range"),
                       roi=D.Roi.model_validate(event["roi"]) if event.get("roi") else None,
                       note=event.get("note", ""))
    con = S.connect(project_dir)
    try:
        S.insert(con, ev)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-event-{ev.id}", revision_id=ev.clip_revision_id,
                            next_actions=["corrections_list"] if ev.action == "mark_issue" else ["review_packet_get"])
