"""P0 check implementations. Each returns a domain CheckResult with measured values.

Profiles: thresholds arrive via constraint params (calibrated per contract); the frozen
fallback profile PIXEL_ART_V1 is recorded in evidence whenever it is used.
"""
from __future__ import annotations

import math

from .. import domain as D
from .raster import (alpha_mask, centroid, descriptor_distance, feature_points,
                     occupancy_descriptor, quantized_palette_distance, silhouette)
from .registry import CheckSpec, register

PROFILE = "pixel-art-v1"
PROFILE_DEFAULTS = {"max_area_fraction": 0.18, "max_width_fraction": 0.15, "max_height_fraction": 0.12,
                    "max_palette_drift": 0.22, "max_expected_excess": 0.045, "min_phase_ratio": 1.5,
                    "max_centroid_step": 14.0, "max_anchor_distance": 8.0,
                    "max_feature_span_delta": 3.0, "max_adjacent_span_delta": 2.5, "min_alpha": 128}


def _res(cid: str, scope: str, outcome: D.CheckOutcome, reason: str, **kw) -> D.CheckResult:
    return D.CheckResult(constraint_id=cid, scope=scope, outcome=outcome, reason=reason, **kw)


register(CheckSpec(code="native_registration", applicability="every frame; required",
    required_inputs="asset pixels, frozen canvas", method="dimensions + nonempty alpha + frozen transform match",
    units="native_px", limits="blank/malformed fail closed", severity="error",
    blind_spots="cannot certify anatomy, only frame fit"))
register(CheckSpec(code="silhouette_area_drift", applicability="same-view, same-phase reference pairs",
    required_inputs="candidate + independent phase reference mask", method="area fraction vs reference",
    units="fraction", limits="profile bounds; cape/weapon motion can legitimately change bounds",
    blind_spots="whole-frame area cannot prove limb volume"))
register(CheckSpec(code="silhouette_width_drift", applicability="same-view, same-phase",
    required_inputs="candidate + reference", method="width fraction vs reference", units="fraction",
    limits="profile bounds", blind_spots="foreshortening needs compatible-pose profile, never standing frontal"))
register(CheckSpec(code="silhouette_height_drift", applicability="same-view, same-phase",
    required_inputs="candidate + reference", method="height fraction vs reference", units="fraction",
    limits="profile bounds", blind_spots="equal height can hide width/mass change"))
register(CheckSpec(code="phase_correspondence", applicability="run/cycle phases with independent guides",
    required_inputs="registered occupancy descriptor + expected + alternative guides",
    method="expected distance vs best alternative + gap", units="descriptor units",
    limits="flags likely wrong phase, not universal motion judgment",
    blind_spots="unlike phases can share silhouettes; never choose expected pose from the batch"))
register(CheckSpec(code="declared_contacts", applicability="planted phases with reviewed windows",
    required_inputs="sole/palm mask or alpha in declared window + support schedule",
    method="visible support fraction in window", units="fraction/px",
    blind_spots="image-plane support is not world-space non-sliding; flight phases exempt"))
register(CheckSpec(code="world_sliding", applicability="world-grounded trajectories, held drawings included",
    required_inputs="per-tick support point in stage/world units", method="planted-point drift while root moves",
    units="world units", limits="declared world tolerance",
    blind_spots="treadmill preview vs world-grounded trajectory differ; interior of held drawings checked per tick"))
register(CheckSpec(code="visible_span", applicability="declared visible feature pairs in reviewed regions",
    required_inputs="two feature colors + search windows + compatible-pose bound",
    method="feature-pair span vs master bound", units="native_px",
    blind_spots="stable costume features are scale proxies, not skeleton joints"))
register(CheckSpec(code="local_pulse", applicability="adjacent frames",
    required_inputs="adjacent spans", method="frame-to-frame span delta", units="native_px",
    limits="profile bound", blind_spots="smear frames and declared squash/stretch need exemptions"))
register(CheckSpec(code="appearance_palette_drift", applicability="masked part-level preferred; global fallback",
    required_inputs="candidate + same-phase reference", method="quantized histogram distance", units="fraction",
    limits="profile bound", blind_spots="global histogram misses swapped colors and identity drift; part masks can fail"))
register(CheckSpec(code="locked_cadence", applicability="every clip",
    required_inputs="contract holds vs presented holds", method="exact integer schedule compare", units="ticks",
    limits="any change fails", blind_spots="none; grace assessed by humans"))
register(CheckSpec(code="loop_seam", applicability="looped clips only",
    required_inputs="first/last drawings + loop flag", method="wraparound adjacency delta",
    units="descriptor units", limits="one-shots must NOT be seam-tested; terminal/handoff honored",
    blind_spots="a subtle idle may legitimately preserve silhouette"))
register(CheckSpec(code="repair_protection", applicability="repair candidates",
    required_inputs="baseline + candidate RGBA + edit support + protected regions",
    method="exact RGBA equality outside support; protected regions untouched", units="pixels",
    limits="hard mask in P0; filter halos must be inside support",
    blind_spots="compare pixels, not file bytes"))
register(CheckSpec(code="provenance_coverage", applicability="every evaluation",
    required_inputs="reference eligibility + annotation freshness + required matrix",
    method="missing authority/coverage inventory", units="counts",
    limits="correct-looking result with missing authority is incomplete",
    blind_spots="none; this check reports the gaps"))


def check_registration(cid: str, scope: str, px: bytes, w: int, h: int, canvas: tuple[int, int],
                       min_alpha: int = 128) -> D.CheckResult:
    if (w, h) != canvas:
        return _res(cid, scope, D.CheckOutcome.FAIL, f"frame {w}x{h} differs from frozen canvas {canvas[0]}x{canvas[1]}",
                    observed_value=f"{w}x{h}", units="native_px", expected_interval=None)
    m = alpha_mask(px, w, h, min_alpha)
    if sum(m) == 0:
        return _res(cid, scope, D.CheckOutcome.ERROR, "blank frame: zero foreground pixels; cannot pass shape checks",
                    observed_value=0, units="pixels")
    return _res(cid, scope, D.CheckOutcome.PASS, "dimensions match frozen canvas; foreground present",
                observed_value=sum(m), units="pixels")


def check_silhouette(cid: str, scope: str, px: bytes, w: int, h: int, ref_px: bytes,
                     tol: float, dim: str) -> D.CheckResult:
    m, r = alpha_mask(px, w, h), alpha_mask(ref_px, w, h)
    s, rs = silhouette(m, w, h), silhouette(r, w, h)
    if rs["area"] == 0:
        return _res(cid, scope, D.CheckOutcome.UNMEASURED,
                    "reference has zero foreground; same-phase independent reference required before measurement",
                    units="fraction")
    key = {"area": "area", "width": "width", "height": "height"}[dim]
    frac = abs(s[key] - rs[key]) / rs[key]
    if frac > tol:
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"{dim} drift {frac:.3f} exceeds bound {tol} vs same-phase reference",
                    observed_value=frac, units="fraction", expected_interval=[0, tol])
    return _res(cid, scope, D.CheckOutcome.PASS, f"{dim} within bound vs same-phase reference",
                observed_value=frac, units="fraction", expected_interval=[0, tol])


def check_phase(cid: str, scope: str, px: bytes, w: int, h: int, region: list[int], grid: list[int],
                expected: bytes, alternatives: list[bytes], max_excess: float, min_ratio: float) -> D.CheckResult:
    d = occupancy_descriptor(px, w, h, region, grid)
    de = descriptor_distance(d, occupancy_descriptor(expected, w, h, region, grid))
    others = [descriptor_distance(d, occupancy_descriptor(a, w, h, region, grid)) for a in alternatives]
    best = min(others) if others else float("inf")
    gap = best - de
    ratio = (best / de) if de > 0 else float("inf")
    if de - best > max_excess and ratio < min_ratio and math.isfinite(best):
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"frame matches another phase better: expected {de:.4f} vs best-alt {best:.4f} (gap {gap:.4f})",
                    observed_value=de, units="descriptor", expected_interval=[0, best])
    if not math.isfinite(best) or abs(gap) < max_excess:
        return _res(cid, scope, D.CheckOutcome.UNMEASURED,
                    "phase descriptor ambiguous: unlike phases share silhouette; needs human visual decision",
                    observed_value=de, units="descriptor")
    return _res(cid, scope, D.CheckOutcome.PASS, f"phase matches expected guide (gap {gap:.4f})",
                observed_value=de, units="descriptor")


def check_contacts(cid: str, scope: str, px: bytes, w: int, h: int, window: list[int],
                   min_visible: int, flight: bool = False) -> D.CheckResult:
    if flight:
        return _res(cid, scope, D.CheckOutcome.NOT_APPLICABLE, "flight phase has no planted-foot requirement",
                    units="pixels")
    l, t, r, b = window
    n = 0
    for y in range(max(0, t), min(h, b)):
        for x in range(max(0, l), min(w, r)):
            if px[(y * w + x) * 4 + 3] >= 128:
                n += 1
    if n < min_visible:
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"planted phase shows {n} support pixels in window, need {min_visible}",
                    observed_value=n, units="pixels", expected_interval=[min_visible, w * h])
    return _res(cid, scope, D.CheckOutcome.PASS, f"support present ({n} px in declared window)",
                observed_value=n, units="pixels")


def check_world_sliding(cid: str, scope: str, world_positions: list[tuple[float, float]],
                        planted: list[bool], tol: float) -> D.CheckResult:
    worst = 0.0
    for i in range(1, len(world_positions)):
        if planted[i] and planted[i - 1]:
            d = math.dist(world_positions[i], world_positions[i - 1])
            worst = max(worst, d)
    if worst > tol:
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"planted support slides {worst:.2f} world units across held ticks (tol {tol})",
                    observed_value=worst, units="world_units", expected_interval=[0, tol])
    return _res(cid, scope, D.CheckOutcome.PASS, f"planted support holds within {tol} world units",
                observed_value=worst, units="world_units")


def check_span(cid: str, scope: str, px: bytes, w: int, h: int, color_a: tuple[int, int, int],
               color_b: tuple[int, int, int], window_a: list[int], window_b: list[int],
               expected: float, max_delta: float) -> D.CheckResult:
    ca = centroid(feature_points(px, w, h, color_a, window_a))
    cb = centroid(feature_points(px, w, h, color_b, window_b))
    if ca is None or cb is None:
        return _res(cid, scope, D.CheckOutcome.UNMEASURED,
                    "required declared feature missing or ambiguous; needs reviewed annotation, blocks required gate",
                    units="native_px")
    span = math.dist(ca, cb)
    if abs(span - expected) > max_delta:
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"visible span {span:.2f}px vs bound {expected:.2f}px exceeds {max_delta}px",
                    observed_value=span, units="native_px", expected_interval=[expected - max_delta, expected + max_delta])
    return _res(cid, scope, D.CheckOutcome.PASS, f"visible span {span:.2f}px within bound",
                observed_value=span, units="native_px")


def check_pulse(cid: str, scope: str, span: float | None, prev_span: float | None, max_delta: float) -> D.CheckResult:
    if span is None or prev_span is None:
        return _res(cid, scope, D.CheckOutcome.UNMEASURED,
                    "pulse needs two measured spans; missing measurement propagates, never passes",
                    units="native_px")
    d = abs(span - prev_span)
    if d > max_delta:
        return _res(cid, scope, D.CheckOutcome.FAIL, f"local span pulse {d:.2f}px exceeds {max_delta}px",
                    observed_value=d, units="native_px", expected_interval=[0, max_delta])
    return _res(cid, scope, D.CheckOutcome.PASS, "no local pulse", observed_value=d, units="native_px")


def check_palette(cid: str, scope: str, px: bytes, ref: bytes, max_drift: float) -> D.CheckResult:
    d = quantized_palette_distance(px, ref)
    if d > max_drift:
        return _res(cid, scope, D.CheckOutcome.FAIL, f"palette drift {d:.3f} exceeds {max_drift}",
                    observed_value=d, units="fraction", expected_interval=[0, max_drift])
    return _res(cid, scope, D.CheckOutcome.PASS, "palette within bound", observed_value=d, units="fraction")


def check_cadence(cid: str, scope: str, holds: list[int], presented: list[int]) -> D.CheckResult:
    if holds != presented:
        return _res(cid, scope, D.CheckOutcome.FAIL, f"holds changed {holds} → {presented}: locked_cadence failure",
                    units="ticks")
    return _res(cid, scope, D.CheckOutcome.PASS, "holds match frozen schedule", units="ticks")


def check_loop_seam(cid: str, scope: str, drawings: list[bytes], w: int, h: int,
                    loop: bool, region: list[int], grid: list[int], max_ratio: float) -> D.CheckResult:
    """Loop closure: the last→first step must look like an ordinary adjacent step.

    Compares the seam distance against the worst in-cycle adjacent distance. A loop whose
    seam is far worse than its own steps has a visible hitch; an absolute near-zero demand
    would falsely require the first and last drawings to be identical poses.
    """
    if not loop:
        return _res(cid, scope, D.CheckOutcome.NOT_APPLICABLE,
                    "one-shot clip: no artificial last→first seam test; terminal/handoff honored", units="descriptor")
    if len(drawings) < 3:
        return _res(cid, scope, D.CheckOutcome.UNMEASURED,
                    "fewer than 3 drawings: no in-cycle baseline for seam comparison; needs more poses",
                    units="descriptor")
    desc = [occupancy_descriptor(d, w, h, region, grid) for d in drawings]
    adj = [descriptor_distance(desc[i], desc[(i + 1) % len(desc)]) for i in range(len(desc))]
    seam, worst_inner = adj[-1], max(adj[:-1])
    ratio = seam / worst_inner if worst_inner > 0 else (0.0 if seam == 0 else float("inf"))
    if ratio > max_ratio:
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"loop seam {seam:.4f} is {ratio:.2f}x the worst in-cycle step {worst_inner:.4f}",
                    observed_value=ratio, units="ratio", expected_interval=[0, max_ratio])
    return _res(cid, scope, D.CheckOutcome.PASS,
                f"loop seam closes like an ordinary step (ratio {ratio:.2f})",
                observed_value=ratio, units="ratio")


def check_protection(cid: str, scope: str, before: bytes, after: bytes, w: int, h: int,
                     allowed_mask: bytearray, protected_mask: bytearray | None) -> D.CheckResult:
    bad_outside, bad_protected = 0, 0
    for p in range(w * h):
        if before[p * 4:(p + 1) * 4] != after[p * 4:(p + 1) * 4]:
            if protected_mask is not None and protected_mask[p]:
                bad_protected += 1
            elif not allowed_mask[p]:
                bad_outside += 1
    if bad_protected or bad_outside:
        return _res(cid, scope, D.CheckOutcome.FAIL,
                    f"protection violated: {bad_outside} changed outside edit support, {bad_protected} in protected regions",
                    observed_value=bad_outside + bad_protected, units="pixels")
    return _res(cid, scope, D.CheckOutcome.PASS, "exterior + protected pixels identical", units="pixels")
