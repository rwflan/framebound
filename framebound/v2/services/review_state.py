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


def _candidate_revisions(con, task) -> set[str]:
    """Resolve attempt IDs to the candidate revisions they published.

    Attempt IDs and revision IDs live in different relations; comparing them
    directly is a type error that lets replacement revisions escape their
    unresolved tasks. Every consumer must resolve through this helper.
    """
    out: set[str] = set()
    for aid in task.attempt_ids or []:
        row = con.execute("SELECT data FROM attempts WHERE id=?", (aid,)).fetchone()
        if row is None:
            continue
        try:
            att = D.Attempt.model_validate_json(row["data"])
        except Exception:
            continue
        out.update(att.candidate_asset_ids or [])
    return out


def task_relates_to(con, task, revision_id: str) -> bool:
    """A task blocks its baseline revision and every candidate it published."""
    if task.baseline_revision_id == revision_id:
        return True
    return revision_id in _candidate_revisions(con, task)


def current_state(project_dir: str, revision_id: str) -> dict:
    con = S.connect(project_dir)
    try:
        return current_state_in(con, project_dir, revision_id)
    finally:
        con.close()


def current_state_in(con, project_dir: str, revision_id: str) -> dict:
    """Single ordered reducer for current human acceptance.

    Fold in durable (created_at, id) order; the latest valid reviewer
    approve/reject/needs_changes/reopen decides. Non-reviewer events never
    confer acceptance. Reapproval after rejection restores approval; reopen
    revokes it again.
    """
    if True:
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
        related = {t.id for t in tasks if task_relates_to(con, t, revision_id)}
    events.sort(key=lambda e: (e.created_at, e.id))
    acceptance = D.HumanAcceptance.UNREVIEWED.value
    decided_by = decided_at = decided_event = decided_packet = None
    for ev in events:
        if ev.actor_type != "reviewer":
            continue  # only recorded reviewer decisions move current state
        if ev.action == "approve":
            acceptance = D.HumanAcceptance.APPROVED.value
        elif ev.action == "reject":
            acceptance = D.HumanAcceptance.REJECTED.value
        elif ev.action == "needs_changes":
            acceptance = D.HumanAcceptance.NEEDS_CHANGES.value
        elif ev.action == "reopen_issue":
            acceptance = D.HumanAcceptance.NEEDS_CHANGES.value
        else:
            continue
        decided_by, decided_at = ev.actor_id, ev.created_at
        decided_event, decided_packet = ev.id, ev.packet_id
    open_issue_ids, resolved_issue_ids = [], []
    for t in tasks:
        if t.id not in related:
            continue
        if t.status in (D.CorrectionStatus.RESOLVED, D.CorrectionStatus.CANCELLED):
            resolved_issue_ids.append(t.source_issue_event_id)
        else:
            open_issue_ids.append(t.source_issue_event_id)
    return {"revision_id": revision_id, "acceptance": acceptance,
            "decided_by": decided_by, "decided_at": decided_at,
            "decided_event_id": decided_event, "decided_packet_id": decided_packet,
            "open_issue_ids": sorted(set(open_issue_ids)),
            "resolved_issue_ids": sorted(set(resolved_issue_ids))}
