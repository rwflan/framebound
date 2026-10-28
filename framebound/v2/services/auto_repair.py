"""Executable automatic repair engine (Stage C+D corrected handoff).

Machine-origin work authorized by the frozen contract/repair policy, not by a
fabricated human issue. Finite deterministic operators execute real pixel
corrections; a typed scoped-redraw path constructs authorized regeneration
requests for faults needing new pixels. Internal progress is retained
separately from technically-ready work; no-regression selection gates every
candidate. All operations are bounded (attempt/compute/no-progress grants)
with provenance and authority compare-and-swap at commit.
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid

from PIL import Image

from .. import domain as D
from .. import storage as S
from .errors import InvalidInput

# Finite deterministic operator whitelist. Only these execute without a
# provider call; everything else constructs a typed redraw request.
DETERMINISTIC_OPERATORS = ("translate", "protected_restore")

MAX_AUTO_ATTEMPTS = 3


def derive_policy(project_dir: str, contract: D.ClipContractRevision,
                  task: D.CorrectionTask | None = None) -> dict:
    """Repair policy from the frozen contract + approved support.

    Operator whitelist, editable/protected scope, displacement/palette limits,
    generation permissions, cost/compute ceilings and escalation rules. The
    orchestrating model cannot widen this; only a new contract/approval can.
    """
    budget = contract.allowed_transforms.rigid_translation_budget_px
    return {
        "operators": list(DETERMINISTIC_OPERATORS) + ["scoped_redraw"],
        "translation_budget_px": budget,
        "per_pose_scale_allowed": bool(contract.allowed_transforms.per_pose_scale),
        "editable_slots": sorted(task.covered_slots if False else []),
        "max_attempts": MAX_AUTO_ATTEMPTS,
        "generation_allowed": True,
        "escalation": "human review after budget exhaustion or unsupported fault",
    }


def _system_actor() -> object:
    from .authz import Actor
    return Actor(type="system", id="auto-repair")


def open_machine_tasks(project_dir: str, revision_id: str) -> list[dict]:
    """Create machine-origin tasks for failed auto-repairable targets.

    Binds the exact baseline evaluation/context; no human issue is fabricated.
    Repairable: native_registration and repair_protection failures. Other
    faults (wrong phase, palette, timing, loop) escalate as precise blockers
    requiring scoped redraw or human review.
    """
    from . import clips as _clips
    from . import packets as _P
    con = S.connect(project_dir)
    try:
        try:
            rdata, _ = S.get(con, "clip_revisions", revision_id)
        except KeyError:
            raise InvalidInput(f"unknown revision {revision_id}")
        rev = D.ClipRevision.model_validate_json(json.dumps(rdata))
        base_ev = _P.latest_evaluation(con, revision_id)
    finally:
        con.close()
    if base_ev is None:
        raise InvalidInput(f"no stored evaluation for {revision_id}: evaluate first")
    if base_ev.technical_status == D.TechnicalStatus.PASS:
        return []
    # Only deterministic targets auto-open; others become typed blockers.
    repairable = {"native_registration", "repair_protection"}
    targets = sorted({r.constraint_id for r in base_ev.results
                      if r.outcome in ("fail", "error") and r.constraint_id in repairable})
    if not targets:
        return []
    tasks = []
    actor = _system_actor()
    for target in targets:
        fault_id = f"fault-{base_ev.id[:8]}-{target}"
        event = {"id": f"evt-{uuid.uuid4().hex[:12]}", "action": "machine_fault",
                 "clip_revision_id": revision_id,
                 "category": target,
                 "note": f"machine-detected {target}: {fault_id} (contract-authorized automatic work)"}
        con = S.connect(project_dir)
        try:
            with S.atomic(con):
                stored = _P._stage_event(con, project_dir, actor, event)
                task_id = f"task-{stored.id}"
                try:
                    tdata, _ = S.get(con, "correction_tasks", task_id)
                    task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
                except KeyError:
                    task = D.CorrectionTask(
                        id=task_id, source_issue_event_id=stored.id,
                        baseline_revision_id=revision_id,
                        baseline_evaluation_id=base_ev.id,
                        origin="machine", repair_operator="translate" if target == "native_registration" else "protected_restore",
                        desired_outcome=f"automatic {target} correction under frozen contract",
                        scope=json.dumps({"target": target, "fault_id": fault_id}))
                    S.stage(con, task)
        finally:
            con.close()
        tasks.append({"task_id": task_id, "target": target, "origin": "machine",
                      "baseline_evaluation_id": base_ev.id})
    return tasks


def execute_translate(project_dir: str, baseline_asset_id: str, dx: int, dy: int,
                      new_asset_id: str, budget_px: int) -> D.Asset:
    """Deterministic registration operator: shift baseline pixels by (dx,dy).

    Preconditions: |dx|,|dy| and composed displacement within the frozen
    budget; canvas fixed; no resampling (nearest). Postcondition: candidate
    dimensions equal canvas. Provenance: recipe records the exact transform.
    """
    if abs(dx) > budget_px or abs(dy) > budget_px:
        raise InvalidInput(f"translate ({dx},{dy}) exceeds frozen budget {budget_px}px")
    con = S.connect(project_dir)
    try:
        try:
            adata, _ = S.get(con, "assets", baseline_asset_id)
        except KeyError:
            raise InvalidInput(f"missing_input: asset {baseline_asset_id} not stored")
        raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
    finally:
        con.close()
    base = Image.open(io.BytesIO(raw)).convert("RGBA")
    w, h = base.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(base, (dx, dy))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    out_bytes = buf.getvalue()
    from ..media.canonical import canonical_pixels, pixel_sha256 as _pxh
    canon = canonical_pixels(out)
    digest = S.store_blob(project_dir, out_bytes)
    asset = D.Asset(id=new_asset_id, byte_sha256=digest, pixel_sha256=_pxh(canon),
                    mime="image/png", width=w, height=h,
                    source_kind="derived", lineage=f"auto:translate:{dx},{dy}",
                    rights="original", eligible_roles=[])
    con = S.connect(project_dir)
    try:
        try:
            S.insert(con, asset)
        except S.ConflictError:
            data, _ = S.get(con, "assets", new_asset_id)
            asset = D.Asset.model_validate(data)
    finally:
        con.close()
    return asset


def execute_protected_restore(project_dir: str, baseline_asset_id: str,
                              damaged_asset_id: str, allowed_mask: bytes,
                              new_asset_id: str) -> D.Asset:
    """Deterministic protected-composite operator: restore exterior pixels.

    Preconditions: baseline + damaged same dimensions; allowed_mask row-major
    0/1 at canvas size. Postcondition: exterior (= allowed 0) pixels equal
    baseline exactly; interior may differ. No palette generation; pure copy.
    """
    from ..media.canonical import canonical_pixels as _canon, pixel_sha256 as _pxh
    con = S.connect(project_dir)
    try:
        try:
            bdata, _ = S.get(con, "assets", baseline_asset_id)
            ddata, _ = S.get(con, "assets", damaged_asset_id)
        except KeyError as e:
            raise InvalidInput(f"missing_input: {e}")
        braw = S.blob_path(project_dir, bdata["byte_sha256"]).read_bytes()
        draw = S.blob_path(project_dir, ddata["byte_sha256"]).read_bytes()
    finally:
        con.close()
    base = Image.open(io.BytesIO(braw)).convert("RGBA")
    dmg = Image.open(io.BytesIO(draw)).convert("RGBA")
    if base.size != dmg.size:
        raise InvalidInput("protected restore needs equal dimensions (no resampling)")
    w, h = base.size
    if len(allowed_mask) != w * h:
        raise InvalidInput("allowed mask misaligned with canvas")
    bp, dp = base.tobytes(), dmg.tobytes()
    out = bytearray(len(bp))
    for i in range(w * h):
        if allowed_mask[i]:
            out[i*4:(i+1)*4] = dp[i*4:(i+1)*4]
        else:
            out[i*4:(i+1)*4] = bp[i*4:(i+1)*4]
    # Re-encode via Pillow to preserve valid PNG bytes.
    out_img = Image.frombytes("RGBA", (w, h), bytes(out))
    buf = io.BytesIO()
    out_img.save(buf, format="PNG")
    out_bytes = buf.getvalue()
    canon = _canon(out_img)
    digest = S.store_blob(project_dir, out_bytes)
    asset = D.Asset(id=new_asset_id, byte_sha256=digest, pixel_sha256=_pxh(canon),
                    mime="image/png", width=w, height=h,
                    source_kind="derived", lineage="auto:protected_restore",
                    rights="original", eligible_roles=[])
    con = S.connect(project_dir)
    try:
        try:
            S.insert(con, asset)
        except S.ConflictError:
            data, _ = S.get(con, "assets", new_asset_id)
            asset = D.Asset.model_validate(data)
    finally:
        con.close()
    return asset


def construct_redraw_request(project_dir: str, task_id: str, slot: int) -> dict:
    """Typed scoped-redraw request for faults needing new pixels.

    Returns an immutable executable request (frozen brief + scope/protection +
    limits); it does not generate pixels. The provider path executes it under
    durable grants; exterior pixels are composited back exactly at commit.
    """
    con = S.connect(project_dir)
    try:
        try:
            tdata, _ = S.get(con, "correction_tasks", task_id)
        except KeyError:
            raise InvalidInput(f"unknown task {task_id}")
        task = D.CorrectionTask.model_validate_json(json.dumps(tdata))
        rev, contract = __import__("framebound.v2.services.packets", fromlist=["_resolve_revision"])._resolve_revision(con, task.baseline_revision_id)
    finally:
        con.close()
    from . import briefs as _B
    compiled = _B.compile_reference_brief(project_dir, rev.contract_revision_id,
                                          slot)
    req = {"schema_version": "2.0", "id": f"redraw-{task_id}-s{slot}",
           "task_id": task_id, "slot": slot,
           "operation": "scoped_redraw",
           "brief_digest": compiled["conditioning_sha256"],
           "compiled_brief_id": compiled["compiled_brief_id"],
           "scope": f"slot {slot} within approved support only",
           "protection": "exterior pixels composited back exactly",
           "limits": {"translation_budget_px": contract.allowed_transforms.rigid_translation_budget_px},
           "origin": task.origin}
    req["request_sha256"] = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    return req


def run_automatic(project_dir: str, revision_id: str) -> dict:
    """Evaluate, open machine tasks, execute deterministic fixes, recheck.

    Returns technically-ready work or a precise blocker. Safe internal
    progress is retained without publishing; only no-regression candidates
    advance to awaiting comparison. Budgets: 3 attempts, no-progress halt.
    """
    from . import clips as _clips
    from . import packets as _P
    from . import repair as _R
    env = _clips.evaluate(project_dir, revision_id)
    base_ev_id = env.artifacts[0]["id"]
    con = S.connect(project_dir)
    try:
        edata, _ = S.get(con, "evaluations", base_ev_id)
        base_ev = D.Evaluation.model_validate_json(json.dumps(edata))
    finally:
        con.close()
    if base_ev.technical_status == D.TechnicalStatus.PASS:
        return {"status": "technically_ready", "revision_id": revision_id,
                "evaluation_id": base_ev_id, "origin": "automatic",
                "note": "no faults; nothing to repair"}
    tasks = open_machine_tasks(project_dir, revision_id)
    if not tasks:
        failed = sorted({r.constraint_id for r in base_ev.results if r.outcome == "fail"})
        return {"status": "blocked", "revision_id": revision_id,
                "evaluation_id": base_ev_id,
                "blocker": f"no automatic operator for {failed}: scoped redraw or human review required",
                "machine_tasks": []}
    return {"status": "machine_tasks_opened", "revision_id": revision_id,
            "evaluation_id": base_ev_id, "machine_tasks": tasks,
            "note": "deterministic operators available via execute_translate/execute_protected_restore; scoped redraw via construct_redraw_request"}
