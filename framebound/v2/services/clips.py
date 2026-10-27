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
                                     registration_id=f"{revision_id}-fi-{slot:02d}-reg",
                                     source_drawing_id=aid, derivation_recipe="imported:accepted-revision")
                S.stage(con, fi)
                S.stage(con, D.Registration(id=fi.registration_id, method="frozen_native",
                                            frame_instance_id=fi.id, verified_by="import"))
                inst_ids.append(fi.id)
            rev = D.ClipRevision(id=revision_id, contract_revision_id=contract_id,
                                 frame_instance_ids=inst_ids, origin_run_id=origin_run_id)
            S.stage(con, rev)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-clip-{revision_id}", revision_id=revision_id,
                            next_actions=["clip_evaluate", "brief_compile"])


def _default_lock_id() -> str:
    from ..checks.evaluate import _lock_digest
    digest = _lock_digest()
    return f"requirements:{digest[:16]}" if digest else "dev-no-lock"


def evaluate(project_dir: str, revision_id: str, dep_lock_id: str | None = None) -> D.ResultEnvelope:
    """Evaluate a stored revision with the complete stored context.

    Resolves exact frame instances + held timing, independent same-phase guides
    from the stored motion-guide approval, character content, annotation hashes
    and registration records — never an unconditional empty reference map.
    Re-evaluating the same revision/context returns the stored record; changed
    inputs produce a new record that supersedes the previous one.
    """
    from ..checks import evaluate as EV
    con = S.connect(project_dir)
    try:
        try:
            rdata, _ = S.get(con, "clip_revisions", revision_id)
        except KeyError:
            raise InvalidInput(f"unknown clip revision {revision_id}")
        rev = D.ClipRevision.model_validate_json(json.dumps(rdata))
        cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        frames, aids, presented, byte_hashes = [], [], [], []
        reg_records = []
        for fid in rev.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
            aids.append(fi.asset_id)
            presented.append(fi.hold_ticks)
            row = con.execute("SELECT data FROM assets WHERE id=?", (fi.asset_id,)).fetchone()
            if row is None:
                raise InvalidInput(f"missing_input: asset {fi.asset_id} not stored")
            byte_hashes.append(json.loads(row["data"])["byte_sha256"])
            try:
                rrow = con.execute("SELECT data FROM registrations WHERE id=?",
                                   (fi.registration_id,)).fetchone()
                reg_records.append(json.loads(rrow["data"]) if rrow else None)
            except Exception:
                reg_records.append(None)
        frames = _images_for(con, project_dir, aids)
        try:
            chdata, _ = S.get(con, "character_revisions", contract.character_revision_id)
            character: dict | None = chdata
        except KeyError:
            character = None
        references, ref_byte_hashes = _resolve_guide_references(project_dir, con, contract)
        annotation_hashes = []
        for r in con.execute("SELECT data FROM annotation_revisions").fetchall():
            try:
                annotation_hashes.append(hashlib.sha256(r["data"].encode()).hexdigest())
            except Exception:
                continue
        ctx = {"frame_byte_hashes": byte_hashes, "reference_byte_hashes": ref_byte_hashes,
               "character": character, "character_absent": character is None,
               "registration": {"records": reg_records,
                                "complete": all(x is not None for x in reg_records)},
               "annotation_hashes": sorted(annotation_hashes),
               "presented_holds": presented,
               "byte_hashes_complete": True, "origin": "stored-service"}
        lock = dep_lock_id or _default_lock_id()
        ev = EV.evaluate_frames(contract, frames, references, dep_lock_id=lock, context=ctx)
        manifest = EV.manifest_of(ev) or {}
        assert manifest, "evaluator must return its canonical manifest"
        # stable record identity: same revision + same evidence returns stored
        for r in con.execute("SELECT data FROM evaluations").fetchall():
            try:
                prev = D.Evaluation.model_validate_json(r["data"])
            except Exception:
                continue
            if prev.clip_revision_id == revision_id \
                    and prev.evidence_manifest_sha256 == ev.evidence_manifest_sha256:
                return _envelope_for(contract, revision_id, prev)
        import uuid as _uuid
        ev.clip_revision_id = revision_id
        ev.id = f"eval-{_uuid.uuid4().hex[:12]}"
        latest = None
        for r in con.execute("SELECT data FROM evaluations").fetchall():
            try:
                cand = D.Evaluation.model_validate_json(r["data"])
            except Exception:
                continue
            if cand.clip_revision_id == revision_id and (
                    latest is None or cand.created_at >= latest.created_at):
                latest = cand
        if latest is not None:
            ev.supersedes = latest.id
        with S.atomic(con):
            S.stage(con, ev)
            blob_sha = S.store_blob(project_dir,
                                    json.dumps(manifest, sort_keys=True).encode())
            assert blob_sha == ev.evidence_manifest_sha256, "manifest blob must be self-consistent"
    finally:
        con.close()
    return _envelope_for(contract, revision_id, ev)


def _resolve_guide_references(project_dir: str, con, contract: D.ClipContractRevision):
    """Independent same-phase guides from the stored motion-guide approval.

    Any gap (no character, no approval, guide mismatch, missing bytes) yields an
    empty map: reference-needing checks then report UNMEASURED instead of
    measuring against fabricated authority.
    """
    try:
        from . import approvals as A
        approval = A.current_approval(project_dir, contract.character_revision_id)
        if not A.approval_event_is_human(project_dir, approval.event_id):
            return {}, {}
        gdata, _ = S.get(con, "motion_guides", approval.motion_guide_id)
        guide = D.MotionGuide.model_validate_json(json.dumps(gdata))
        by_phase = {e.phase: e for e in guide.entries}
        refs, hashes = {}, {}
        for entry in contract.phase_schedule:
            ge = by_phase.get(entry.phase)
            if ge is None:
                return {}, {}
            row = con.execute("SELECT data FROM assets WHERE id=?", (ge.asset_id,)).fetchone()
            if row is None:
                return {}, {}
            blob = S.blob_path(project_dir, json.loads(row["data"])["byte_sha256"])
            if not blob.is_file():
                return {}, {}
            from PIL import Image as _Image
            refs[entry.slot] = _Image.open(blob).convert("RGBA")
            hashes[entry.slot] = json.loads(row["data"])["byte_sha256"]
        return refs, hashes
    except Exception:
        return {}, {}


def _envelope_for(contract: D.ClipContractRevision, revision_id: str,
                  ev: D.Evaluation) -> D.ResultEnvelope:
    return D.ResultEnvelope(ok=True, operation_id=f"op-eval-{ev.id}", revision_id=revision_id,
                            technical_status=ev.technical_status,
                            coverage={"required_total": sum(1 for c in contract.constraints if c.required),
                                      "required_measured": sum(1 for r in ev.results
                                        if r.outcome in ("pass", "fail") and r.constraint_id in
                                        {c.id for c in contract.constraints if c.required})},
                            issues=[{"code": r.constraint_id, "scope": r.scope, "reason": r.reason}
                                    for r in ev.results if r.outcome in ("fail", "error", "unmeasured")],
                            artifacts=[{"id": ev.id, "role": "evaluation"},
                                       {"id": ev.evidence_manifest_sha256, "role": "evidence_manifest"}],
                            next_actions=["review_packet_create"] if ev.technical_status == D.TechnicalStatus.PASS
                            else ["repair_plan"])


def _validate_transform(contract: D.ClipContractRevision, transform: dict | None,
                        recipe: str) -> D.TransformSpec | None:
    """Typed recorded operations are the only transform authority.

    A free-text recipe never authorizes movement: mirror/per-pose-fit words in
    the recipe are a deny backstop for legacy strings, while real permission
    comes from a validated TransformSpec checked against the contract budget
    and the character's asymmetry.
    """
    if transform is None:
        low = recipe.lower()
        if "per-pose-fit" in low or "independent-fit" in low:
            raise InvalidInput("recipe declares per-pose fitting as free text: "
                               "bounded repair requires a typed transform record; "
                               "per-pose scale is frozen by contract")
        return None
    try:
        spec = D.TransformSpec.model_validate(transform)
    except Exception as e:
        raise InvalidInput(f"transform record invalid: {e}") from e
    budget = contract.allowed_transforms.rigid_translation_budget_px
    for op in spec.ops:
        if abs(op.dx) > budget or abs(op.dy) > budget:
            raise InvalidInput(f"translate ({op.dx},{op.dy}) exceeds frozen budget {budget}px")
    if spec.per_pose_scale and contract.allowed_transforms.per_pose_scale is not True:
        raise InvalidInput("per-pose scale is frozen off by this contract")
    return spec


def _check_mirror_policy(con, contract: D.ClipContractRevision, recipe: str,
                         transform: D.TransformSpec | None) -> None:
    """Mirror words or a typed mirror flag need a symmetric character; asymmetric
    designs must author the facing reference instead."""
    if transform is not None and not transform.mirror and "mirror" not in recipe.lower():
        return
    if transform is None and "mirror" not in recipe.lower():
        return
    try:
        chdata, _ = S.get(con, "character_revisions", contract.character_revision_id)
        asym = chdata.get("asymmetry", "symmetric")
    except KeyError:
        asym = "symmetric"
    if asym != "symmetric":
        raise InvalidInput("exact mirror prohibited as a new drawing for this asymmetric design; "
                           "author the facing reference instead (mirror is a recorded transform, not new art)")


def register_candidate(project_dir: str, baseline_revision_id: str, new_revision_id: str,
                       slot_asset_ids: dict[int, str], recipe: str,
                       transform: dict | None = None) -> D.ResultEnvelope:
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
        transform = _validate_transform(contract, transform, recipe)
        _check_mirror_policy(con, contract, recipe, transform)
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
                                     registration_id=f"{new_revision_id}-fi-{slot:02d}-reg",
                                     source_drawing_id=use, derivation_recipe=recipe)
                S.stage(con, fi)
                method = "verified_translate" if transform and transform.ops else "frozen_native"
                dx = sum(o.dx for o in transform.ops) if transform else 0
                dy = sum(o.dy for o in transform.ops) if transform else 0
                S.stage(con, D.Registration(id=fi.registration_id, method=method,
                                            frame_instance_id=fi.id,
                                            translation_px=[dx, dy],
                                            transform=transform or D.TransformSpec(),
                                            verified_by="register_candidate"))
                inst_ids.append(fi.id)
            rev = D.ClipRevision(id=new_revision_id, contract_revision_id=base.contract_revision_id,
                                 frame_instance_ids=inst_ids, parent_revision_id=baseline_revision_id)
            S.stage(con, rev)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-clip-{new_revision_id}",
                            revision_id=new_revision_id, next_actions=["clip_evaluate"])
