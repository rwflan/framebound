"""Original P0 demo character: Pip the courier (hooded, satchel LEFT hip, trailing scarf).

Original design authored in-repo for the Framebound P0 demo. Lineage: hand-set keyframe
parameter tables below (independent poses, not a sine loop); rendered with Pillow.
Asymmetric by design (satchel + scarf favor the left) → exact mirrors are prohibited as
new drawings and must be authored facings instead. Badges: [replay/procedural-original].
Live provider generation is attempted and recorded; without credentials the ledger shows
not_configured and nothing is fabricated.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

W = H = 96
GROUND = 80
SKIN = (238, 200, 160, 255)
CLOAK = (38, 92, 86, 255)      # teal hood/cloak
CLOAK_DK = (24, 62, 58, 255)
SATCHEL = (150, 100, 52, 255)  # leather, LEFT hip
BRASS = (255, 200, 40, 255)    # compass + buckle (visible feature pair)
SCARF = (196, 60, 60, 255)
BOOTS = (70, 48, 32, 255)

COMPASS_WINDOW = [30, 30, 52, 48]
BUCKLE_WINDOW = [26, 52, 50, 68]
SUPPORT_WINDOW = [16, 70, 80, 90]
REGION = [12, 12, 84, 88]
GRID = [6, 6]

# Hand-authored keyframes: (hip_y, torso_lean, lead_swing, trail_lift, arm_swing, scarf_lift, cloak_flare)
RUN = [
    ("A_contact",     (0.0, 0.05, 10, 0, -6, 2, 1)),
    ("A_compression", (2.5, 0.10, 7, 1, -4, 1, 0)),
    ("A_passing",     (1.0, 0.06, 0, 5, 0, 3, 2)),
    ("A_flight",      (-1.5, 0.02, -6, 7, 4, 5, 3)),
    ("B_contact",     (0.0, 0.05, -10, 0, 6, 2, 1)),
    ("B_compression", (2.5, 0.10, -7, 1, 4, 1, 0)),
    ("B_passing",     (1.0, 0.06, 0, 5, 0, 3, 2)),
    ("B_flight",      (-1.5, 0.02, 6, 7, -4, 5, 3)),
]
JUMP = [
    ("crouch",  (6.0, 0.22, 4, 0, 3, 0, 0)),
    ("launch",  (2.0, 0.10, 8, 2, -5, 3, 2)),
    ("rise",    (-4.0, 0.00, 6, 6, -3, 5, 3)),
    ("apex",    (-7.0, -0.04, 2, 8, 0, 6, 4)),
    ("fall",    (-3.0, 0.04, -3, 5, 2, 5, 3)),
    ("land",    (5.0, 0.20, 5, 0, 4, 1, 1)),
]
ATTACK = [
    ("ready",    (1.0, 0.08, 3, 0, -8, 1, 0)),
    ("windup",   (2.0, 0.14, 2, 1, -12, 2, 1)),
    ("swing",    (0.0, 0.02, 6, 3, 10, 5, 3)),
    ("contact",  (0.5, 0.00, 8, 2, 12, 4, 2)),
    ("follow",   (1.5, 0.06, 5, 1, 6, 3, 2)),
    ("recover",  (2.0, 0.10, 3, 0, -4, 1, 0)),
]
IDLE = [
    ("idle_0", (0.0, 0.03, 1, 0, 1, 1, 0)),
    ("idle_1", (0.8, 0.03, 1, 0, 1, 2, 0)),
    ("idle_2", (0.0, 0.03, 1, 0, 1, 1, 0)),
    ("idle_3", (-0.8, 0.03, 1, 0, 1, 0, 0)),
]
TRANSITIONS = {
    "idle-run-01": [("leave_idle", (0.5, 0.06, 4, 0, -2, 1, 1)), ("enter_run", (0.0, 0.05, 10, 0, -6, 2, 1))],
    "run-idle-01": [("leave_run", (0.5, 0.06, 4, 1, -2, 2, 1)), ("enter_idle", (0.0, 0.03, 1, 0, 1, 1, 0))],
    "run-attack-01": [("leave_run", (0.0, 0.05, 8, 1, -4, 2, 1)), ("enter_attack", (1.0, 0.08, 3, 0, -8, 1, 0))],
}


def render(pose: tuple, facing: str = "right") -> Image.Image:
    (bob, lean, lead, lift, arm, scarf, flare) = pose
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = 48.0
    hip = (cx + lean * 20, 58 + bob)
    neck = (cx + lean * 34, 58 + bob - 20)
    # legs: lead planted/striding, trail lifted
    for far, (sw, lf) in ((False, (lead, lift)), (True, (-lead * 0.6, 0))):
        knee = (hip[0] + sw * 0.6, hip[1] + 11)
        foot = (hip[0] + sw, GROUND - lf)
        col = (30, 40, 52, 255) if far else (36, 46, 60, 255)
        d.line([hip, knee], fill=col, width=2 if far else 3)
        d.line([knee, foot], fill=col, width=1 if far else 2)
        d.line([(foot[0], foot[1]), (foot[0] + 6, foot[1])], fill=BOOTS, width=2)
    # cloak torso + hood
    d.line([hip, neck], fill=CLOAK, width=7 + flare)
    d.line([hip, neck], fill=CLOAK_DK, width=2)
    head = (neck[0] + 1, neck[1] - 7)
    d.ellipse([head[0] - 6, head[1] - 6, head[0] + 6, head[1] + 6], fill=CLOAK_DK)
    d.ellipse([head[0] - 4, head[1] - 4, head[0] + 4, head[1] + 4], fill=SKIN)
    # satchel on LEFT hip (asymmetry) + brass buckle
    d.rectangle([hip[0] - 12, hip[1] - 6, hip[0] - 4, hip[1] + 2], fill=SATCHEL)
    d.rectangle([hip[0] - 10, hip[1] - 3, hip[0] - 6, hip[1] + 1], fill=BRASS)
    # arms: courier's tagging arm swings wide
    hand = (hip[0] + arm, neck[1] + 10)
    elbow = (hip[0] + arm * 0.5, neck[1] + 5)
    d.line([neck, elbow], fill=CLOAK, width=3)
    d.line([elbow, hand], fill=SKIN, width=2)
    # scarf trailing left
    sx = neck[0] - 4
    d.line([(sx, neck[1]), (sx - 8 - scarf, neck[1] - 2 - scarf * 0.4)], fill=SCARF, width=3)
    d.line([(sx - 8 - scarf, neck[1] - 2 - scarf * 0.4), (sx - 12 - scarf, neck[1] + 2)], fill=SCARF, width=2)
    # compass at chest (visible feature): drawn last so arm/scarf strokes cannot
    # fragment the declared feature into ambiguous blobs (R2 fixture repair;
    # the span measurement itself is unchanged and still rejects ambiguity)
    d.ellipse([neck[0] - 2, neck[1] + 2, neck[0] + 2, neck[1] + 6], fill=BRASS)
    if facing == "left":
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return img


def build_character(out_dir: str | Path) -> dict:
    """Author the full P0 clip set. Returns manifest with independent-pose counts."""
    out = Path(out_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    clips = {"run": RUN, "jump": JUMP, "attack": ATTACK, "idle": IDLE}
    manifest = {"character": "pip-courier", "facing": "right", "clips": {}, "transitions": {}}
    hashes = set()
    for clip, poses in clips.items():
        rels = []
        for i, (phase, params) in enumerate(poses):
            img = render(params)
            rel = f"frames/{clip}-{i:02d}.png"
            img.save(out / rel)
            rels.append(rel)
            hashes.add(img.tobytes())
        manifest["clips"][clip] = {"phases": [p for p, _ in poses], "frames": rels}
    for tid, poses in TRANSITIONS.items():
        rels = []
        for i, (phase, params) in enumerate(poses):
            img = render(params)
            rel = f"frames/{tid}-{i}.png"
            img.save(out / rel)
            rels.append(rel)
        manifest["transitions"][tid] = rels
    # reference sheet: identity + style (approved masters for the demo)
    ident = render(RUN[0][1])
    ident.save(out / "identity.png")
    style = render(ATTACK[2][1])
    style.save(out / "style.png")
    manifest["independent_drawings"] = len(hashes)
    manifest["presented_samples"] = sum(len(v["frames"]) for v in manifest["clips"].values())
    return manifest
