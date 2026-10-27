"""v2 offline demo: procedural cycle, clean pass, named faults, bounded repair selection.

Provenance: all art procedural-test; faults labeled, never accepted art. Offline, no providers.
"""
from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path

from PIL import Image

from . import domain as D
from .checks import evaluate as E
from .checks import fixtures as F


def run_demo(out_dir: str | Path) -> dict:
    out = Path(out_dir)
    fx = out / "fixtures"
    meta = F.build_cycle(fx)

    def load(rel: str) -> Image.Image:
        return Image.open(fx / rel).convert("RGBA")

    clean = [load(r) for r in meta["clean"]]
    refs = {i: load(r) for i, r in enumerate(meta["clean"])}
    from .checks.raster import centroid, feature_points
    from .media.canonical import canonical_pixels
    px0 = canonical_pixels(clean[0])
    ca = centroid(feature_points(px0, 64, 64, (255, 200, 40), F.CLASP_WINDOW))
    cb = centroid(feature_points(px0, 64, 64, (255, 200, 40), F.BUCKLE_WINDOW))
    span0 = math.dist(ca, cb)
    n = sum(1 for y in range(F.SUPPORT_WINDOW[1], F.SUPPORT_WINDOW[3])
            for x in range(F.SUPPORT_WINDOW[0], F.SUPPORT_WINDOW[2])
            if px0[(y * 64 + x) * 4 + 3] >= 128)
    contract = D.ClipContractRevision(
        id="contract-demo-run", character_revision_id="char-demo",
        action={"name": "run", "view": "side", "facing": "right", "loop": True},
        canvas={"width": 64, "height": 64, "units": "native_px"},
        timing={"ticks_per_second": 60, "holds": [4] * 8},
        references={"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-demo"},
        phase_schedule=[{"slot": i, "phase": p, "motion_reference_id": f"pose-{p}"}
                        for i, p in enumerate(["A_contact", "A_compression", "A_passing", "A_flight",
                                               "B_contact", "B_compression", "B_passing", "B_flight"])],
        constraints=[
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "body_area", "check": "silhouette_area", "required": True, "params": {"max_fraction": 0.18}},
            {"id": "torso_span", "check": "visible_span", "required": True,
             "params": {"color_a": [255, 200, 40], "color_b": [255, 200, 40], "window_a": F.CLASP_WINDOW,
                        "window_b": F.BUCKLE_WINDOW, "expected": span0, "max_delta": 3.0}},
            {"id": "phase", "check": "phase_correspondence", "required": True,
             "params": {"region": F.REGION, "grid": F.GRID, "alt_slots": [1, 2, 3, 4, 5, 6, 7]}},
            {"id": "support", "check": "declared_contacts", "required": True,
             "params": {"window": F.SUPPORT_WINDOW, "min_visible": max(1, n // 2)}},
            {"id": "look", "check": "appearance_palette", "required": True, "params": {"max_drift": 0.06}},
            {"id": "pulse", "check": "local_pulse", "required": True},
            {"id": "cadence", "check": "locked_cadence", "required": True},
            {"id": "seam", "check": "loop_seam", "required": True, "params": {"region": F.REGION, "grid": F.GRID}},
        ],
        allowed_transforms={"per_pose_scale": False, "rigid_translation_budget_px": 2})
    t0 = time.perf_counter()
    ev_clean = E.evaluate_frames(contract, clean, refs)
    ms = (time.perf_counter() - t0) / len(clean) * 1000
    # faulty batch: slot2 pulse, slot3 wrong phase, slot1 palette
    faulty = list(clean)
    faulty[2] = load(meta["faults"]["pulse"])
    faulty[3] = load(meta["faults"]["phase"])
    faulty[1] = load(meta["faults"]["palette"])
    ev_faulty = E.evaluate_frames(contract, faulty, refs)
    fault_codes = sorted({r.constraint_id for r in ev_faulty.results if r.outcome == "fail"})
    # bounded repair: correct slots restored (simulates an approved repair candidate)
    ev_repaired = E.evaluate_frames(contract, clean, refs)
    return {"profile": "v2", "clean_technical_status": ev_clean.technical_status.value,
            "clean_coverage": ev_clean.coverage_status.value,
            "faulty_technical_status": ev_faulty.technical_status.value,
            "fault_codes": fault_codes,
            "repair_selected_for_review": ev_repaired.technical_status.value == "pass",
            "check_ms_per_frame": round(ms, 3),
            "evidence_id": ev_clean.evidence_manifest_sha256,
            "provenance": "procedural-test fixtures only; no provider output; faults labeled, never accepted art"}


def run_benchmark() -> dict:
    """200-frame 256x256 procedural stress: report cold/warm, no unmeasured shortcuts."""
    import numpy as np
    from .checks.raster import alpha_mask, silhouette
    rng = np.random.default_rng(7)
    frames = []
    for _ in range(200):
        a = np.zeros((256, 256), dtype=np.uint8)
        a[60:200, 60:200] = 255
        noise = (rng.random((256, 256)) * 20).astype(np.uint8)
        frames.append((a, noise))
    def one_pass():
        t0 = time.perf_counter()
        for a, noise in frames:
            px = np.dstack([np.full((256, 256, 3), 120, dtype=np.uint8), (a > 128).astype(np.uint8) * 255]).tobytes()
            m = alpha_mask(px, 256, 256)
            silhouette(m, 256, 256)
        return time.perf_counter() - t0
    cold, warm = one_pass(), one_pass()
    return {"fixture": "stress-200", "frames": 200, "canvas": [256, 256],
            "cold_seconds": round(cold, 3), "warm_seconds": round(warm, 3),
            "cold_ms_per_frame": round(cold / 200 * 1000, 3),
            "warm_ms_per_frame": round(warm / 200 * 1000, 3),
            "note": "core raster only, excludes providers and video encoding; this dev machine"}
