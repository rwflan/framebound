"""Release eligibility: one central rule for desk, export and publication.

A revision is releasable only with ALL of:
1. current trustworthy technical evidence (latest evaluation PASS + COMPLETE),
2. actual human approval for the exact revision + exact evaluation,
3. no unresolved blocking correction tasks,
4. fresh evidence (manifest blob present and candidate bytes unchanged).

Bare status flags or 'any approve exists' never substitute. Packetless human
decisions count as acceptance signal but NOT as release approval: release
needs a decision bound to the exact revision+evaluation through a packet.
"""
from __future__ import annotations

import json

from .. import domain as D
from .. import storage as S
from . import packets as P


def _lineage(con, revision_id: str) -> list[str]:
    """Revision plus its parent chain: an unresolved task on an ancestor
    blocks descendants under the documented correction policy, without
    blocking unrelated siblings."""
    chain = [revision_id]
    seen = {revision_id}
    cur = revision_id
    for _ in range(64):
        row = con.execute("SELECT data FROM clip_revisions WHERE id=?", (cur,)).fetchone()
        if row is None:
            break
        try:
            parent = D.ClipRevision.model_validate_json(row["data"]).parent_revision_id
        except Exception:
            break
        if not parent or parent in seen:
            break
        chain.append(parent)
        seen.add(parent)
        cur = parent
    return chain


def release_eligibility(project_dir: str, revision_id: str) -> dict:
    reasons: list[str] = []
    eligible = True
    con = S.connect(project_dir)
    try:
        try:
            rev, contract = P._resolve_revision(con, revision_id)
        except KeyError:
            return {"revision_id": revision_id, "eligible": False,
                    "reasons": [f"unknown revision {revision_id}"]}
        latest = P.latest_evaluation(con, revision_id)
        if latest is None:
            return {"revision_id": revision_id, "eligible": False,
                    "reasons": ["no stored evaluation: nothing trustworthy to release"]}
        if latest.technical_status != D.TechnicalStatus.PASS:
            eligible = False
            reasons.append(f"technical evidence is {latest.technical_status.value}, not pass")
        if latest.coverage_status != D.CoverageStatus.COMPLETE:
            eligible = False
            reasons.append(f"coverage is {latest.coverage_status.value}, not complete")
        # One shared verifier: manifest address, candidate/reference bytes +
        # pixels, relevant annotations, analyzer and lock identity. A stored
        # JSON flag or a matching status field never substitutes for it.
        from . import evidence as _EV
        verdict, problems = _EV.verify_evidence(project_dir, revision_id, latest)
        if not verdict:
            eligible = False
            reasons.append("evidence invalid: " + "; ".join(problems[:4]))
        # Current human acceptance comes from the single ordered reducer
        # (approve -> reject -> approve reduces to approved). Release then
        # needs that decision bound to this exact revision+evaluation through
        # a packet: packetless decisions are acceptance signal, not release.
        from . import review_state as _RS
        state = _RS.current_state(project_dir, revision_id)
        if state["acceptance"] != D.HumanAcceptance.APPROVED.value:
            eligible = False
            reasons.append(f"current human acceptance is {state['acceptance']}, not approved")
        else:
            pkt_id = state.get("decided_packet_id")
            bound = False
            if pkt_id:
                try:
                    pdata, _ = S.get(con, "review_packets", pkt_id)
                    pkt = D.ReviewPacket.model_validate_json(json.dumps(pdata))
                    bound = (pkt.clip_revision_id == revision_id
                             and pkt.evaluation_id == latest.id)
                except KeyError:
                    bound = False
            if not bound:
                eligible = False
                reasons.append("the current approval is not bound to this exact "
                               "revision+evaluation via a packet")
        # Unresolved blocking tasks: the revision's own tasks (baseline or
        # published candidate) plus tasks on its ancestors. Siblings with
        # their own lineage are unaffected.
        blocking = []
        lineage = set(_lineage(con, revision_id))
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            try:
                t = D.CorrectionTask.model_validate_json(r["data"])
            except Exception:
                continue
            if t.status in (D.CorrectionStatus.RESOLVED, D.CorrectionStatus.CANCELLED):
                continue
            if t.baseline_revision_id in lineage:
                blocking.append(t.id)
                continue
            if lineage & _RS._candidate_revisions(con, t):
                blocking.append(t.id)
        if blocking:
            eligible = False
            reasons.append(f"unresolved tasks: {sorted(blocking)[:4]}")
    finally:
        con.close()
    return {"revision_id": revision_id, "eligible": eligible,
            "evaluation_id": latest.id if latest else None,
            "reasons": reasons}
