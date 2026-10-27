from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput


def list_open(project_dir: str) -> dict:
    con = S.connect(project_dir)
    try:
        rows = con.execute("SELECT data FROM correction_tasks").fetchall()
    finally:
        con.close()
    tasks = [json.loads(r["data"]) for r in rows]
    open_tasks = [t for t in tasks if t["status"] in ("open", "reopened")]
    return {"open": open_tasks, "count": len(open_tasks)}


def open_task(project_dir: str, task: D.CorrectionTask) -> None:
    con = S.connect(project_dir)
    try:
        S.insert(con, task)
    finally:
        con.close()


def claim(project_dir: str, task_id: str, holder: str, expected_version: int,
          lease_minutes: int = 30) -> dict:
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "correction_tasks", task_id)
        task = D.CorrectionTask.model_validate_json(json.dumps(data))
        if task.status not in (D.CorrectionStatus.OPEN, D.CorrectionStatus.REOPENED):
            raise InvalidInput(f"task {task_id} is {task.status}, not claimable")
        task.status = D.CorrectionStatus.CLAIMED
        task.claim_lease = (datetime.now(timezone.utc) + timedelta(minutes=lease_minutes)).isoformat()
        nv = S.update_mutable(con, "correction_tasks", task, expected_version)
    finally:
        con.close()
    return {"task_id": task_id, "status": "claimed", "lease": task.claim_lease, "version": nv}
