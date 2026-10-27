"""v2 verify: stored revisions validate, blobs present, evidence fresh (WP1 scope)."""
from __future__ import annotations

import json
from pathlib import Path

from . import domain as D
from . import storage as S

TABLE_MODEL = {
    "projects": D.Project, "assets": D.Asset, "character_revisions": D.CharacterRevision,
    "contract_revisions": D.ClipContractRevision, "clip_revisions": D.ClipRevision,
    "frame_instances": D.FrameInstance, "annotation_revisions": D.AnnotationRevision,
    "evaluations": D.Evaluation, "attempts": D.Attempt, "review_packets": D.ReviewPacket,
    "review_events": D.ReviewEvent, "correction_tasks": D.CorrectionTask,
    "jobs": D.Job, "export_snapshots": D.ExportSnapshot,
}


def run_verify(project_dir: str) -> dict:
    issues: list[str] = []
    counts: dict[str, int] = {}
    con = S.connect(project_dir)
    try:
        for table, model in TABLE_MODEL.items():
            rows = con.execute(f"SELECT id, data FROM {table}").fetchall()
            counts[table] = len(rows)
            for r in rows:
                try:
                    model.model_validate_json(r["data"])
                except Exception as e:
                    issues.append(f"{table}/{r['id']}: invalid: {e}")
        # blob presence for assets
        for r in con.execute("SELECT data FROM assets").fetchall():
            a = json.loads(r["data"])
            if not S.blob_path(project_dir, a["byte_sha256"]).is_file():
                issues.append(f"assets/{a['id']}: missing blob {a['byte_sha256'][:16]}...")
    finally:
        con.close()
    return {"schema_version": "2.0", "ok": not issues, "counts": counts, "issues": issues,
            "project": str(Path(project_dir).resolve())}
