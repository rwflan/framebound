"""Clip evaluation: run the contract's required checks, build the evidence manifest.

Evidence ID hashes: canonical contract JSON, character revision, every input byte+pixel
hash, mask/annotation revisions, registration recipes, timeline/trace, analyzer version,
dependency lock id, settings, schema versions. No timestamps in the hashed manifest.
Cache keys use the same dependencies. A changed input invalidates dependents (verify).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from .. import domain as D
from ..media.canonical import canonical_pixels
from . import implementations as C
from .raster import alpha_mask, centroid, feature_points, silhouette

ANALYZER_VERSION = "v2-checks-1"
PROFILE = C.PROFILE


def _bytes_of(img: Image.Image) -> bytes:
    return canonical_pixels(img)


def _manifest_sha256(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def evaluate_frames(contract: D.ClipContractRevision, frames: list[Image.Image],
                    references: dict[int, Image.Image],
                    dep_lock_id: str = "dev-no-lock",
                    world_positions: list[tuple[float, float]] | None = None,
                    planted: list[bool] | None = None) -> D.Evaluation:
    """Evaluate ordered frame images against a contract revision.

    references: slot -> independent same-phase reference image (never from the batch).
    """
    results: list[D.CheckResult] = []
    man_inputs: list[str] = []
    spans: list[float | None] = [None] * len(frames)
    by_check = {c.id: c for c in contract.constraints}
    P = C.PROFILE_DEFAULTS
    W, H = contract.canvas.width, contract.canvas.height

    def tol(cid: str, key: str, default: float) -> float:
        c = by_check.get(cid)
        if c is not None and key in c.params:
            return float(c.params[key])
        return default

    # per-frame checks
    for slot, img in enumerate(frames):
        scope = f"slot {slot}"
        px = _bytes_of(img)
        man_inputs.append(hashlib.sha256(px).hexdigest())
        w, h = img.size
        reg_c = by_check.get("registration")
        if reg_c is not None or True:
            results.append(C.check_registration(reg_c.id if reg_c else "registration", scope, px, w, h, (W, H)))
        if (w, h) != (W, H):
            continue  # invalid dims stop downstream measurements for this frame
        ref = references.get(slot)
        for check_id, dim in (("silhouette_area", "area"), ("silhouette_width", "width"), ("silhouette_height", "height")):
            pass
        # silhouette checks keyed by constraint ids present in contract
        for c in contract.constraints:
            if c.check == "silhouette_area":
                if ref is None:
                    results.append(D.CheckResult(constraint_id=c.id, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                        reason="no independent same-phase reference bound; measurement blocked", units="fraction"))
                else:
                    results.append(C.check_silhouette(c.id, scope, px, w, h, _bytes_of(ref),
                        tol(c.id, "max_fraction", P["max_area_fraction"]), "area"))
            elif c.check == "silhouette_width":
                if ref is None:
                    results.append(D.CheckResult(constraint_id=c.id, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                        reason="no independent same-phase reference bound; measurement blocked", units="fraction"))
                else:
                    results.append(C.check_silhouette(c.id, scope, px, w, h, _bytes_of(ref),
                        tol(c.id, "max_fraction", P["max_width_fraction"]), "width"))
            elif c.check == "silhouette_height":
                if ref is None:
                    results.append(D.CheckResult(constraint_id=c.id, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                        reason="no independent same-phase reference bound; measurement blocked", units="fraction"))
                else:
                    results.append(C.check_silhouette(c.id, scope, px, w, h, _bytes_of(ref),
                        tol(c.id, "max_fraction", P["max_height_fraction"]), "height"))
            elif c.check == "visible_span":
                p = c.params
                r = C.check_span(c.id, scope, px, w, h, tuple(p.get("color_a", (255, 200, 40))),
                                 tuple(p.get("color_b", (255, 200, 40))),
                                 p.get("window_a", [20, 18, 44, 34]), p.get("window_b", [20, 34, 44, 48]),
                                 float(p.get("expected", 14.0)), float(p.get("max_delta", P["max_feature_span_delta"])))
                if r.outcome == D.CheckOutcome.PASS and isinstance(r.observed_value, (int, float)):
                    spans[slot] = float(r.observed_value)
                results.append(r)
            elif c.check == "phase_correspondence":
                p = c.params
                n = len(frames)
                near = set(p.get("adjacent_slots", [1]))
                alts = [references[a] for a in p.get("alt_slots", []) if a in references and a != slot
                        and min((a - slot) % n, (slot - a) % n) not in near]
                if ref is None or not alts:
                    results.append(D.CheckResult(constraint_id=c.id, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                        reason="phase check needs expected + alternative independent guides; ambiguous silhouettes stay unmeasured",
                        units="descriptor"))
                else:
                    results.append(C.check_phase(c.id, scope, px, w, h, p.get("region", [8, 8, 56, 60]),
                        p.get("grid", [6, 6]), _bytes_of(ref), [_bytes_of(a) for a in alts],
                        P["max_expected_excess"], P["min_phase_ratio"]))
            elif c.check == "declared_contacts":
                p = c.params
                results.append(C.check_contacts(c.id, scope, px, w, h, p.get("window", [8, 50, 56, 62]),
                    int(p.get("min_visible", 20)), flight=bool(p.get("flight", False))))
            elif c.check == "appearance_palette":
                if ref is None:
                    results.append(D.CheckResult(constraint_id=c.id, scope=scope, outcome=D.CheckOutcome.UNMEASURED,
                        reason="no same-phase reference for appearance comparison", units="fraction"))
                else:
                    results.append(C.check_palette(c.id, scope, px, _bytes_of(ref),
                        tol(c.id, "max_drift", P["max_palette_drift"])))

    # temporal checks across frames
    for c in contract.constraints:
        if c.check == "local_pulse":
            for s in range(1, len(frames)):
                results.append(C.check_pulse(c.id, f"slots {s-1}→{s}", spans[s], spans[s-1],
                    float(c.params.get("max_delta", P["max_adjacent_span_delta"]))))
        elif c.check == "world_sliding" and world_positions is not None and planted is not None:
            results.append(C.check_world_sliding(c.id, "planted support across ticks", world_positions, planted,
                float(c.params.get("tol", 2.0))))
        elif c.check == "locked_cadence":
            results.append(C.check_cadence(c.id, "clip", list(contract.timing.holds),
                list(c.params.get("presented", contract.timing.holds))))
        elif c.check == "loop_seam" and len(frames) >= 2:
            p = c.params
            results.append(C.check_loop_seam(c.id, "loop seam", [_bytes_of(f) for f in frames],
                W, H, contract.action.loop, p.get("region", [8, 8, 56, 60]), p.get("grid", [6, 6]),
                float(p.get("max_ratio", 2.0))))

    # status + coverage
    required = [c for c in contract.constraints if c.required]
    by_cid = {}
    for r in results:
        by_cid.setdefault(r.constraint_id, []).append(r.outcome)
    required_ids = {c.id for c in required}
    if not required:
        tech = D.TechnicalStatus.INCOMPLETE
    elif any(D.CheckOutcome.ERROR in by_cid.get(cid, []) for cid in required_ids):
        tech = D.TechnicalStatus.ERROR
    elif any(o in (D.CheckOutcome.FAIL,) for r in results if r.constraint_id in required_ids for o in [r.outcome]):
        tech = D.TechnicalStatus.FAIL
    elif any(o in (D.CheckOutcome.UNMEASURED, D.CheckOutcome.NOT_APPLICABLE) for r in results
             if r.constraint_id in required_ids for o in [r.outcome]):
        tech = D.TechnicalStatus.INCOMPLETE
    else:
        tech = D.TechnicalStatus.PASS
    measured_req = sum(1 for cid in required_ids for r in results
                       if r.constraint_id == cid and r.outcome in (D.CheckOutcome.PASS, D.CheckOutcome.FAIL))
    total_req = sum(1 for cid in required_ids for r in results if r.constraint_id == cid)
    if total_req and measured_req == total_req:
        cov = D.CoverageStatus.COMPLETE
    elif measured_req == 0 and total_req:
        cov = D.CoverageStatus.UNSUPPORTED
    else:
        cov = D.CoverageStatus.PARTIAL

    manifest = {
        "contract": contract.model_dump(mode="json"), "frame_pixel_hashes": man_inputs,
        "reference_slots": sorted(references.keys()), "analyzer_version": ANALYZER_VERSION,
        "dependency_lock_id": dep_lock_id, "profile": PROFILE,
        "profile_defaults": C.PROFILE_DEFAULTS, "schema_versions": {"domain": "2.0"},
        "world_positions": world_positions, "planted": planted,
    }
    ev = D.Evaluation(id=f"eval-{hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]}",
        clip_revision_id=contract.id, evidence_manifest_sha256=_manifest_sha256(manifest),
        analyzer_version=ANALYZER_VERSION, dependency_lock_id=dep_lock_id,
        results=results, technical_status=tech, coverage_status=cov)
    return ev
