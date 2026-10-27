"""Procedural demo project: a clean 8-frame run cycle plus a faulty set.

No generated art is shipped. A deterministic parametric runner proves the
pipeline end to end: clean passes, four injected faults each fail with a
named code, and a bounded repair returns the clip to a technical pass.
Run:  framebound demo --out build/demo
"""
import json
import math
import time
from pathlib import Path
from .pngcodec import write_png, sha256_file

W = H = 96
GROUND = 84
SKIN = (232, 184, 148, 255)
SHIRT = (32, 140, 140, 255)
PANTS = (44, 48, 64, 255)
BOOTS = (110, 72, 40, 255)
HAIR = (52, 36, 28, 255)
GOLD = (255, 200, 40, 255)
FAULT_SHIRT = (150, 40, 170, 255)


def _blank():
    return bytearray(W * H * 4)


def _px(img, x, y, colour):
    if 0 <= x < W and 0 <= y < H:
        i = (int(y) * W + int(x)) * 4
        img[i:i + 4] = bytes(colour)


def _line(img, a, b, r, colour):
    x0, y0 = a; x1, y1 = b
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) * 2))
    for s in range(steps + 1):
        t = s / steps
        cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    _px(img, round(cx + dx), round(cy + dy), colour)


def _circle(img, c, r, colour):
    for y in range(int(c[1] - r), int(c[1] + r + 1)):
        for x in range(int(c[0] - r), int(c[0] + r + 1)):
            if (x - c[0]) ** 2 + (y - c[1]) ** 2 <= r * r:
                _px(img, x, y, colour)


def _leg(img, hip, phase, support_lift=0.0, far=False):
    """Two-segment leg. The planted leg (no swing lift) takes support_lift.
    The far leg is thinner and darker, as in hand-drawn cycles; this also
    keeps the two legs distinguishable to the phase descriptor."""
    swing = math.sin(phase)
    lift_amt = max(0.0, math.sin(phase)) * 7
    knee = (hip[0] + swing * 9, hip[1] + 13)
    foot = (hip[0] + swing * 15, GROUND - lift_amt - (support_lift if lift_amt == 0 else 0.0))
    colour = (34, 38, 52, 255) if far else PANTS
    _line(img, hip, knee, 2 if far else 3, colour)
    _line(img, knee, foot, 1 if far else 2, colour)
    _line(img, foot, (foot[0] + 6, foot[1]), 2, BOOTS)  # toe forward
    return foot


def render(phase=None, torso_scale=1.0, shirt=SHIRT, support_lift=0.0, standing=False):
    img = _blank()
    if standing:
        hip = (48.0, 50.0)
        neck = (48.0, 50.0 - 22 * torso_scale)
        _line(img, hip, neck, 5, shirt)
        _circle(img, (48, 50 - 22 * torso_scale - 7), 6, SKIN)
        _circle(img, (48, 50 - 22 * torso_scale - 9), 6, HAIR)
        _line(img, hip, (42, GROUND), 3, PANTS); _line(img, hip, (54, GROUND), 3, PANTS)
        _line(img, (42, GROUND), (48, GROUND), 2, BOOTS); _line(img, (54, GROUND), (60, GROUND), 2, BOOTS)
        _line(img, neck, (40, 38), 2, SKIN); _line(img, neck, (56, 38), 2, SKIN)
    else:
        p = phase or 0.0
        bob = math.sin(2 * p) * 1.5
        hip = (48.0, 50.0 + bob)
        lean = 5.0
        neck = (hip[0] + lean, hip[1] - 22 * torso_scale)
        _leg(img, hip, p, support_lift=support_lift)
        _leg(img, hip, p + math.pi, support_lift=support_lift, far=True)
        _line(img, hip, neck, 5, shirt)
        _line(img, neck, (neck[0] + math.sin(p + math.pi) * 8, neck[1] + 11), 2, SKIN)
        _line(img, neck, (neck[0] + math.sin(p) * 8, neck[1] + 11), 2, SKIN)
        head = (neck[0] + 2, neck[1] - 7)
        _circle(img, head, 6, SKIN)
        _circle(img, (head[0] - 1, head[1] - 2), 6, HAIR)
    # Declared visible features: clasp (upper torso) and buckle (waist).
    if standing:
        clasp, buckle = (48, 34), (48, 46)
    else:
        p = phase or 0.0
        hip = (48.0, 50.0 + math.sin(2 * p) * 1.5)
        neck = (hip[0] + 5.0, hip[1] - 22 * torso_scale)
        clasp = (hip[0] + (neck[0] - hip[0]) * 0.75, hip[1] + (neck[1] - hip[1]) * 0.75)
        buckle = (hip[0] + (neck[0] - hip[0]) * 0.25, hip[1] + (neck[1] - hip[1]) * 0.25)
    _circle(img, clasp, 2, GOLD)
    _circle(img, buckle, 2, GOLD)
    return bytes(img)


FAULTS = [
    {"slot": 2, "code": "surface_span_drift", "kwargs": {"torso_scale": 1.4}},
    {"slot": 5, "code": "phase_correspondence", "kwargs": {"phase_override": 1}},
    {"slot": 6, "code": "missing_support_contact", "kwargs": {"support_lift": 12.0}},
    {"slot": 7, "code": "appearance_palette_drift", "kwargs": {"shirt": FAULT_SHIRT}},
]


def build_demo(out_dir, *, replace: bool = False):
    from framebound.v2.safe_output import prepare_output_dir
    out = prepare_output_dir(out_dir, replace=replace, tool="framebound-demo-v1")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    phases = [i * math.pi / 4 for i in range(8)]

    def save(name, img):
        write_png(out / name, W, H, img)
        return name

    save("master.png", render(standing=True))
    save("identity.png", render(standing=True))
    clean, faulty = [], []
    for i, p in enumerate(phases):
        clean.append(save(f"frames/clean-{i}.png", render(phase=p)))
    fault_by_slot = {f["slot"]: f for f in FAULTS}
    for i, p in enumerate(phases):
        fault = fault_by_slot.get(i)
        if not fault:
            faulty.append(clean[i]); continue
        kw = dict(fault["kwargs"])
        phase = phases[kw.pop("phase_override")] if "phase_override" in kw else p
        faulty.append(save(f"frames/faulty-{i}.png", render(phase=phase, **kw)))
    contract = {
        "schema": 1, "character": "demo-runner", "clip": "run", "canvas": [W, H],
        "loop": True, "holds": [3, 3, 2, 4, 4, 3, 5, 4], "locked_holds": [3, 3, 2, 4, 4, 3, 5, 4],
        "frames": faulty,
        "references": [{"file": f, "sha256": sha256_file(out / f)} for f in clean],
        "master": {"file": "master.png", "sha256": sha256_file(out / "master.png")},
        "identity_reference": {"file": "identity.png", "sha256": sha256_file(out / "identity.png")},
        "region": [24, 48, 76, 88], "grid": [12, 10],
        "contacts": [{"slot": 6, "kind": "planted support foot", "region": [26, 76, 50, 88], "rows": [82, 86], "min_span": 8}],
        "feature_span": {
            "between": ["clasp", "buckle"],
            "rule": {"r_min": 200, "g_min": 150, "b_max": 110},
            "features": {
                "clasp": {"region": [30, 18, 66, 40], "min_pixels": 4},
                "buckle": {"region": [30, 40, 66, 62], "min_pixels": 4},
            },
            "frames": [str(i) for i in range(8)],
        },
        "repair_regions": [{"slot": i, "region": [10, 2, 86, 94]} for i in range(8)],
        "protected_regions": [],
        "forbidden_path_fragments": ["/rejected/"],
        "tolerances": {"max_palette_drift": 0.12, "max_feature_span_delta": 3.0,
                       "max_expected_excess": 0.005},
    }
    (out / "contract.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return out, clean, faulty
