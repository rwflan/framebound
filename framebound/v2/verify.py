"""v2 verify: stored revisions validate, blobs present and hash-fresh, evidence current.

Fail-closed: a nonexistent project path is an error, never an empty verified
project. Tampered blobs, changed pixels, broken relationships, truncated
sequences, stale manifests and superseded approvals are reported as issues.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import domain as D
from . import storage as S
from .media.canonical import canonical_pixels

TABLE_MODEL = {
    "projects": D.Project, "assets": D.Asset, "character_revisions": D.CharacterRevision,
    "contract_revisions": D.ClipContractRevision, "clip_revisions": D.ClipRevision,
    "frame_instances": D.FrameInstance, "annotation_revisions": D.AnnotationRevision,
    "evaluations": D.Evaluation, "attempts": D.Attempt, "review_packets": D.ReviewPacket,
    "review_events": D.ReviewEvent, "correction_tasks": D.CorrectionTask,
    "jobs": D.Job, "export_snapshots": D.ExportSnapshot,
    "motion_guides": D.MotionGuide, "reference_approvals": D.ReferenceApproval,
    "registrations": D.Registration, "edit_masks": D.EditMask,
    "compiled_briefs": D.CompiledBrief, "world_traces": D.WorldTrace, "runs": D.Run,
    "transition_traces": D.TransitionTrace,
}


def run_verify(project_dir: str) -> dict:
    issues: list[str] = []
    counts: dict[str, int] = {}
    proj = Path(project_dir)
    db = proj / "framebound.sqlite3"
    if not proj.is_dir() or not db.is_file():
        return {"schema_version": "2.0", "ok": False, "counts": {},
                "issues": [f"no such project: {proj} (refusing to materialize one)"],
                "project": str(proj.resolve())}
    con = S.connect(project_dir)
    try:
        for table, model in TABLE_MODEL.items():
            try:
                rows = con.execute(f"SELECT id, data FROM {table}").fetchall()
            except Exception as e:
                issues.append(f"{table}: unreadable: {e}")
                continue
            counts[table] = len(rows)
            for r in rows:
                try:
                    model.model_validate_json(r["data"])
                except Exception as e:
                    issues.append(f"{table}/{r['id']}: invalid: {e}")
        # blob presence + hash freshness + canonical pixel freshness for assets
        for r in con.execute("SELECT data FROM assets").fetchall():
            try:
                a = D.Asset.model_validate_json(r["data"])
            except Exception:
                continue
            blob = S.blob_path(project_dir, a.byte_sha256)
            if not blob.is_file():
                issues.append(f"assets/{a.id}: missing blob {a.byte_sha256[:16]}...")
                continue
            raw = blob.read_bytes()
            if hashlib.sha256(raw).hexdigest() != a.byte_sha256:
                issues.append(f"assets/{a.id}: blob bytes no longer match recorded hash (tampered?)")
                continue
            if a.pixel_sha256:
                try:
                    from PIL import Image as _Image
                    import io as _io
                    canon = canonical_pixels(_Image.open(_io.BytesIO(raw)))
                    if hashlib.sha256(canon).hexdigest() != a.pixel_sha256:
                        issues.append(f"assets/{a.id}: canonical pixels changed since import")
                except Exception as e:
                    issues.append(f"assets/{a.id}: undecodable blob: {e}")
        _check_relationships(con, project_dir, issues)
        _check_sequences(con, issues)
        _check_evidence_freshness(con, project_dir, issues)
    finally:
        con.close()
    return {"schema_version": "2.0", "ok": not issues, "counts": counts, "issues": issues,
            "project": str(Path(project_dir).resolve())}


def _check_relationships(con, project_dir: str, issues: list[str]) -> None:
    def has(table: str, rid: str) -> bool:
        return con.execute(f"SELECT 1 FROM {table} WHERE id=?", (rid,)).fetchone() is not None

    for r in con.execute("SELECT id, data FROM clip_revisions").fetchall():
        try:
            rev = json.loads(r["data"])
        except Exception:
            continue
        if not has("contract_revisions", rev.get("contract_revision_id", "")):
            issues.append(f"clip_revisions/{r['id']}: contract {rev.get('contract_revision_id')} missing")
        for fid in rev.get("frame_instance_ids", []):
            if not has("frame_instances", fid):
                issues.append(f"clip_revisions/{r['id']}: frame instance {fid} missing")
    for r in con.execute("SELECT id, data FROM frame_instances").fetchall():
        try:
            fi = json.loads(r["data"])
        except Exception:
            continue
        if not has("clip_revisions", fi.get("clip_revision_id", "")):
            issues.append(f"frame_instances/{r['id']}: revision {fi.get('clip_revision_id')} missing")
        if not has("assets", fi.get("asset_id", "")):
            issues.append(f"frame_instances/{r['id']}: asset {fi.get('asset_id')} missing")
        if fi.get("registration_id") and not has("registrations", fi["registration_id"]):
            issues.append(f"frame_instances/{r['id']}: registration {fi['registration_id']} missing")
    for r in con.execute("SELECT id, data FROM review_packets").fetchall():
        try:
            pkt = json.loads(r["data"])
        except Exception:
            continue
        if not has("clip_revisions", pkt.get("clip_revision_id", "")):
            issues.append(f"review_packets/{r['id']}: revision {pkt.get('clip_revision_id')} missing")
        ev = con.execute("SELECT data FROM evaluations WHERE id=?",
                         (pkt.get("evaluation_id", ""),)).fetchone()
        if ev is None:
            issues.append(f"review_packets/{r['id']}: evaluation {pkt.get('evaluation_id')} missing")
        elif json.loads(ev["data"]).get("clip_revision_id") != pkt.get("clip_revision_id"):
            issues.append(f"review_packets/{r['id']}: evaluation addresses a different revision (stale packet)")
    for r in con.execute("SELECT id, data FROM correction_tasks").fetchall():
        try:
            t = json.loads(r["data"])
        except Exception:
            continue
        if not has("review_events", t.get("source_issue_event_id", "")):
            issues.append(f"correction_tasks/{r['id']}: source issue {t.get('source_issue_event_id')} missing")


def _check_sequences(con, issues: list[str]) -> None:
    for r in con.execute("SELECT id, data FROM clip_revisions").fetchall():
        try:
            rev = json.loads(r["data"])
            cdata, _ = S.get(con, "contract_revisions", rev["contract_revision_id"])
        except Exception:
            continue
        holds = cdata["timing"]["holds"]
        slots = []
        for fid in rev.get("frame_instance_ids", []):
            frow = con.execute("SELECT data FROM frame_instances WHERE id=?", (fid,)).fetchone()
            if frow is None:
                continue
            slots.append(json.loads(frow["data"])["slot"])
        if sorted(slots) != list(range(len(holds))):
            issues.append(f"clip_revisions/{r['id']}: frame slots {sorted(slots)} do not cover "
                          f"0..{len(holds) - 1}: truncated or padded sequence")


def _check_evidence_freshness(con, project_dir: str, issues: list[str]) -> None:
    # One shared verifier: manifest address, candidate/reference bytes +
    # pixels, relevant annotations, analyzer and lock identity.
    from .services import evidence as _EV
    for r in con.execute("SELECT id, data FROM evaluations").fetchall():
        try:
            ev = D.Evaluation.model_validate_json(r["data"])
        except Exception:
            continue
        _, problems = _EV.verify_evidence(project_dir, ev.clip_revision_id, ev)
        for problem in problems:
            issues.append(f"evaluations/{r['id']}: {problem}")
    # superseded approvals referenced by newer briefs are history, not authority:
    # flag approvals whose event is not a reviewer decision
    for r in con.execute("SELECT id, data FROM reference_approvals").fetchall():
        try:
            ap = json.loads(r["data"])
        except Exception:
            continue
        evrow = con.execute("SELECT data FROM review_events WHERE id=?",
                            (ap.get("event_id", ""),)).fetchone()
        if evrow is None or json.loads(evrow["data"]).get("actor_type") != "reviewer":
            issues.append(f"reference_approvals/{r['id']}: backing event is not a human reviewer decision")
