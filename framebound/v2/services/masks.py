"""Reviewer-approved edit masks: pixel-level repair authority.

An issue ROI suggests scope but never authorizes pixels by itself. A repair
candidate may change a pixel only inside the issue ROI and/or a separately
reviewer-approved mask. Masks are stored assets with hash-bound bytes and an
explicit covered-slot list; approval is a reviewer event, never a model claim.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from PIL import Image

from .. import domain as D
from .. import storage as S
from . import packets as P
from .authz import Actor, require_reviewer
from .errors import InvalidInput


def _canvas_of(con, contract: D.ClipContractRevision) -> tuple[int, int]:
    return contract.canvas.width, contract.canvas.height


def approve_mask(project_dir: str, actor: Actor, issue_event_id: str,
                 mask_asset_id: str, covered_slots: list[int]) -> D.EditMask:
    """Reviewer binds a stored mask asset to an issue's correction task."""
    require_reviewer(actor, "approve_mask")
    if not covered_slots or any(isinstance(s, bool) or not isinstance(s, int) or s < 0
                                for s in covered_slots):
        raise InvalidInput("covered_slots must be a non-empty list of slot ints")
    con = S.connect(project_dir)
    try:
        try:
            idata, _ = S.get(con, "review_events", issue_event_id)
        except KeyError:
            raise InvalidInput(f"unknown issue event {issue_event_id}")
        issue = D.ReviewEvent.model_validate_json(json.dumps(idata))
        if issue.action != "mark_issue":
            raise InvalidInput(f"event {issue_event_id} is {issue.action}, not an openable issue")
        task = None
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            t = D.CorrectionTask.model_validate_json(r["data"])
            if t.source_issue_event_id == issue_event_id:
                task = t
                break
        if task is None:
            raise InvalidInput(f"no correction task for issue {issue_event_id}")
        rev, contract = P._resolve_revision(con, issue.clip_revision_id)
        n = len(contract.timing.holds)
        bad = [s for s in covered_slots if s >= n]
        if bad:
            raise InvalidInput(f"mask covers slots {bad} outside 0..{n - 1}")
        try:
            adata, _ = S.get(con, "assets", mask_asset_id)
        except KeyError:
            raise InvalidInput(f"mask asset {mask_asset_id} not stored")
        asset = D.Asset.model_validate_json(json.dumps(adata))
        w, h = _canvas_of(con, contract)
        if asset.width != w or asset.height != h:
            raise InvalidInput(f"mask {asset.width}x{asset.height} != canvas {w}x{h}")
        raw = S.blob_path(project_dir, asset.byte_sha256).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != asset.byte_sha256:
            raise InvalidInput(f"mask asset {mask_asset_id}: bytes changed since import")
        mid = f"mask-{uuid.uuid4().hex[:12]}"
        with S.atomic(con):
            ap = P._stage_event(con, project_dir, actor,
                                {"action": "approve_mask",
                                 "clip_revision_id": issue.clip_revision_id,
                                 "note": f"edit mask {mask_asset_id} for issue {issue_event_id} "
                                         f"slots {sorted(set(covered_slots))}"})
            mask = D.EditMask(id=mid, issue_event_id=issue_event_id, task_id=task.id,
                              mask_asset_id=mask_asset_id, mask_byte_sha256=digest,
                              covered_slots=sorted(set(covered_slots)),
                              approved_by=actor.id, approval_event_id=ap.id)
            S.stage(con, mask)
            data, ver = S.get(con, "correction_tasks", task.id)
            t2 = D.CorrectionTask.model_validate_json(json.dumps(data))
            t2.edit_mask_id = mid
            S.stage_update(con, "correction_tasks", t2, ver)
    finally:
        con.close()
    return mask


def get_mask(project_dir: str, mask_id: str) -> D.EditMask:
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "edit_masks", mask_id)
    finally:
        con.close()
    return D.EditMask.model_validate_json(json.dumps(data))


def scope_slots(project_dir: str, task: D.CorrectionTask) -> set[int]:
    """Temporal scope: range/instance slots plus approved mask slots."""
    con = S.connect(project_dir)
    try:
        idata, _ = S.get(con, "review_events", task.source_issue_event_id)
        issue = D.ReviewEvent.model_validate_json(json.dumps(idata))
        rev, contract = P._resolve_revision(con, issue.clip_revision_id)
        holds = contract.timing.holds
        slots: set[int] = set()
        if issue.frame_instance_id:
            try:
                fdata, _ = S.get(con, "frame_instances", issue.frame_instance_id)
                fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
                slots.add(fi.slot)
            except KeyError:
                pass
        if issue.frame_range is not None:
            start, end = issue.frame_range
            acc = 0
            for s, h in enumerate(holds):
                if acc <= end and start < acc + h:
                    slots.add(s)
                acc += h
        if task.edit_mask_id:
            try:
                mdata, _ = S.get(con, "edit_masks", task.edit_mask_id)
                m = D.EditMask.model_validate_json(json.dumps(mdata))
                slots.update(m.covered_slots)
            except KeyError:
                pass
        return slots
    finally:
        con.close()


def allowed_region(project_dir: str, task: D.CorrectionTask,
                   slot: int) -> bytes | None:
    """Per-slot allowed-edit raster (row-major 0/1) at canvas size, or None.

    None means no pixel of this slot may change. The region is the union of
    the issue ROI (when the slot is temporally in scope) and the approved mask
    (when the slot is mask-covered).
    """
    from ..media.canonical import canonical_pixels
    con = S.connect(project_dir)
    try:
        idata, _ = S.get(con, "review_events", task.source_issue_event_id)
        issue = D.ReviewEvent.model_validate_json(json.dumps(idata))
        rev, contract = P._resolve_revision(con, issue.clip_revision_id)
        w, h = contract.canvas.width, contract.canvas.height
        temporal = scope_slots(project_dir, task)
        if slot not in temporal:
            return None
        allow = bytearray(w * h)
        if issue.roi is not None:
            for y in range(max(0, issue.roi.top), min(h, issue.roi.bottom)):
                for x in range(max(0, issue.roi.left), min(w, issue.roi.right)):
                    allow[y * w + x] = 1
        if task.edit_mask_id:
            try:
                mdata, _ = S.get(con, "edit_masks", task.edit_mask_id)
                m = D.EditMask.model_validate_json(json.dumps(mdata))
            except KeyError:
                m = None
            if m is not None and slot in m.covered_slots:
                adata, _ = S.get(con, "assets", m.mask_asset_id)
                raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
                cur = hashlib.sha256(raw).hexdigest()
                if cur != m.mask_byte_sha256:
                    raise InvalidInput(f"mask asset {m.mask_asset_id}: bytes changed since approval")
                img = Image.open(S.blob_path(project_dir, adata["byte_sha256"])).convert("L")
                if img.size != (w, h):
                    raise InvalidInput("approved mask no longer matches the canvas")
                px = img.tobytes()
                for i, b in enumerate(px):
                    if b > 127:
                        allow[i] = 1
        if not any(allow):
            return None
        return bytes(allow)
    finally:
        con.close()
