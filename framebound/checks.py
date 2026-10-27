"""Consistency checks for a 2D animation clip.

A clip is checked against a frozen contract: one approved master, one
native canvas, locked cadence, phase references, declared contacts and
anchors, and declared visible features. Measurements are registered
raster observations, never inferred skeletons. Anything that cannot be
measured is reported as unmeasured; a declared measurement that cannot
be taken fails closed.

Issue codes are stable and machine-readable so an orchestrating model
can act on them without parsing prose.
"""
import math
from .pngcodec import read_png

DEFAULTS = {
    "max_area_fraction": 0.18,       # silhouette area vs reference-cycle median
    "max_width_fraction": 0.15,      # silhouette width vs reference-cycle median
    "max_height_fraction": 0.12,     # silhouette height vs reference-cycle median
    "max_palette_drift": 0.22,       # quantised colour histogram distance vs master
    "max_expected_excess": 0.045,    # phase descriptor: expected minus best distance
    "min_wrong_phase_ratio": 1.5,    # phase descriptor: expected / best distance
    "max_centroid_step": 14.0,       # art px between adjacent frames (root drift)
    "max_anchor_distance": 8.0,      # art px, declared reviewed anchors
    "max_feature_span_delta": 3.0,   # art px vs master feature span
    "max_adjacent_span_delta": 2.5,  # art px between adjacent measured frames
    "min_alpha": 128,
}


def _alpha(data, w, x, y):
    return data[(y * w + x) * 4 + 3]


def silhouette(data, w, h, min_alpha):
    xs, ys, area = [], [], 0
    for y in range(h):
        for x in range(w):
            if _alpha(data, w, x, y) >= min_alpha:
                xs.append(x); ys.append(y); area += 1
    if not area:
        return {"area": 0, "bbox": None, "centroid": None}
    return {"area": area,
            "bbox": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
            "width": max(xs) - min(xs) + 1, "height": max(ys) - min(ys) + 1,
            "centroid": [sum(xs) / area, sum(ys) / area]}


def descriptor(data, w, h, region, grid):
    left, top, right, bottom = region
    cols, rows = grid
    out = []
    for r in range(rows):
        y0, y1 = top + (bottom - top) * r // rows, top + (bottom - top) * (r + 1) // rows
        for c in range(cols):
            x0, x1 = left + (right - left) * c // cols, left + (right - left) * (c + 1) // cols
            total = sum(_alpha(data, w, x, y) for y in range(y0, y1) for x in range(x0, x1))
            out.append(total / (255 * max(1, (x1 - x0) * (y1 - y0))))
    return out


def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) / max(1, len(a))


def palette_hist(data, w, h, min_alpha):
    hist = {}
    n = 0
    for i in range(0, len(data), 4):
        if data[i + 3] >= min_alpha:
            key = (data[i] >> 5, data[i + 1] >> 5, data[i + 2] >> 5)
            hist[key] = hist.get(key, 0) + 1
            n += 1
    return {k: v / n for k, v in hist.items()} if n else {}


def palette_drift(a, b):
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)


def contact_span(data, w, region, rows, min_alpha):
    left, top, right, bottom = region
    best = 0
    for y in range(max(top, rows[0]), min(bottom, rows[1])):
        run = 0
        for x in range(left, right):
            run = run + 1 if _alpha(data, w, x, y) >= min_alpha else 0
            best = max(best, run)
    return best


def find_feature(data, w, h, spec, rule, min_alpha):
    """Largest colour-rule component in a search window. Ambiguous = fail."""
    left, top, right, bottom = spec["region"]
    selected = set()
    for y in range(top, bottom):
        for x in range(left, right):
            i = (y * w + x) * 4
            r, g, b, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            if a >= min_alpha and all([
                    r >= rule.get("r_min", 0), g >= rule.get("g_min", 0), b >= rule.get("b_min", 0),
                    r <= rule.get("r_max", 255), g <= rule.get("g_max", 255), b <= rule.get("b_max", 255)]):
                selected.add((x, y))
    parts = []
    while selected:
        seed = min(selected, key=lambda p: (p[1], p[0])); selected.remove(seed)
        part, queue = [seed], [seed]
        while queue:
            x, y = queue.pop()
            for q in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if q in selected:
                    selected.remove(q); part.append(q); queue.append(q)
        if len(part) >= spec.get("min_pixels", 4):
            parts.append(part)
    parts.sort(key=lambda p: (-len(p), min(p)))
    if not parts:
        return {"status": "missing"}
    if len(parts) > 1 and len(parts[1]) >= len(parts[0]) * 0.65:
        return {"status": "ambiguous"}
    xs = [q[0] for q in parts[0]]; ys = [q[1] for q in parts[0]]
    return {"status": "measured",
            "point": [(min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2],
            "pixels": len(parts[0])}


def _median(values):
    s = sorted(values)
    return s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2


def check_clip(contract, frames, references=None, master=None, anchors=None):
    """frames/references/master: lists of (w, h, rgba). Returns (issues, metrics).

    references defaults to frames (self-consistency mode: phase order is
    then only checked for stalls/drift, not against a frozen cycle).
    """
    tol = {**DEFAULTS, **contract.get("tolerances", {})}
    w, h = contract["canvas"]
    min_alpha = tol["min_alpha"]
    issues, metrics = [], {"frames": []}

    def add(code, detail, slot=None, severity="error"):
        issues.append({"code": code, "detail": detail, "slot": slot, "severity": severity})

    n = len(frames)
    holds = contract.get("holds", [])
    if contract.get("locked_holds") is not None and holds != contract["locked_holds"]:
        add("locked_cadence", "Frame holds differ from the locked cadence")
    if len(holds) != n or any(type(x) is not int or x <= 0 for x in holds):
        add("playback_structure", "Holds must be positive integers, one per frame")
    for i, (fw, fh, _) in enumerate(frames):
        if (fw, fh) != (w, h):
            add("candidate_registration", f"Frame {i} is {fw}x{fh}, contract canvas is {w}x{h}; per-pose fitting is not allowed", i)
    if any(i["severity"] == "error" for i in issues):
        return issues, metrics

    sils = [silhouette(d, w, h, min_alpha) for _, _, d in frames]
    for i, s in enumerate(sils):
        if s["area"] == 0:
            add("empty_frame", f"Frame {i} has no visible pixels", i)
    # Same-pose comparison: with frozen references each frame is compared
    # to its own phase, never to a different pose. Without references the
    # cycle median is the fallback (weaker; unlike poses vary legitimately).
    ref_sils = [silhouette(d, w, h, min_alpha) for _, _, d in (references or frames)]
    per_slot = references is not None and len(references) == n
    med = {k: _median([s[k] for s in ref_sils if s["area"]]) for k in ("area", "width", "height")}
    for i, s in enumerate(sils):
        if not s["area"]:
            continue
        base_s = ref_sils[i] if per_slot else med
        base_label = f"reference phase {i}" if per_slot else "cycle median"
        if abs(s["area"] / base_s["area"] - 1) > tol["max_area_fraction"]:
            add("silhouette_area_drift", f"Frame {i} visible area {s['area']} vs {base_label} {base_s['area']:.0f}", i)
        if abs(s["width"] / base_s["width"] - 1) > tol["max_width_fraction"]:
            add("silhouette_width_drift", f"Frame {i} visible width {s['width']} vs {base_label} {base_s['width']:.0f}", i)
        if abs(s["height"] / base_s["height"] - 1) > tol["max_height_fraction"]:
            add("silhouette_height_drift", f"Frame {i} visible height {s['height']} vs {base_label} {base_s['height']:.0f}", i)
        metrics["frames"].append({"slot": i, **{k: s[k] for k in ("area", "width", "height")},
                                  "bbox": s["bbox"], "centroid": s["centroid"]})

    # Movement: centroid steps, adjacent pose change, loop seam.
    cents = [s["centroid"] for s in sils]
    steps = []
    rng = range(n) if contract.get("loop", True) else range(n - 1)
    for i in rng:
        j = (i + 1) % n
        if cents[i] and cents[j]:
            step = math.dist(cents[i], cents[j])
            steps.append({"from": i, "to": j, "centroid_step": round(step, 2)})
            if step > tol["max_centroid_step"]:
                add("root_drift_step", f"Centroid moves {step:.1f} art px between frames {i} and {j}", j, "warning")
    metrics["centroid_steps"] = steps

    # Phase correspondence against frozen references (registered descriptor).
    if references and contract.get("region") and contract.get("grid"):
        region, grid = contract["region"], contract["grid"]
        ctrl = [descriptor(d, w, h, region, grid) for _, _, d in references]
        curr = [descriptor(d, w, h, region, grid) for _, _, d in frames]
        corr = []
        for i, cur in enumerate(curr):
            if i >= len(ctrl):
                break
            scores = [_dist(cur, c) for c in ctrl]
            best = min(range(len(scores)), key=scores.__getitem__)
            corr.append({"slot": i, "best_reference_slot": best,
                         "expected_distance": round(scores[i], 5), "best_distance": round(scores[best], 5)})
            if scores[i] - scores[best] > tol["max_expected_excess"] and scores[i] > scores[best] * tol["min_wrong_phase_ratio"]:
                add("phase_correspondence", f"Frame {i} matches reference phase {best} substantially better than its own phase {i}", i)
            nxt = (i + 1) % n
            if contract.get("loop", True) or i < n - 1:
                d_cur, d_ctrl = _dist(curr[i], curr[nxt]), _dist(ctrl[i], ctrl[nxt % len(ctrl)])
                if d_cur < 0.002 and d_ctrl > 0.025:
                    add("stalled_phase", f"Frames {i} and {nxt} collapse to the same registered pose", i)
        metrics["phase_correspondence"] = corr

    # Appearance: palette drift vs the same-phase reference when frozen
    # references exist (pose proportions then cancel out), else vs master.
    base = master if master else (references[0] if references else frames[0])
    base_hist = palette_hist(base[2], w, h, min_alpha)
    for i, (_, _, d) in enumerate(frames):
        ref_hist = palette_hist(references[i][2], w, h, min_alpha) if per_slot else base_hist
        drift = palette_drift(ref_hist, palette_hist(d, w, h, min_alpha))
        metrics["frames"][i]["palette_drift"] = round(drift, 4)
        if drift > tol["max_palette_drift"]:
            add("appearance_palette_drift", f"Frame {i} palette drift {drift:.3f} exceeds {tol['max_palette_drift']}", i)

    # Declared contacts: visible support span in a frozen window.
    for c in contract.get("contacts", []):
        span = contact_span(frames[c["slot"]][2], w, c["region"], c["rows"], min_alpha)
        metrics.setdefault("contacts", []).append({**c, "observed_span": span})
        if span < c["min_span"]:
            add("missing_support_contact", f"{c.get('kind', 'contact')}: span {span} < {c['min_span']} art px", c["slot"])

    # Declared reviewed anchors (never inferred joints).
    for a in contract.get("anchors", []):
        point = (anchors or {}).get(a["slot"])
        if point is None:
            add("unmeasured_anchor", f"{a['name']} has no reviewed anchor; reported unmeasured, not passed", a["slot"], "warning")
            continue
        d = math.dist(point, a["point"])
        if d > a.get("max_distance", tol["max_anchor_distance"]):
            add("anchor_drift", f"{a['name']} is {d:.1f} art px from its reviewed position", a["slot"])

    # Declared visible-feature span (e.g. clasp-to-buckle): size pulse detector.
    feat = contract.get("feature_span")
    if feat and master:
        rule = feat["rule"]
        def span(img):
            pts = {}
            for name, spec in feat["features"].items():
                pts[name] = find_feature(img[2], w, h, spec, rule, min_alpha)
            if any(v["status"] != "measured" for v in pts.values()):
                return None, pts
            a, b = feat["between"]
            return math.dist(pts[a]["point"], pts[b]["point"]), pts
        target, _ = span(master)
        if target is None:
            add("surface_reference_unmeasured", "Master feature span cannot be measured; contract is invalid")
        else:
            spans = []
            for i, img in enumerate(frames):
                if str(i) not in feat.get("frames", [str(x) for x in range(n)]):
                    spans.append(None); continue
                value, _pts = span(img)
                if value is None:
                    add("surface_feature_unmeasured", f"Frame {i}: declared visible feature missing or ambiguous", i)
                    spans.append(None); continue
                spans.append(value)
                metrics["frames"][i]["feature_span"] = round(value, 2)
                if abs(value - target) > tol["max_feature_span_delta"]:
                    add("surface_span_drift", f"Frame {i} feature span {value:.1f} vs master {target:.1f} art px", i)
            seq = [(i, s) for i, s in enumerate(spans) if s is not None]
            for (i, a), (j, b) in zip(seq, seq[1:]):
                if abs(a - b) > tol["max_adjacent_span_delta"]:
                    add("surface_span_pulse", f"Feature span changes {abs(a-b):.1f} art px between frames {i} and {j}", j)
    return issues, metrics


def load_images(paths):
    return [read_png(p) for p in paths]

