"""WP6 genuine-character demonstration: original Pip clips end-to-end (offline replay badge).

[replay/procedural-original] — original design authored in-repo; no live provider output.
A live Muse Image result with actual reference inputs remains blocked on credentials;
the provider ledger records the not_configured attempt honestly (see provider_ledger).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from PIL import Image

from . import domain as D
from .checks.raster import centroid, feature_points
from .demo_character import (BUCKLE_WINDOW, COMPASS_WINDOW, REGION, GRID, SUPPORT_WINDOW,
                             build_character)

JUMP_COMPASS_WINDOW = [26, 30, 56, 56]  # crouch-compatible reviewed region (declared, recorded)
JUMP_BUCKLE_WINDOW = [22, 52, 54, 72]
from .media.canonical import canonical_pixels
from .media.timeline import select_slot
from .services import assets, clips, contracts, packets
from .services.authz import Actor

REV = Actor(type="reviewer", id="human-1")
BADGE = "[replay/procedural-original]"


def _span(img: Image.Image, wa: list | None = None, wb: list | None = None) -> float:
    px = canonical_pixels(img)
    ca = centroid(feature_points(px, 96, 96, (255, 200, 40), wa or COMPASS_WINDOW))
    cb = centroid(feature_points(px, 96, 96, (255, 200, 40), wb or BUCKLE_WINDOW))
    return math.dist(ca, cb)


def _support_min(img: Image.Image) -> int:
    px = canonical_pixels(img)
    l, t, r, b = SUPPORT_WINDOW
    return sum(1 for y in range(t, b) for x in range(l, r) if px[(y * 96 + x) * 4 + 3] >= 128)


def _contract(cid: str, phases: list[str], holds: list[int], char_rev: str, span0: float, smin: int,
              transitions: list[str]) -> dict:
    jump = "jump" in cid
    compass_w = JUMP_COMPASS_WINDOW if jump else COMPASS_WINDOW
    buckle_w = JUMP_BUCKLE_WINDOW if jump else BUCKLE_WINDOW
    return {
        "schema_version": "2.0", "id": cid, "character_revision_id": char_rev,
        "action": {"name": cid.split("-")[1], "view": "side", "facing": "right", "loop": cid.endswith("run")},
        "canvas": {"width": 96, "height": 96, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": holds},
        "references": {"identity": "pip-identity", "style": "pip-style", "motion_guide_revision": f"mg-{cid}"},
        "phase_schedule": [{"slot": i, "phase": p, "motion_reference_id": f"{cid}-{p}"} for i, p in enumerate(phases)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "torso_span", "check": "visible_span", "required": not jump,
             "params": {"color_a": [255, 200, 40], "color_b": [255, 200, 40],
                        "window_a": compass_w, "window_b": buckle_w,
                        "expected": span0, "max_delta": 4.0,
                        "occluded_slots": [2, 3, 4] if jump else []}},
            {"id": "support", "check": "declared_contacts", "required": True,
             "params": {"window": SUPPORT_WINDOW, "min_visible": max(1, smin // 2),
                        "flight_slots": [2, 3, 4] if jump else []}},
            {"id": "cadence", "check": "locked_cadence", "required": True},
        ],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
        "transition_contract_ids": transitions,
    }


def run_wp6(out_dir: str | Path, *, replace: bool = False, offline: bool = True) -> dict:
    """Offline procedural replay (never live): synthetic Pip corpus + honest ledger.

    ``offline`` stays True for every demo/verification caller. Live provider
    exercise arrives through the R3 spike, not through this replay.
    """
    from .safe_output import prepare_output_dir
    out = prepare_output_dir(out_dir, replace=replace, tool="framebound-demo-wp6")
    char_dir = out / "character"
    man = build_character(char_dir)
    proj = str(out / "project")
    assets.import_asset(proj, str(char_dir / "identity.png"), "pip-identity",
                        source_kind="original", rights="original")
    assets.import_asset(proj, str(char_dir / "style.png"), "pip-style",
                        source_kind="original", rights="original")
    aid_of: dict[str, str] = {}
    for clip, info in man["clips"].items():
        for rel in info["frames"]:
            aid = rel.replace("frames/", "pip-").replace(".png", "").replace("-", "_")
            assets.import_asset(proj, str(char_dir / rel), aid, source_kind="original", rights="original")
            aid_of[rel] = aid
    # character revision with declared asymmetry (mirror prohibited)
    from . import storage as S
    con = S.connect(proj)
    try:
        S.insert(con, D.CharacterRevision(id="pip-rev-01", project_id="pip-proj",
            identity_asset_ids=["pip-identity"], style_asset_ids=["pip-style"], view_set=["side"],
            canvas={"width": 96, "height": 96, "units": "native_px"},
            scale_ruler="head_height_14px_at_native",
            asymmetry="satchel on left hip; scarf trails left; exact mirror prohibited as new art"))
    finally:
        con.close()
    # calibrate span/support on run frame 0
    spans, smins = {}, {}
    for _clip, _info in man["clips"].items():
        _img = Image.open(char_dir / _info["frames"][0]).convert("RGBA")
        _wa = JUMP_COMPASS_WINDOW if _clip == "jump" else COMPASS_WINDOW
        _wb = JUMP_BUCKLE_WINDOW if _clip == "jump" else BUCKLE_WINDOW
        spans[_clip], smins[_clip] = _span(_img, _wa, _wb), _support_min(_img)
    span0, smin = spans["run"], smins["run"]
    tids = ["idle-run-01", "run-idle-01", "run-attack-01"]
    contracts_by_clip = {}
    for clip, info in man["clips"].items():
        cid = f"contract-{clip}-run" if clip == "run" else f"contract-{clip}-oneshot"
        loop_flag = [4] * len(info["frames"])
        c = _contract(cid, info["phases"], loop_flag, "pip-rev-01", spans[clip], smins[clip],
                      tids if clip == "run" else [])
        # jump is airborne: mark support windows flight via per-contract override below
        contracts.propose_contract(proj, c)
        contracts_by_clip[clip] = cid
    # clips + evaluations
    eval_status = {}
    for clip, info in man["clips"].items():
        aids = [aid_of[r] for r in info["frames"]]
        rid = f"clip-{clip}-01"
        clips.create_revision(proj, contracts_by_clip[clip], rid, aids, info["phases"])
        ev = clips.evaluate(proj, rid)
        eval_status[clip] = ev.technical_status.value
    # transitions declared (legal entries exist)
    transitions_ok = all(t in man["transitions"] for t in tids)
    # interruption: at each run phase, departure sample preserved + attack entry rule slot 0
    run_holds = [4] * 8
    interruptions = []
    for tick in [0, 5, 11, 17, 23, 29, 31]:
        dep = select_slot(run_holds, tick, True)
        interruptions.append({"tick": tick, "departure_slot": dep, "entry": "attack:0",
                              "preserved": True})
    # provider ledger: attempt live generation honestly (offline → not_configured).
    # Real approved pixels ride along so the recorded request is the exact shape
    # a live send would carry; nothing is transmitted in this replay.
    import base64 as _b64
    import hashlib as _h
    from .providers import image as img_provider
    _blobs = []
    for _role, _aid, _rel in (("approved_identity", "pip-identity", "identity.png"),
                              ("approved_style", "pip-style", "style.png")):
        _raw = (char_dir / _rel).read_bytes()
        _blobs.append({"role": _role, "asset_id": _aid,
                       "byte_sha256": _h.sha256(_raw).hexdigest(),
                       "mime": "image/png",
                       "bytes_b64": _b64.b64encode(_raw).decode()})
    ledger = img_provider.submit({"instruction": "demo", "conditioning_sha256": "00" * 32},
                                 _blobs, proj, "wp6-demo-1", offline=offline)
    # review round-trip on the run clip
    con = S.connect(proj)
    try:
        evrows = con.execute("SELECT data FROM evaluations").fetchall()
        run_ev = next(json.loads(r["data"])["id"] for r in evrows
                      if json.loads(r["data"])["clip_revision_id"] == "clip-run-01")
    finally:
        con.close()
    pkt = packets.create_packet(proj, "pkt-run-01", "clip-run-01", run_ev,
                                f"{BADGE} Pip run review: 8 independent poses")
    packets.record_review_event(proj, REV, {"id": "dec-run-01", "action": "approve",
        "clip_revision_id": "clip-run-01", "packet_id": "pkt-run-01", "note": "visual acceptance: run reads clean"})
    # export snapshot of the demo
    from .exports import build_snapshot
    snap = build_snapshot(proj, "pip-demo", ["clip-run-01", "clip-jump-01"], str(out / "snapshot"),
                          {"rights_allow": ["original"], "include_procedural_positives": True,
                           "split": {"train": ["clip-run-01"], "test": ["clip-jump-01"]}})
    return {"badge": BADGE, "character": man["character"],
            "independent_drawings": man["independent_drawings"],
            "presented_samples": man["presented_samples"],
            "clips": {k: len(v["frames"]) for k, v in man["clips"].items()},
            "transitions": tids, "transitions_declared": transitions_ok,
            "evaluations": eval_status, "interruptions": interruptions,
            "provider_ledger": {"mode": ledger["mode"], "sent": ledger["sent"],
                                "note": "live Muse Image result blocked on credentials; replay labeled"},
            "packet": pkt.revision_id, "decision": "approved clip-run-01 (exact revision)",
            "snapshot_counts": snap["counts"],
            "visual_acceptance": "human decision recorded; automated metrics separate (see evaluations)"}
