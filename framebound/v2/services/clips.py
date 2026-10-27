from __future__ import annotations

import hashlib
import json

from PIL import Image

from .. import domain as D
from .. import storage as S
from ..checks import evaluate as E
from ..media.canonical import canonical_pixels
from .errors import InvalidInput


def _images_for(con: S.sqlite3.Connection, project_dir: str, asset_ids: list[str]) -> list[Image.Image]:
    imgs = []
    for aid in asset_ids:
        row = con.execute("SELECT data FROM assets WHERE id=?", (aid,)).fetchone()
        if row is None:
            raise InvalidInput(f"missing_input: asset {aid} not stored")
        blob = S.blob_path(project_dir, json.loads(row["data"])["byte_sha256"])
        imgs.append(Image.open(blob).convert("RGBA"))
    return imgs


def create_revision(project_dir: str, contract_id: str, revision_id: str,
                    frame_asset_ids: list[str], phase_names: list[str],
                    origin_run_id: str | None = None) -> D.ResultEnvelope:
    con = S.connect(project_dir)
    try:
        try:
            cdata, _ = S.get(con, "contract_revisions", contract_id)
        except KeyError:
            raise InvalidInput(f"unknown contract revision {contract_id}")
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        n = len(contract.timing.holds)
        if len(frame_asset_ids) != n:
            raise InvalidInput(f"{len(frame_asset_ids)} frame assets vs {n} contract holds: "
                               "a truncated or padded sequence can never enter a revision")
        if len(phase_names) != n:
            raise InvalidInput(f"{len(phase_names)} phase names vs {n} contract holds: "
                               "every held frame needs its scheduled phase")
        schedule = {e.slot: e.phase for e in contract.phase_schedule}
        for slot, phase in enumerate(phase_names):
            if not isinstance(phase, str) or not phase.strip():
                raise InvalidInput(f"slot {slot}: phase name must be a non-empty string")
            if schedule.get(slot) != phase:
                raise InvalidInput(
                    f"slot {slot}: phase {phase!r} does not match scheduled {schedule.get(slot)!r}")
        with S.atomic(con):
            inst_ids = []
            for slot, (aid, phase) in enumerate(zip(frame_asset_ids, phase_names)):
                try:
                    S.get(con, "assets", aid)
                except KeyError:
                    raise InvalidInput(f"missing_input: asset {aid} not stored")
                fi = D.FrameInstance(id=f"{revision_id}-fi-{slot:02d}", clip_revision_id=revision_id,
                                     slot=slot, asset_id=aid, phase=phase,
                                     hold_ticks=contract.timing.holds[slot],
                                     registration_id=f"{revision_id}-reg",
                                     source_drawing_id=aid, derivation_recipe="imported:accepted-revision")
                S.stage(con, fi)
                inst_ids.append(fi.id)
            rev = D.ClipRevision(id=revision_id, contract_revision_id=contract_id,
                                 frame_instance_ids=inst_ids, origin_run_id=origin_run_id)
            S.stage(con, rev)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-clip-{revision_id}", revision_id=revision_id,
                            next_actions=["clip_evaluate", "brief_compile"])


def evaluate(project_dir: str, revision_id: str, dep_lock_id: str = "dev-no-lock") -> D.ResultEnvelope:
    con = S.connect(project_dir)
    try:
        rdata, _ = S.get(con, "clip_revisions", revision_id)
        rev = D.ClipRevision.model_validate_json(json.dumps(rdata))
        cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        aids = []
        for fid in rev.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            aids.append(D.FrameInstance.model_validate_json(json.dumps(fdata)).asset_id)
        frames = _images_for(con, project_dir, aids)
        ev = E.evaluate_frames(contract, frames, {}, dep_lock_id=dep_lock_id)
        ev.clip_revision_id = revision_id
        S.insert(con, ev)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-eval-{ev.id}", revision_id=revision_id,
                            technical_status=ev.technical_status,
                            coverage={"required_total": sum(1 for c in contract.constraints if c.required),
                                      "required_measured": sum(1 for r in ev.results
                                        if r.outcome in ("pass", "fail") and r.constraint_id in
                                        {c.id for c in contract.constraints if c.required})},
                            issues=[{"code": r.constraint_id, "scope": r.scope, "reason": r.reason}
                                    for r in ev.results if r.outcome in ("fail", "error", "unmeasured")],
                            artifacts=[{"id": ev.id, "role": "evaluation"}],
                            next_actions=["review_packet_create"] if ev.technical_status == D.TechnicalStatus.PASS
                            else ["repair_plan"])


def register_candidate(project_dir: str, baseline_revision_id: str, new_revision_id: str,
                       slot_asset_ids: dict[int, str], recipe: str) -> D.ResultEnvelope:
    """Register a repair/replacement candidate as a child revision (frozen recipe).

    slot_asset_ids: slot -> replacement asset id. Unlisted slots inherit baseline assets.
    Original references stay bundled; the candidate never becomes its own authority.
    """
    con = S.connect(project_dir)
    try:
        rdata, _ = S.get(con, "clip_revisions", baseline_revision_id)
        base = D.ClipRevision.model_validate_json(json.dumps(rdata))
        cdata, _ = S.get(con, "contract_revisions", base.contract_revision_id)
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        if "per-pose-fit" in recipe or "independent-fit" in recipe:
            raise InvalidInput("candidate declares per-pose fitting; blocked by frozen calibration")
        if "mirror" in recipe:
            chdata, _ = S.get(con, "character_revisions", contract.character_revision_id)
            if chdata.get("asymmetry", "symmetric") != "symmetric":
                raise InvalidInput("exact mirror prohibited as a new drawing for this asymmetric design; "
                                   "author the facing reference instead (mirror is a recorded transform, not new art)")
        n = len(contract.timing.holds)
        for slot in slot_asset_ids:
            if isinstance(slot, bool) or not isinstance(slot, int) or not (0 <= slot < n):
                raise InvalidInput(f"replacement slot {slot!r} outside 0..{n - 1}")
        if not isinstance(recipe, str) or not recipe.strip():
            raise InvalidInput("candidate recipe must be a non-empty recorded transform")
        base_aids = []
        for fid in base.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            f = D.FrameInstance.model_validate_json(json.dumps(fdata))
            base_aids.append((f.slot, f.asset_id, f.phase))
        with S.atomic(con):
            inst_ids = []
            for slot, aid, phase in base_aids:
                use = slot_asset_ids.get(slot, aid)
                try:
                    S.get(con, "assets", use)
                except KeyError:
                    raise InvalidInput(f"missing_input: asset {use} not stored")
                fi = D.FrameInstance(id=f"{new_revision_id}-fi-{slot:02d}", clip_revision_id=new_revision_id,
                                     slot=slot, asset_id=use, phase=phase,
                                     hold_ticks=contract.timing.holds[slot],
                                     registration_id=f"{new_revision_id}-reg",
                                     source_drawing_id=use, derivation_recipe=recipe)
                S.stage(con, fi)
                inst_ids.append(fi.id)
            rev = D.ClipRevision(id=new_revision_id, contract_revision_id=base.contract_revision_id,
                                 frame_instance_ids=inst_ids, parent_revision_id=baseline_revision_id)
            S.stage(con, rev)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-clip-{new_revision_id}",
                            revision_id=new_revision_id, next_actions=["clip_evaluate"])
