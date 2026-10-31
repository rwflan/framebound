"""Clip evaluation: explicit expected-result matrix, fail-closed status, evidence closure.

For every contract, the evaluator builds the full expected matrix (required
check x applicable scope) BEFORE measuring. Status is computed against that
matrix, not against whatever happened to execute:
- unknown check codes are rejected at contract validation (see params.py);
- a required check with missing inputs emits UNMEASURED with a reason;
- a missing result for an expected item is itself an analyzer ERROR;
- only contract-declared exemptions (flight slots, occluded slots, loop flag)
  may yield NOT_APPLICABLE.

Evidence binds the actual pixels: candidate pixel+byte hashes, reference pixel
hashes per slot (+ byte hashes when the service resolves stored assets), the
character/contract content, annotation hashes, registration, timeline/trace,
analyzer code identity, check configuration, schema versions and the
dependency-lock digest. Different reference pixels always change the evidence
ID even when slot numbers are unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from .. import domain as D
from ..media.canonical import canonical_pixels
from ..services.errors import InvalidInput
from . import implementations as C
from .raster import alpha_mask

ANALYZER_VERSION = "v2-checks-3-isolated"
PROFILE = C.PROFILE


def _code_sha256() -> str:
    h = hashlib.sha256()
    here = Path(__file__).parent
    for name in ("implementations.py", "evaluate.py", "raster.py", "registry.py", "params.py"):
        h.update((here / name).read_bytes())
    # The stored service's context resolver, canonical raster, and domain
    # schema are part of the measurement identity: changing how references,
    # annotations, registration, or pixels are resolved must invalidate old
    # evidence instead of silently reinterpreting it.
    for extra in (here.parent / "services" / "clips.py",
                  here.parent / "services" / "animation_context.py",
                  here.parent / "media" / "canonical.py",
                  here.parent / "domain.py"):
        h.update(extra.read_bytes())
    h.update((here.parent.parent / "v3" / "intake.py").read_bytes())
    return h.hexdigest()


def _packaged_lock_digest() -> str | None:
    """Lock digest from installed package resources (portable, no cwd search)."""
    try:
        from importlib import resources as _res
        for candidate in ("requirements.lock", "requirements-lock.sha256"):
            try:
                data = (_res.files("framebound") / candidate).read_bytes()
                if candidate.endswith(".sha256"):
                    return data.decode().strip().split()[0]
                return hashlib.sha256(data).hexdigest()
            except (FileNotFoundError, ModuleNotFoundError):
                continue
    except Exception:
        pass
    return None


def _lock_digest() -> str | None:
    digest = _packaged_lock_digest()
    if digest:
        return digest
    # Source-checkout developer fallback: nearest requirements.lock upward.
    # Installed distributions must provide the packaged resource above;
    # returning None signals "no packaged lock identity" instead of
    # silently hashing an unrelated file found via parent search.
    for parent in Path(__file__).resolve().parents:
        lock = parent / "requirements.lock"
        if lock.is_file():
            return hashlib.sha256(lock.read_bytes()).hexdigest()
    return None


def lock_identity() -> dict:
    """Machine-readable lock identity for /api/build-identity and verify."""
    packaged = _packaged_lock_digest()
    if packaged:
        return {"digest": packaged, "source": "packaged"}
    digest = _lock_digest()
    if digest:
        return {"digest": digest, "source": "source-checkout"}
    return {"digest": None, "source": "missing"}


PER_FRAME_CHECKS = {"native_registration", "silhouette_area", "silhouette_width",
                    "silhouette_height", "visible_span", "phase_correspondence",
                    "declared_contacts", "appearance_palette"}


def _matrix(contract: D.ClipContractRevision) -> list[tuple[str, str, str]]:
    """Expected (constraint_id, check, scope) items in stable order."""
    n = len(contract.timing.holds)
    items: list[tuple[str, str, str]] = []
    reg_ids = [c.id for c in contract.constraints if c.check == "native_registration"]
    reg_cid = reg_ids[0] if reg_ids else "registration"
    for slot in range(n):
        items.append((reg_cid, "native_registration", f"slot {slot}"))
    for c in contract.constraints:
        if c.check in PER_FRAME_CHECKS and c.check != "native_registration":
            for slot in range(n):
                items.append((c.id, c.check, f"slot {slot}"))
        elif c.check in PER_FRAME_CHECKS:
            for slot in range(n):
                if (c.id, f"slot {slot}") not in [(i, s) for i, _, s in items]:
                    items.append((c.id, c.check, f"slot {slot}"))
    for c in contract.constraints:
        if c.check == "local_pulse":
            for s in range(1, n):
                items.append((c.id, c.check, f"slots {s - 1}->{s}"))
            if contract.action.loop and n >= 2:
                items.append((c.id, c.check, f"slots {n - 1}->0 seam"))
        elif c.check == "world_sliding":
            items.append((c.id, c.check, "planted support across ticks"))
        elif c.check == "locked_cadence":
            items.append((c.id, c.check, "clip"))
        elif c.check == "loop_seam":
            items.append((c.id, c.check, "loop seam"))
        elif c.check == "repair_protection":
            items.append((c.id, c.check, "repaired slots"))
        elif c.check == "provenance_coverage":
            items.append((c.id, c.check, "authority inventory"))
    return items


class _Ctx:
    def __init__(self, contract, frames_px, refs_px, world_positions, planted, context):
        self.contract = contract
        self.frames_px = frames_px
        self.refs_px = refs_px
        self.world_positions = world_positions
        self.planted = planted
        self.context = context or {}
        self.by_check = {c.id: c for c in contract.constraints}
        self.n = len(frames_px)
        self.W, self.H = contract.canvas.width, contract.canvas.height
        self.P = C.PROFILE_DEFAULTS
        self.spans: list[float | None] = [None] * self.n
        self.gaps: list[str] = []

    def tol(self, cid, key, default):
        c = self.by_check.get(cid)
        if c is not None and isinstance(c.params, dict) and key in c.params:
            v = c.params[key]
            if isinstance(v, bool):
                raise InvalidInput(f"constraint {cid}: param {key} must be a number, not a boolean")
            return float(v)
        return default


def _frame_ok(ctx: _Ctx, slot: int) -> D.CheckResult | None:
    """Registration prerequisite: invalid media blocks dependent measurements as ERROR."""
    img_px = ctx.frames_px[slot]
    w, h = ctx.sizes[slot]
    reg_c = ctx.by_check.get("registration")
    cid = reg_c.id if reg_c else "registration"
    r = C.check_registration(cid, f'slot {slot}', img_px, w, h, (ctx.W, ctx.H))
    if (w,h)!=(ctx.W,ctx.H) or r.outcome!=D.CheckOutcome.PASS:return r
    from ...v3.intake import inspect
    intake=inspect(Image.frombytes('RGBA',(w,h),img_px))
    if not intake['eligible']:
        return D.CheckResult(constraint_id=cid,scope=f'slot {slot}',outcome=D.CheckOutcome.FAIL,reason='MVP intake: '+'; '.join(intake['reasons']))
    r = C.check_registration(cid, f"slot {slot}", img_px, w, h, (ctx.W, ctx.H))
    if (w, h) != (ctx.W, ctx.H) or r.outcome != D.CheckOutcome.PASS:
        return r
    return None


def _h_frame(ctx: _Ctx, cid: str, check: str, scope: str) -> D.CheckResult:
    slot = int(scope.split()[1])
    if check == "native_registration":
        records = (ctx.context.get('registration') or {}).get('records') or []
        if slot < len(records) and records[slot] and records[slot].get('translation_px') != [0,0]:
            return D.CheckResult(constraint_id=cid,scope=scope,outcome=D.CheckOutcome.UNMEASURED,
                reason='nonzero legacy registration requires explicit native re-materialization')
        px = ctx.frames_px[slot]
        w, h = ctx.sizes[slot]
        intake_failure=_frame_ok(ctx,slot)
        if intake_failure is not None:return intake_failure
        registration=C.check_registration(cid, scope, px, w, h, (ctx.W, ctx.H))
        c=ctx.by_check.get(cid)
        bound=(c.params or {}).get('max_anchor_drift_px') if c else None
        if registration.outcome==D.CheckOutcome.PASS and bound is not None:
            ref=ctx.refs_px.get(slot)
            if ref is None:
                return D.CheckResult(constraint_id=cid,scope=scope,outcome=D.CheckOutcome.UNMEASURED,reason='no independent phase anchor')
            def centroid(raster):
                points=[(i%w,i//w) for i,v in enumerate(alpha_mask(raster,w,h)) if v]
                return (sum(x for x,y in points)/len(points),sum(y for x,y in points)/len(points)) if points else None
            a,b=centroid(px),centroid(ref)
            if a is None or b is None:
                return D.CheckResult(constraint_id=cid,scope=scope,outcome=D.CheckOutcome.UNMEASURED,reason='empty silhouette cannot measure anchor')
            delta=max(abs(a[0]-b[0]),abs(a[1]-b[1]))
            return D.CheckResult(constraint_id=cid,scope=scope,outcome=D.CheckOutcome.PASS if delta<=bound else D.CheckOutcome.FAIL,
                observed_value=delta,expected_interval=[0,bound],units='native_px',reason=f'alpha centroid displacement {delta:g}px')
        return registration
    blocked = _frame_ok(ctx, slot)
    if blocked is not None:
        return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.ERROR,
            reason=f"blocked: registration prerequisite failed ({blocked.reason})")
    px = ctx.frames_px[slot]
    w, h = ctx.sizes[slot]
    ref = ctx.refs_px.get(slot)
    c = ctx.by_check[cid]
    p = c.params or {}
    if check in ("silhouette_area", "silhouette_width", "silhouette_height"):
        if ref is None:
            ctx.gaps.append(f"{cid}: slot {slot} has no independent same-phase reference")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason="no independent same-phase reference bound; measurement blocked", units="fraction")
        dim = {"silhouette_area": "area", "silhouette_width": "width",
               "silhouette_height": "height"}[check]
        key = {"silhouette_area": "max_area_fraction", "silhouette_width": "max_width_fraction",
               "silhouette_height": "max_height_fraction"}[check]
        return C.check_silhouette(cid, scope, px, w, h, ref,
            ctx.tol(cid, "max_fraction", ctx.P[key]), dim)
    if check == "visible_span":
        if slot in set(p.get("occluded_slots", [])):
            note = p.get("occlusion_note") or "declared occlusion in contract"
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.NOT_APPLICABLE,
                reason=f"{note}: shape unmeasured for this slot, needs human visual decision",
                units="native_px")
        r = C.check_span(cid, scope, px, w, h, tuple(p.get("color_a", (255, 200, 40))),
                         tuple(p.get("color_b", (255, 200, 40))),
                         p.get("window_a", [20, 18, 44, 34]), p.get("window_b", [20, 34, 44, 48]),
                         float(p.get("expected", 14.0)),
                         ctx.tol(cid, "max_delta", ctx.P["max_feature_span_delta"]))
        if r.outcome == D.CheckOutcome.PASS and isinstance(r.observed_value, (int, float)):
            ctx.spans[slot] = float(r.observed_value)
        return r
    if check == "phase_correspondence":
        n = ctx.n
        near = set(p.get("adjacent_slots", []))
        alts = [ctx.refs_px[a] for a in p.get("alt_slots", [])
                if a in ctx.refs_px and a != slot and min((a - slot) % n, (slot - a) % n) not in near]
        if ref is None or not alts:
            ctx.gaps.append(f"{cid}: slot {slot} lacks expected + alternative independent guides")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason="phase check needs expected + alternative independent guides; "
                       "ambiguous silhouettes stay unmeasured", units="descriptor")
        return C.check_phase(cid, scope, px, w, h, p.get("region", [8, 8, 56, 60]),
            p.get("grid", [6, 6]), ref, alts,
            ctx.tol(cid, "max_expected_excess", ctx.P["max_expected_excess"]),
            ctx.tol(cid, "min_phase_ratio", ctx.P["min_phase_ratio"]))
    if check == "declared_contacts":
        flight_slots = set(p.get("flight_slots", []))
        is_flight = bool(p.get("flight", False)) or slot in flight_slots
        if is_flight:
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.NOT_APPLICABLE,
                reason="contract-declared flight slot: no planted-foot requirement", units="pixels")
        color = p.get("support_color")
        kw = {"support_color": tuple(color)} if color else {}
        return C.check_contacts(cid, scope, px, w, h, p.get("window", [8, 50, 56, 62]),
            int(p.get("min_visible", 20)), flight=False, **kw)
    if check == "appearance_palette":
        if ref is None:
            ctx.gaps.append(f"{cid}: slot {slot} has no same-phase reference for appearance")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason="no same-phase reference for appearance comparison", units="fraction")
        return C.check_palette(cid, scope, px, ref,
            ctx.tol(cid, "max_drift", ctx.P["max_palette_drift"]))
    raise AssertionError(f"no per-frame dispatch for {check}")


def _h_temporal(ctx: _Ctx, cid: str, check: str, scope: str) -> D.CheckResult:
    c = ctx.by_check[cid]
    p = c.params or {}
    if check == "local_pulse":
        if scope.endswith("seam"):
            span, prev = ctx.spans[ctx.n - 1], ctx.spans[0]
        else:
            a, b = scope.split()[1].split("->")
            span, prev = ctx.spans[int(b)], ctx.spans[int(a)]
        return C.check_pulse(cid, scope, span, prev, ctx.tol(cid, "max_delta", ctx.P["max_adjacent_span_delta"]))
    if check == "world_sliding":
        total = sum(ctx.contract.timing.holds)
        if ctx.world_positions is not None and len(ctx.world_positions) != total:
            ctx.gaps.append(f"{cid}: world trace has {len(ctx.world_positions)} ticks vs {total} held")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason=f"world trace length does not match the {total} held ticks; cannot verify sliding",
                units="world_units")
        if ctx.planted is not None and ctx.world_positions is not None \
                and len(ctx.planted) != len(ctx.world_positions):
            ctx.gaps.append(f"{cid}: planted flags do not match trace length")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason="planted flags length differs from world trace length", units="world_units")
        if ctx.world_positions is None or ctx.planted is None:
            ctx.gaps.append(f"{cid}: no world trace bound (positions + planted flags)")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason="required world_sliding has no world positions/planted trace bound; "
                       "a passing verdict without the trace would be fabricated", units="world_units")
        return C.check_world_sliding(cid, scope, ctx.world_positions, ctx.planted,
            ctx.tol(cid, "tol", 2.0))
    if check == "locked_cadence":
        presented = list(p.get("presented", ctx.contract.timing.holds))
        if "presented_holds" in ctx.context and ctx.context["presented_holds"] is not None:
            presented = list(ctx.context["presented_holds"])
        return C.check_cadence(cid, scope, list(ctx.contract.timing.holds), presented)
    if check == "loop_seam":
        if not ctx.contract.action.loop:
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.NOT_APPLICABLE,
                reason="one-shot contract (loop=false): no artificial last->first seam test", units="descriptor")
        return C.check_loop_seam(cid, scope, list(ctx.frames_px), ctx.W, ctx.H, True,
            p.get("region", [8, 8, 56, 60]), p.get("grid", [6, 6]),
            ctx.tol(cid, "max_ratio", 2.0))
    if check == "repair_protection":
        rep = ctx.context.get("repair")
        if not rep or not rep.get("baseline") or not rep.get("allowed_mask"):
            ctx.gaps.append(f"{cid}: no repair context bound (baseline + edit support)")
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                reason="required repair_protection has no baseline/edit-support context bound; "
                       "protection cannot pass by default", units="pixels")
        base, allowed = rep["baseline"], rep["allowed_mask"]
        protected = rep.get("protected_mask")
        bad = 0
        for slot in rep.get("repaired_slots", list(range(ctx.n))):
            r = C.check_protection(cid, f"slot {slot}", base[slot], ctx.frames_px[slot],
                                   ctx.W, ctx.H, allowed[slot] if isinstance(allowed, list) else allowed,
                                   (protected[slot] if isinstance(protected, list) else protected)
                                   if protected is not None else None)
            if r.outcome != D.CheckOutcome.PASS:
                bad+=int(r.observed_value or 0)
        return D.CheckResult(constraint_id=cid,scope=scope,outcome=D.CheckOutcome.FAIL if bad else D.CheckOutcome.PASS,
            observed_value=bad,expected_interval=[0,0],
            reason=f'{bad} protected/exterior pixel violations across repaired slots' if bad else 'exterior + protected pixels identical across repaired slots',units='pixels')
    if check == "provenance_coverage":
        gaps = sorted(set(ctx.gaps))
        if gaps or not ctx.context.get("byte_hashes_complete", False):
            extra = [] if ctx.context.get("byte_hashes_complete", False) else ["origin byte hashes unavailable"]
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.FAIL,
                reason="authority/coverage gaps: " + "; ".join(gaps + extra), units="counts")
        if ctx.context.get("character_absent"):
            return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.FAIL,
                reason="no character revision bound: references cannot be tied to an approved identity",
                units="counts")
        return D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.PASS,
            reason="authority and coverage complete for the required matrix", units="counts")
    raise AssertionError(f"no temporal dispatch for {check}")


def _mask_hashes(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray)):
        return [hashlib.sha256(bytes(value)).hexdigest()]
    if isinstance(value, list):
        return [hashlib.sha256(bytes(item)).hexdigest() for item in value]
    raise InvalidInput('raster input must contain row-major bytes')


def evaluate_frames(contract: D.ClipContractRevision, frames: list[Image.Image],
                    references: dict[int, Image.Image],
                    dep_lock_id: str = "dev-no-lock",
                    world_positions: list[tuple[float, float]] | None = None,
                    planted: list[bool] | None = None,
                    context: dict | None = None) -> D.Evaluation:
    """Evaluate ordered frame images against a contract revision.

    references: slot -> independent same-phase reference image (never from the batch).
    context (service-built): frame/reference byte hashes, character content,
    registration, annotations, repair context, presented holds, origin label.
    Structural mismatches (frame count vs holds) raise: a truncated clip must
    never flow into a passing verdict.
    """
    n = len(contract.timing.holds)
    if len(frames) != n:
        raise InvalidInput(f"{len(frames)} frames vs {n} contract holds: a truncated or padded "
                           "sequence can never enter evaluation")
    ctx = context or {}
    frames_px = [canonical_pixels(f) for f in frames]
    refs_px = {s: canonical_pixels(r) for s, r in references.items()}
    state = _Ctx(contract, frames_px, refs_px, world_positions, planted, ctx)
    state.sizes = [f.size for f in frames]
    expected = _matrix(contract)
    results: list[D.CheckResult] = []
    seen: set[tuple[str, str]] = set()
    for cid, check, scope in expected:
        try:
            if check in PER_FRAME_CHECKS:
                r = _h_frame(state, cid, check, scope)
            else:
                r = _h_temporal(state, cid, check, scope)
        except InvalidInput:
            raise
        except Exception as e:
            r = D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.ERROR,
                reason=f"analyzer failure in {check}: {type(e).__name__}: {e}")
        if (cid, scope) in seen:
            r = D.CheckResult(constraint_id=cid, scope=scope, outcome=D.CheckOutcome.ERROR,
                reason="analyzer emitted a duplicate result for one matrix item")
        seen.add((cid, scope))
        results.append(r)
    produced = {(r.constraint_id, r.scope) for r in results}
    for cid, check, scope in expected:
        if (cid, scope) not in produced:
            results.append(D.CheckResult(constraint_id=cid, scope=scope,
                outcome=D.CheckOutcome.ERROR,
                reason=f"dispatch omission: no analyzer produced the expected {check} result"))

    reg_ids = [c.id for c in contract.constraints if c.check == "native_registration"]
    reg_cid = reg_ids[0] if reg_ids else "registration"
    required_ids = {c.id for c in contract.constraints if c.required} | {reg_cid}
    gated = [r for r in results if r.constraint_id in required_ids
             and r.outcome != D.CheckOutcome.NOT_APPLICABLE]
    if not required_ids or not gated:
        tech = D.TechnicalStatus.INCOMPLETE
    elif any(r.outcome == D.CheckOutcome.FAIL for r in gated):
        tech = D.TechnicalStatus.FAIL
    elif any(r.outcome == D.CheckOutcome.ERROR for r in gated):
        tech = D.TechnicalStatus.ERROR
    elif any(r.outcome == D.CheckOutcome.UNMEASURED for r in gated):
        tech = D.TechnicalStatus.INCOMPLETE
    else:
        tech = D.TechnicalStatus.PASS
    bad = sum(1 for r in results if r.outcome in (D.CheckOutcome.UNMEASURED, D.CheckOutcome.ERROR))
    measured = sum(1 for r in results if r.outcome in (D.CheckOutcome.PASS, D.CheckOutcome.FAIL,
                                                       D.CheckOutcome.NOT_APPLICABLE))
    if bad == 0 and measured == len(results):
        cov = D.CoverageStatus.COMPLETE
    elif measured == 0:
        cov = D.CoverageStatus.UNSUPPORTED
    else:
        cov = D.CoverageStatus.PARTIAL

    frame_hashes = [hashlib.sha256(px).hexdigest() for px in frames_px]
    ref_hashes = {str(s): hashlib.sha256(px).hexdigest() for s, px in refs_px.items()}
    # Stage B: repair support is part of the evidence identity. Different
    # allowed/protected support must yield a different context key; a narrowed
    # mask can never reuse an old PASS verdict.
    _rep = ctx.get("repair") or {}
    _allowed = _rep.get("allowed_mask")
    if isinstance(_allowed, (bytes, bytearray)):
        _allowed_h = [hashlib.sha256(bytes(_allowed)).hexdigest()]
    elif isinstance(_allowed, list):
        _allowed_h = [hashlib.sha256(bytes(m) if isinstance(m, (bytes, bytearray)) else b"").hexdigest()
                      for m in _allowed]
    else:
        _allowed_h = []
    _repair_key = {
        "repaired_slots": list(_rep.get("repaired_slots", [])),
        "allowed_mask_sha256": _allowed_h,
        "protected_present": _rep.get("protected_mask") is not None,
        "protected_mask_sha256": _mask_hashes(_rep.get('protected_mask')),
        "baseline_pixel_sha256": _mask_hashes(_rep.get('baseline')),
        "baseline_byte_sha256": _rep.get("baseline_byte_sha256", []),
        "task_id": _rep.get("task_id"),
        "mask_id": _rep.get("mask_id"),
        "support_id": _rep.get("support_id"),
    }
    manifest = {
        "contract": contract.model_dump(mode="json"),
        "character": ctx.get("character") or {"absent": True},
        "frames": [{"slot": i, "pixel_sha256": h,
                    "byte_sha256": (ctx.get("frame_byte_hashes") or [None] * n)[i]}
                   for i, h in enumerate(frame_hashes)],
        "references": {s: {"pixel_sha256": h,
                           "byte_sha256": (ctx.get("reference_byte_hashes") or {}).get(int(s))}
                       for s, h in ref_hashes.items()},
        "annotations": ctx.get("annotations", ctx.get("annotation_hashes", [])),
        "authority": ctx.get("authority", {}),
        "transitions": ctx.get("transitions", []),
        "registration": ctx.get("registration"),
        "repair": _repair_key,
        "timeline": {"holds": list(contract.timing.holds), "loop": contract.action.loop,
                     "world_positions": world_positions, "planted": planted},
        "analyzer": {"version": ANALYZER_VERSION, "code_sha256": _code_sha256(),
                     "profile": PROFILE, "profile_defaults": C.PROFILE_DEFAULTS},
        "check_config": [{"id": c.id, "check": c.check, "required": c.required,
                          "params": c.params} for c in contract.constraints],
        "schema_versions": {"domain": "2.0"},
        "dependency_lock": {"id": dep_lock_id, "digest": _lock_digest()},
        "origin": ctx.get("origin", "direct"),
    }
    manifest_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    ev = D.Evaluation(id=f"eval-{manifest_sha[:16]}",
        clip_revision_id=contract.id, evidence_manifest_sha256=manifest_sha,
        analyzer_version=ANALYZER_VERSION, dependency_lock_id=dep_lock_id,
        results=results, technical_status=tech, coverage_status=cov)
    object.__setattr__(ev, "_manifest_cache", manifest)  # side-channel for the storing service
    return ev


def manifest_of(ev: D.Evaluation) -> dict | None:
    """Retrieve the canonical manifest built alongside a fresh evaluate_frames result."""
    return getattr(ev, "_manifest_cache", None)
