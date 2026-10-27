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

import hashlib
import json

from .. import domain as D
from .. import storage as S
from . import packets as P


def _manifest_bytes(project_dir: str, ev: D.Evaluation) -> dict | None:
    try:
        raw = S.blob_path(project_dir, ev.evidence_manifest_sha256).read_bytes()
        return json.loads(raw.decode())
    except Exception:
        return None


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
        manifest = _manifest_bytes(project_dir, latest)
        if manifest is None:
            eligible = False
            reasons.append("evidence manifest blob missing from the store")
        else:
            stale = []
            frames = manifest.get("frames", [])
            for i, fid in enumerate(rev.frame_instance_ids):
                try:
                    fdata, _ = S.get(con, "frame_instances", fid)
                    fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
                    adata, _ = S.get(con, "assets", fi.asset_id)
                except KeyError:
                    stale.append(f"slot {i}: record missing")
                    continue
                want = (frames[i].get("byte_sha256") if i < len(frames) else None)
                if adata["byte_sha256"] != want:
                    stale.append(f"slot {i}: bytes changed since evaluation")
            if stale:
                eligible = False
                reasons.append("evidence stale: " + "; ".join(stale[:4]))
        # exact-revision + exact-evaluation human approval through a packet
        approved = False
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
                break
        if not approved:
            eligible = False
            reasons.append("no reviewer approval binds this exact revision+evaluation via a packet")
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
