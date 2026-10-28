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
        references, ref_byte_hashes, authority = _resolve_guide_references(
            project_dir, con, contract)
        # Relevant annotations only: bound to this revision's frames or source
        # assets. Unrelated project annotations never validate or invalidate
        # this evidence.
        frame_id_set = set(rev.frame_instance_ids)
        asset_id_set = set(aids)
        relevant = []
        for r in con.execute("SELECT id, data FROM annotation_revisions").fetchall():
            try:
                ad = json.loads(r["data"])
            except Exception:
                continue
            if ad.get("frame_instance_id") in frame_id_set \
                    or ad.get("source_asset_id") in asset_id_set:
                relevant.append({"id": r["id"],
                                 "sha256": hashlib.sha256(r["data"].encode()).hexdigest()})
        relevant.sort(key=lambda a: a["id"])
        world_positions, planted = _resolve_world_trace(project_dir, con, rev, contract)
        transitions = _resolve_transition_traces(con, rev)
        repair = _resolve_repair_context(project_dir, con, rev)
        rctx = dict(repair) if repair else {}
        if world_positions is not None:
            rctx.setdefault("world_trace_revision_ids", [])
        ctx = {"frame_byte_hashes": byte_hashes, "reference_byte_hashes": ref_byte_hashes,
               "character": character, "character_absent": character is None,
               "registration": {"records": reg_records,
                                "complete": all(x is not None for x in reg_records)},
               "annotation_hashes": sorted(a["sha256"] for a in relevant),
               "annotations": relevant,
               "authority": authority,
               "transitions": transitions,
               "presented_holds": presented,
               "byte_hashes_complete": True, "origin": "stored-service"}
        if repair:
            ctx["repair"] = repair
        lock = dep_lock_id or _default_lock_id()
        ev = EV.evaluate_frames(contract, frames, references, dep_lock_id=lock,
                                world_positions=world_positions, planted=planted,
                                context=ctx)
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
    measuring against fabricated authority. The returned authority binding
    freezes which exact approval/guide conditioned this evaluation, so a later
    re-approval cannot silently reinterpret old evidence.
    """
    try:
        from . import approvals as A
        # Stage B: freeze to the contract's declared guide, not the latest
        # approval. An old contract never silently follows a new guide
        # approval; new work needs an explicit rebind/new contract.
        declared = (contract.references or {}).get("motion_guide_revision")
        if not declared:
            return {}, {}, {}
        try:
            gdata, _ = S.get(con, "motion_guides", declared)
        except KeyError:
            return {}, {}, {}
        # Find the human approval that binds this exact guide (immutable
        # history, even if superseded by a newer approval for new work).
        approval = None
        for r in con.execute("SELECT data FROM reference_approvals").fetchall():
            try:
                ap = D.ReferenceApproval.model_validate_json(r["data"])
            except Exception:
                continue
            if ap.character_revision_id == contract.character_revision_id \
                    and ap.motion_guide_id == declared:
                if A.approval_event_is_human(project_dir, ap.event_id):
                    if approval is None or ap.created_at >= approval.created_at:
                        approval = ap
        if approval is None:
            return {}, {}, {}
        authority = {"approval_id": approval.id,
                     "approval_event_id": approval.event_id,
                     "motion_guide_id": declared,
                     "character_revision_id": contract.character_revision_id}
        guide = D.MotionGuide.model_validate_json(json.dumps(gdata))
        by_phase = {e.phase: e for e in guide.entries}
        refs, hashes = {}, {}
        for entry in contract.phase_schedule:
            ge = by_phase.get(entry.phase)
            if ge is None:
                return {}, {}, {}
            row = con.execute("SELECT data FROM assets WHERE id=?", (ge.asset_id,)).fetchone()
            if row is None:
                return {}, {}, {}
            blob = S.blob_path(project_dir, json.loads(row["data"])["byte_sha256"])
            if not blob.is_file():
                return {}, {}, {}
            from PIL import Image as _Image
            refs[entry.slot] = _Image.open(blob).convert("RGBA")
            hashes[entry.slot] = json.loads(row["data"])["byte_sha256"]
        return refs, hashes, authority
    except Exception:
        return {}, {}, {}


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


def record_world_trace(project_dir: str, revision_id: str,
                       positions: list[list[float]], planted: list[bool],
                       units: str = "world_units") -> D.WorldTrace:
    """Store frozen per-tick world grounding for one revision (operator/model tool).

    Length must equal the contract's total held ticks; evaluation binds the
    trace to world_sliding/declared_contacts instead of passing silently.
    """
    con = S.connect(project_dir)
    try:
        try:
            rdata, _ = S.get(con, "clip_revisions", revision_id)
        except KeyError:
            raise InvalidInput(f"unknown clip revision {revision_id}")
        rev = D.ClipRevision.model_validate_json(json.dumps(rdata))
        cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        total = contract.timing.total_ticks()
        if len(positions) != total or len(planted) != total:
            raise InvalidInput(
                f"world trace covers {len(positions)} ticks vs {total} held: "
                "a partial trace can never ground sliding/contact checks")
        for pos in positions:
            if not isinstance(pos, (list, tuple)) or len(pos) != 2 \
                    or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                           or v != v or abs(v) == float("inf") for v in pos):
                raise InvalidInput("world positions must be finite [x, y] pairs")
        if any(not isinstance(b, bool) for b in planted):
            raise InvalidInput("planted flags must be booleans, one per tick")
        wt = D.WorldTrace(id=f"wtrace-{revision_id}", clip_revision_id=revision_id,
                          positions=[[float(v) for v in pos] for pos in positions],
                          planted=list(planted), units=units)
        with S.atomic(con):
            try:
                S.stage(con, wt)
            except S.ConflictError:
                raise S.ConflictError(
                    f"world trace for {revision_id} already recorded (frozen)")
    finally:
        con.close()
    return wt


def _resolve_world_trace(project_dir: str, con, rev: D.ClipRevision,
                         contract: D.ClipContractRevision):
    """Load the stored per-tick grounding for this revision, if exactly one exists."""
    rows = con.execute("SELECT data FROM world_traces WHERE id=?",
                       (f"wtrace-{rev.id}",)).fetchall()
    if not rows:
        return None, None
    wt = D.WorldTrace.model_validate_json(rows[0]["data"])
    total = contract.timing.total_ticks()
    if len(wt.positions) != total or len(wt.planted) != total:
        return None, None  # malformed legacy trace: checks stay UNMEASURED, loudly
    return [tuple(p) for p in wt.positions], list(wt.planted)


def _resolve_transition_traces(con, rev: D.ClipRevision) -> list[dict]:
    """Bound interruption evidence for this revision as departure or entry."""
    out = []
    try:
        rows = con.execute("SELECT data FROM transition_traces").fetchall()
    except Exception:
        return out
    for r in rows:
        try:
            td = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if td.get("departure_revision_id") == rev.id or td.get("entry_revision_id") == rev.id:
            out.append({"id": td.get("id"), "verdict": td.get("verdict"),
                        "departure_tick": td.get("departure_tick"),
                        "entry_first_tick": td.get("entry_first_tick"),
                        "world_distance": td.get("world_distance")})
    return out


def _resolve_repair_context(project_dir: str, con, rev: D.ClipRevision):
    """Bind baseline pixels + approved edit support for a repaired revision.

    Returns None for non-repaired revisions (repair_protection then stays
    UNMEASURED when required). For a child of a repaired baseline, the baseline
    is the parent's stored frames and the allowed support is the union of the
    task's approved mask/ROI per repaired slot.
    """
    if not rev.parent_revision_id:
        return None
    try:
        from . import masks as _M
        from ..media.canonical import canonical_pixels as _canon
        from PIL import Image as _Image
        import io as _io
        parent = None
        try:
            pdata, _ = S.get(con, "clip_revisions", rev.parent_revision_id)
            parent = D.ClipRevision.model_validate_json(json.dumps(pdata))
        except KeyError:
            return None
        task = None
        for r in con.execute("SELECT data FROM correction_tasks").fetchall():
            try:
                # row data is already a JSON string; never double-encode it.
                cand = D.CorrectionTask.model_validate_json(r["data"])
            except Exception:
                continue
            if cand.baseline_revision_id == rev.parent_revision_id and cand.edit_mask_id:
                task = cand
                break
        if task is None:
            return None
        base_by_slot: dict[int, bytes] = {}
        base_byte_by_slot: dict[int, str] = {}
        for fid in parent.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
            adata, _ = S.get(con, "assets", fi.asset_id)
            raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
            base_by_slot[fi.slot] = _canon(_Image.open(_io.BytesIO(raw)))
            base_byte_by_slot[fi.slot] = adata["byte_sha256"]
        child_by_slot: dict[int, str] = {}
        for fid in rev.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
            child_by_slot[fi.slot] = fi.asset_id
        parent_by_slot: dict[int, str] = {}
        for fid in parent.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            fi = D.FrameInstance.model_validate_json(json.dumps(fdata))
            parent_by_slot[fi.slot] = fi.asset_id
        repaired = sorted(s for s, aid in child_by_slot.items()
                          if parent_by_slot.get(s) != aid)
        if not repaired:
            return None
        allowed = []
        n = max(child_by_slot) + 1
        for slot in range(n):
            region = _M.allowed_region(project_dir, task, slot)
            allowed.append(bytearray(region) if region is not None else bytearray(len(base_by_slot[slot]) // 4))
        # Stage B: repair identity is part of the evidence key so distinct
        # support yields distinct context and a narrowed mask cannot reuse an
        # old PASS. Baseline byte hashes bind the exact parent pixels measured.
        mask_id = getattr(task, "edit_mask_id", None)
        try:
            mdata, _ = S.get(con, "edit_masks", mask_id) if mask_id else (None, None)
            support_id = json.loads(mdata)["mask_byte_sha256"] if mdata else None
        except Exception:
            support_id = None
        return {"baseline": [base_by_slot[s] for s in range(n)],
                "allowed_mask": allowed,
                "protected_mask": None,
                "repaired_slots": repaired,
                "baseline_byte_sha256": [base_byte_by_slot[s] for s in range(n)],
                "task_id": getattr(task, "id", None),
                "mask_id": mask_id,
                "support_id": support_id or mask_id}
    except Exception:
        return None


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
    # Composed displacement is what actually moves pixels: six dx=2 steps
    # under a 2px budget compose to a 12px translation and are refused here.
    total_dx = sum(op.dx for op in spec.ops)
    total_dy = sum(op.dy for op in spec.ops)
    if abs(total_dx) > budget or abs(total_dy) > budget:
        raise InvalidInput(
            f"composed translation ({total_dx},{total_dy}) exceeds frozen budget "
            f"{budget}px: per-operation limits do not compose past the bound")
    if spec.per_pose_scale and contract.allowed_transforms.per_pose_scale is not True:
        raise InvalidInput("per-pose scale is frozen off by this contract")
    return spec


def _verify_translation_pixels(project_dir: str, con, contract: D.ClipContractRevision,
                                base_by_slot: list[tuple[int, str, str]],
                                slot_asset_ids: dict[int, str],
                                spec: D.TransformSpec | None) -> None:
    """Independently verify the recorded transform against canonical pixels.

    For every replaced slot carrying a translation record, applying the
    composed translation to the baseline slot image must reproduce the
    candidate pixels exactly. A schema-shaped record that disagrees with the
    rendered pixels is refused; the registration keeps its `verified_translate`
    label only when measurement agrees.
    """
    if spec is None or not spec.ops:
        return
    from PIL import Image as _Image
    from ..media.canonical import canonical_pixels as _canon, pixel_sha256 as _pxh
    import io as _io
    dx = sum(op.dx for op in spec.ops)
    dy = sum(op.dy for op in spec.ops)
    w, h = contract.canvas.width, contract.canvas.height
    for slot, _, _ in base_by_slot:
        if slot not in slot_asset_ids:
            continue
        base_aid = next(aid for s, aid, _ in base_by_slot if s == slot)
        try:
            bdata, _ = S.get(con, "assets", base_aid)
            cdata, _ = S.get(con, "assets", slot_asset_ids[slot])
        except KeyError:
            raise InvalidInput("missing_input: translation verification needs stored assets")
        braw = S.blob_path(project_dir, bdata["byte_sha256"]).read_bytes()
        craw = S.blob_path(project_dir, cdata["byte_sha256"]).read_bytes()
        base = _Image.open(_io.BytesIO(braw)).convert("RGBA")
        if base.size != (w, h):
            raise InvalidInput(
                f"slot {slot}: baseline {base.size} != frozen canvas {(w, h)}: "
                "translation is measured on the native canvas only, never resampled")
        moved = _Image.new("RGBA", (w, h), (0, 0, 0, 0))
        moved.paste(base, (dx, dy))
        if _pxh(_canon(moved)) != _pxh(_canon(_Image.open(_io.BytesIO(craw)).convert("RGBA"))):
            raise InvalidInput(
                f"slot {slot}: recorded translation ({dx},{dy}) does not reproduce "
                "the candidate pixels; the transform record is not verified")


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
        # The `verified_translate` registration label is earned by measurement,
        # not by the record's shape: the composed translation must reproduce
        # the candidate pixels exactly.
        _verify_translation_pixels(project_dir, con, contract, base_aids,
                                    slot_asset_ids, transform)
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
                # Stage B: candidate asset bytes already contain the verified
                # translation (see _verify_translation_pixels). Storing the
                # translation again and re-applying it in playback would shift
                # pixels twice and also shift unchanged slots. Registration is
                # therefore [0,0] (already applied exactly once); the typed
                # TransformSpec is retained for provenance.
                method = "verified_translate" if transform and transform.ops else "frozen_native"
                S.stage(con, D.Registration(id=fi.registration_id, method=method,
                                            frame_instance_id=fi.id,
                                            translation_px=[0, 0],
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
