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
        # exact-revision + exact-evaluation human approval through a packet.
        # A later reject/needs_changes/reopen for this revision invalidates it:
        # approval is current acceptance, not a historical event.
        approved = False
        approved_at = ""
        for r in con.execute("SELECT data FROM review_events").fetchall():
            try:
                ev = D.ReviewEvent.model_validate_json(r["data"])
            except Exception:
                continue
            if ev.action != "approve" or ev.actor_type != "reviewer":
                continue
            if ev.clip_revision_id != revision_id or not ev.packet_id:
                continue
            try:
                pdata, _ = S.get(con, "review_packets", ev.packet_id)
            except KeyError:
                continue
            pkt = D.ReviewPacket.model_validate_json(json.dumps(pdata))
            if pkt.clip_revision_id == revision_id and pkt.evaluation_id == latest.id:
                approved = pkt.id
                approved_at = ev.created_at
                break
        if not approved:
            eligible = False
            reasons.append("no reviewer approval binds this exact revision+evaluation via a packet")
        else:
            for r in con.execute("SELECT data FROM review_events").fetchall():
                try:
                    ev = D.ReviewEvent.model_validate_json(r["data"])
                except Exception:
                    continue
                if ev.clip_revision_id != revision_id:
                    continue
                if ev.action in ("reject", "needs_changes", "reopen_issue") \
                        and ev.created_at > approved_at:
                    eligible = False
                    reasons.append(f"{ev.action} at {ev.created_at} supersedes the approval")
                    break
        # unresolved blocking tasks (baseline or attempt references this revision)
        blocking = []
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            try:
                t = D.CorrectionTask.model_validate_json(r["data"])
            except Exception:
                continue
            if t.status in (D.CorrectionStatus.RESOLVED, D.CorrectionStatus.CANCELLED):
                continue
            if t.baseline_revision_id == revision_id or revision_id in (t.attempt_ids or []):
                blocking.append(t.id)
        if blocking:
            eligible = False
            reasons.append(f"unresolved tasks: {sorted(blocking)[:4]}")
    finally:
        con.close()
    return {"revision_id": revision_id, "eligible": eligible,
            "evaluation_id": latest.id if latest else None,
            "reasons": reasons}
