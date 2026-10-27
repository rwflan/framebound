from __future__ import annotations

from .. import domain as D
from .. import storage as S


def create_project(project_dir: str, meta: dict) -> D.ResultEnvelope:
    con = S.connect(project_dir)
    try:
        proj = D.Project(id=meta["id"], name=meta.get("name", meta["id"]),
                         owner=meta.get("owner", "entrant"),
                         rights_policy=meta.get("rights_policy", "original-only"))
        S.insert(con, proj)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-create-{proj.id}", revision_id=proj.id,
                            next_actions=["asset_import", "contract_propose"])


def get_summary(project_dir: str) -> dict:
    con = S.connect(project_dir)
    try:
        out = {"projects": S.count(con, "projects"), "assets": S.count(con, "assets"),
               "contract_revisions": S.count(con, "contract_revisions"),
               "clip_revisions": S.count(con, "clip_revisions"),
               "evaluations": S.count(con, "evaluations"),
               "review_packets": S.count(con, "review_packets"),
               "open_corrections": sum(1 for r in con.execute("SELECT data FROM correction_tasks").fetchall()
                                       if '"status": "open"' in r["data"] or '"status":"open"' in r["data"]),
               "jobs": S.count(con, "jobs")}
    finally:
        con.close()
    return out
