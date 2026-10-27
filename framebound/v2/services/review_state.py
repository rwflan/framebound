"""Current-state reducer: fold immutable events into the present decision.

'Any approve exists' is not current state. The reducer respects event order and
supersession: the latest approve/reject/needs_changes for the exact revision
decides acceptance; open issues are mark_issue events minus explicit
resolutions tracked through correction tasks.
"""
from __future__ import annotations

import json

from .. import domain as D
from .. import storage as S


def current_state(project_dir: str, revision_id: str) -> dict:
    con = S.connect(project_dir)
    try:
        events = []
        for r in con.execute("SELECT data FROM review_events").fetchall():
            try:
                ev = D.ReviewEvent.model_validate_json(r["data"])
            except Exception:
                continue
            if ev.clip_revision_id == revision_id:
                events.append(ev)
        tasks = []
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            try:
                tasks.append(D.CorrectionTask.model_validate_json(r["data"]))
            except Exception:
                continue
    finally:
        con.close()
    events.sort(key=lambda e: (e.created_at, e.id))
    acceptance = D.HumanAcceptance.UNREVIEWED.value
    decided_by = None
    decided_at = None
    for ev in events:
        if ev.action == "approve":
            acceptance, decided_by, decided_at = D.HumanAcceptance.APPROVED.value, ev.actor_id, ev.created_at
        elif ev.action == "reject":
            acceptance, decided_by, decided_at = D.HumanAcceptance.REJECTED.value, ev.actor_id, ev.created_at
        elif ev.action == "needs_changes":
            acceptance, decided_by, decided_at = D.HumanAcceptance.NEEDS_CHANGES.value, ev.actor_id, ev.created_at
        elif ev.action == "reopen_issue":
            acceptance, decided_by, decided_at = D.HumanAcceptance.NEEDS_CHANGES.value, ev.actor_id, ev.created_at
    open_issue_ids, resolved_issue_ids = [], []
    for t in tasks:
        if t.baseline_revision_id != revision_id and not any(
                a == revision_id for a in t.attempt_ids):
            continue
        if t.status in (D.CorrectionStatus.RESOLVED, D.CorrectionStatus.CANCELLED):
            resolved_issue_ids.append(t.source_issue_event_id)
        else:
            open_issue_ids.append(t.source_issue_event_id)
    return {"revision_id": revision_id, "acceptance": acceptance,
            "decided_by": decided_by, "decided_at": decided_at,
            "open_issue_ids": sorted(set(open_issue_ids)),
            "resolved_issue_ids": sorted(set(resolved_issue_ids))}
