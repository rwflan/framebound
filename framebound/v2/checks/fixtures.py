"""Independent procedural fixtures for WP2 (Pillow-based, provenance: synthetic-test).

NOT accepted art, NOT training positives: deliberately bad outputs stay labeled faults.
A tiny side-view runner at 64x64 with parametric limbs, gold clasp/buckle markers,
and boots that occupy a declared support window.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

W = H = 64
GROUND = 56
SKIN = (232, 184, 148, 255)
SHIRT = (32, 140, 140, 255)
PANTS = (44, 48, 64, 255)
BOOTS = (110, 72, 40, 255)
HAIR = (52, 36, 28, 255)
GOLD = (255, 200, 40, 255)
FAULT_SHIRT = (150, 40, 170, 255)

CLASP_WINDOW = [20, 18, 44, 34]
BUCKLE_WINDOW = [20, 34, 44, 48]
SUPPORT_WINDOW = [8, 50, 56, 62]
REGION = [8, 8, 56, 60]
GRID = [6, 6]


def render(phase: float, torso_scale: float = 1.0, shirt=SHIRT, support_lift: float = 0.0,
           slide_x: float = 0.0, draw_gold: bool = True, clip_toe: bool = False) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bob = math.sin(2 * phase) * 1.5  # weight bounce at 2x stride: separates mirrored half-cycles
    hip = (32.0 + slide_x, 40.0 + bob)
    neck = (32.0 + slide_x, 40.0 + bob - 16 * torso_scale)
    d.line([hip, neck], fill=shirt, width=4)
    head = (neck[0], neck[1] - 7)
    d.ellipse([head[0] - 5, head[1] - 5, head[0] + 5, head[1] + 5], fill=HAIR)
    d.ellipse([head[0] - 4, head[1] - 3, head[0] + 4, head[1] + 5], fill=SKIN)
    # legs: two-phase swing; planted foot takes support_lift only when swinging
    for far, off in ((False, 0.0), (True, math.pi)):
        swing = math.sin(phase + off)
        lift = max(0.0, math.sin(phase + off)) * 6
        knee = (hip[0] + swing * 7, hip[1] + 9)
        foot = (hip[0] + swing * 11, GROUND - lift - (support_lift if lift == 0 else 0.0))
        col = (34, 38, 52, 255) if far else PANTS
        d.line([hip, knee], fill=col, width=2 if far else 3)
        d.line([knee, foot], fill=col, width=1 if far else 2)
        toe_end = foot[0] + 5
        if clip_toe:
            toe_end = 60  # clipped: toe runs past declared ownership (test erases instead)
        d.line([(foot[0], foot[1]), (toe_end, foot[1])], fill=BOOTS, width=2)
    # arms pump opposite the same-side leg with a phase offset: every slot gets a distinct pose
    for far, off in ((False, math.pi * 0.5), (True, math.pi * 1.5)):
        swing = math.sin(phase + off)
        hand = (hip[0] + swing * 6, neck[1] + 8 + bob * 0.5)
        elbow = (hip[0] + swing * 3, neck[1] + 4)
        d.line([neck, elbow], fill=SHIRT if not far else HAIR, width=2)
        d.line([elbow, hand], fill=SKIN, width=2)
    if draw_gold:
        d.ellipse([neck[0] - 2, neck[1] - 1, neck[0] + 2, neck[1] + 3], fill=GOLD)  # clasp
        d.rectangle([hip[0] - 2 + slide_x * 0, hip[1] - 4, hip[0] + 2 + slide_x * 0, hip[1]], fill=GOLD)  # buckle
    if clip_toe:
        d.rectangle([50, 48, 64, 62], fill=(0, 0, 0, 0))  # erase toe: clipping fault
    return img


def build_cycle(out_dir: str | Path) -> dict:
    out = Path(out_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    clean, faulty = [], []
    for i in range(8):
        img = render(phase=i * math.pi / 4)
        p = out / f"frames/clean-{i}.png"
        img.save(p)
        pass
    faults = {}
    # 0: torso pulse (height nearly constant, span changes)
    p = out / "frames/fault-pulse.png"
    render(phase=2 * math.pi / 4, torso_scale=1.35).save(p)
    faults["pulse"] = "frames/fault-pulse.png"
    # 1: wrong phase (copy of phase 5 into slot 3)
    p = out / "frames/fault-phase.png"
    render(phase=5 * math.pi / 4).save(p)
    faults["phase"] = "frames/fault-phase.png"
    # 2: blank
    p = out / "frames/fault-blank.png"
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(p)
    faults["blank"] = "frames/fault-blank.png"
    # 3: resized canvas (registration fault)
    p = out / "frames/fault-resized.png"
    render(phase=0).resize((72, 72), Image.NEAREST).save(p)
    faults["resized"] = "frames/fault-resized.png"
    # 4: clipped toe
    p = out / "frames/fault-clipped.png"
    render(phase=0, clip_toe=True).save(p)
    faults["clipped"] = "frames/fault-clipped.png"
    # 5: palette fault
    p = out / "frames/fault-palette.png"
    render(phase=math.pi / 4, shirt=FAULT_SHIRT).save(p)
    faults["palette"] = "frames/fault-palette.png"
    # 6: missing feature
    p = out / "frames/fault-nogold.png"
    render(phase=0, draw_gold=False).save(p)
    faults["nogold"] = "frames/fault-nogold.png"
    return {"clean": [f"frames/clean-{i}.png" for i in range(8)], "faults": faults,
            "canvas": [W, H], "region": REGION, "grid": GRID,
            "support_window": SUPPORT_WINDOW, "clasp_window": CLASP_WINDOW, "buckle_window": BUCKLE_WINDOW}
