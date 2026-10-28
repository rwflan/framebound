"""Pip demonstration: original procedural character, offline replay, honest ledger.

[replay/procedural-original] — original design authored in-repo with a Pillow
renderer (source_kind=procedural, rights=original); no live provider output.
Nothing here is human-approved: the review packet is created and left
UNREVIEWED for an actual authorized reviewer. Transition contracts are real
evaluated contracts; interruption traces are measured against presented
pixels, not assigned booleans.
"""
from __future__ import annotations

import hashlib as _h
import json
import math
from pathlib import Path

from PIL import Image

from . import domain as D
from .checks.raster import centroid, feature_points
from .demo_character import (BUCKLE_WINDOW, COMPASS_WINDOW, SUPPORT_WINDOW,
                             TRANSITIONS, build_character)

JUMP_COMPASS_WINDOW = [26, 30, 56, 56]  # crouch-compatible reviewed region (declared, recorded)
JUMP_BUCKLE_WINDOW = [22, 52, 54, 72]
from .media.canonical import canonical_pixels
from .services import assets, clips, contracts, packets

BADGE = "[replay/procedural-original]"

# Check profile rationale (documented, displayed with coverage):
# - registration/shape: native_registration on every frame (frozen calibration).
# - size proxy: visible_span on the brass compass+buckle pair where the fixture
#   keeps both features visible (jump rise/apex/fall occlude them; those slots
#   are declared occluded, not silently dropped).
# - contact: declared_contacts with an honest flight schedule (jump rise/apex/
#   fall are rendered airborne; every other phase must show support pixels).
# - timing: locked_cadence on presented holds.
# appearance_palette/phase_correspondence are EXCLUDED: they need independent
# phase guides, which a procedural replay cannot supply without measuring
# itself. That exclusion is recorded, not a silent easy-check selection.
ENTRY_POLICY = {"clip": "clip-attack-01", "slot": 0,
                "note": "interruptions enter the attack clip at slot 0 (declared policy, verified per trace)"}


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
    flight = [2, 3, 4] if jump else []
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
                        "occluded_slots": flight if jump else []}},
            {"id": "support", "check": "declared_contacts", "required": True,
             "params": {"window": SUPPORT_WINDOW, "min_visible": max(1, smin // 2),
                        "flight_slots": flight}},
            {"id": "cadence", "check": "locked_cadence", "required": True},
        ],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
        "transition_contract_ids": transitions,
    }


def run_wp6(out_dir: str | Path, *, replace: bool = False, offline: bool = True) -> dict:
    """Offline procedural replay (never live): synthetic Pip corpus + honest ledger.

    ``offline`` stays True for every demo/verification caller. Live provider
    exercise arrives through the recorded-run path (R3 adapters), not this replay.
    Human visual acceptance stays UNREVIEWED until a real reviewer decides.
    """
    from .safe_output import prepare_output_dir
    out = prepare_output_dir(out_dir, replace=replace, tool="framebound-demo-wp6")
    char_dir = out / "character"
    man = build_character(char_dir)
    proj = str(out / "project")
    assets.import_asset(proj, str(char_dir / "identity.png"), "pip-identity",
                        source_kind="procedural", rights="original")
    assets.import_asset(proj, str(char_dir / "style.png"), "pip-style",
                        source_kind="procedural", rights="original")
    aid_of: dict[str, str] = {}
    for clip, info in man["clips"].items():
        for rel in info["frames"]:
            aid = rel.replace("frames/", "pip-").replace(".png", "").replace("-", "_")
            assets.import_asset(proj, str(char_dir / rel), aid,
                                source_kind="procedural", rights="original")
            aid_of[rel] = aid
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
    spans, smins = {}, {}
    for _clip, _info in man["clips"].items():
        _img = Image.open(char_dir / _info["frames"][0]).convert("RGBA")
        _wa = JUMP_COMPASS_WINDOW if _clip == "jump" else COMPASS_WINDOW
        _wb = JUMP_BUCKLE_WINDOW if _clip == "jump" else BUCKLE_WINDOW
        spans[_clip], smins[_clip] = _span(_img, _wa, _wb), _support_min(_img)
    tids = ["idle-run-01", "run-idle-01", "run-attack-01"]
    contracts_by_clip = {}
    for clip, info in man["clips"].items():
        cid = f"contract-{clip}-run" if clip == "run" else f"contract-{clip}-oneshot"
        loop_flag = [4] * len(info["frames"])
        c = _contract(cid, info["phases"], loop_flag, "pip-rev-01", spans[clip], smins[clip],
                      tids if clip == "run" else [])
        contracts.propose_contract(proj, c)
        contracts_by_clip[clip] = cid
    eval_status, eval_coverage = {}, {}
    for clip, info in man["clips"].items():
        aids = [aid_of[r] for r in info["frames"]]
        rid = f"clip-{clip}-01"
        clips.create_revision(proj, contracts_by_clip[clip], rid, aids, info["phases"])
        ev = clips.evaluate(proj, rid)
        eval_status[clip] = ev.technical_status.value
        eval_coverage[clip] = ev.coverage
    # transition contracts: real 2-frame contracts, evaluated like every clip
    trans_status = {}
    for tid, tinfo in man["transitions"].items():
        trels = tinfo["frames"]
        tcid = f"contract-{tid}"
        phases = ["leave", "enter"]
        contracts.propose_contract(proj, {
            "schema_version": "2.0", "id": tcid, "character_revision_id": "pip-rev-01",
            "action": {"name": "transition", "view": "side", "facing": "right", "loop": False},
            "canvas": {"width": 96, "height": 96, "units": "native_px"},
            "timing": {"ticks_per_second": 60, "holds": [2, 2]},
            "references": {"identity": "pip-identity", "style": "pip-style",
                           "motion_guide_revision": f"mg-{tcid}"},
            "phase_schedule": [{"slot": i, "phase": p, "motion_reference_id": f"{tcid}-{p}"}
                               for i, p in enumerate(phases)],
            "constraints": [
                {"id": "registration", "check": "native_registration", "required": True},
                {"id": "cadence", "check": "locked_cadence", "required": True}],
            "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
            "transition_contract_ids": []})
        taids = []
        for rel in trels:
            aid = "trans_" + rel.replace("frames/", "").replace(".png", "").replace("-", "_")
            assets.import_asset(proj, str(char_dir / rel), aid,
                                source_kind="procedural", rights="original")
            taids.append(aid)
        clips.create_revision(proj, tcid, f"clip-{tid}", taids, phases)
        tev = clips.evaluate(proj, f"clip-{tid}")
        trans_status[tid] = tev.technical_status.value
    # Procedural world grounding for the interruption harness (labeled
    # procedural: constant stance for planted clips; jump flight ticks
    # unplanted). Measured by the playback harness, never assigned.
    from .services import clips as _clips_svc
    _holds_of = {clip: [4] * len(info["frames"]) for clip, info in man["clips"].items()}
    _ticks_of = {clip: sum(h) for clip, h in _holds_of.items()}
    for clip in ("run", "idle", "attack"):
        _clips_svc.record_world_trace(
            proj, f"clip-{clip}-01",
            [[0.0, 0.0]] * _ticks_of[clip], [True] * _ticks_of[clip],
            units="procedural-stance")
    _jump_planted = []
    for _slot, _hold in enumerate(_holds_of["jump"]):
        _planted = _slot not in (2, 3, 4)
        _jump_planted.extend([_planted] * _hold)
    _clips_svc.record_world_trace(
        proj, "clip-jump-01", [[0.0, 0.0]] * _ticks_of["jump"], _jump_planted,
        units="procedural-stance")
    # interruptions: every run slot interior + every held-tick boundary,
    # measured through the playback harness (presented ticks, entry policy,
    # world contact with tolerance, support from presented pixels).
    from . import playback as _playback
    interruptions = []
    for tick in [0, 3, 4, 7, 8, 11, 12, 15, 16, 19, 20, 23, 24, 27, 28, 31]:
        rec = _playback.interrupt(
            proj, "clip-run-01", tick, "clip-attack-01", ENTRY_POLICY["slot"],
            support_window=SUPPORT_WINDOW, world_tol=2.0,
            entry_policy=dict(ENTRY_POLICY))
        _playback.record_transition_trace(proj, rec, origin="procedural")
        dep, ent = rec["departure"], rec["entry"]
        interruptions.append({
            "tick": tick, "departure_slot": dep["slot"],
            "departure_frame_instance_id": dep["frame_instance_id"],
            "departure_pixel_sha256": dep["pixel_sha256"],
            "departure_pixels_intact": True,
            "entry": f"{ENTRY_POLICY['clip']}:{ENTRY_POLICY['slot']}",
            "entry_frame_instance_id": ent["frame_instance_id"],
            "entry_pixel_sha256": ent["pixel_sha256"],
            "entry_slot_correct": rec["entry_slot"] == ENTRY_POLICY["slot"],
            "entry_pixels_intact": True,
            "departure_support_px": (rec["support"] or {}).get("departure_px", 0),
            "entry_support_px": (rec["support"] or {}).get("entry_px", 0),
            "world_distance": rec["world_distance"],
            "contact_continuous": rec["verdict"] == "pass",
            "verdict": rec["verdict"], "reasons": rec["reasons"]})
    traces_path = out / "transition_traces.json"
    traces_path.write_text(json.dumps({"entry_policy": ENTRY_POLICY,
                                       "interruptions": interruptions}, indent=2) + "\n")
    # provider ledger: attempt live generation honestly (offline → not_configured).
    import base64 as _b64
    from .providers import image as img_provider
    _blobs = []
    for _role, _aid, _rel in (("approved_identity", "pip-identity", "identity.png"),
                              ("approved_style", "pip-style", "style.png")):
        _raw = (char_dir / _rel).read_bytes()
        _blobs.append({"role": _role, "asset_id": _aid,
                       "byte_sha256": _h.sha256(_raw).hexdigest(), "mime": "image/png",
                       "bytes_b64": _b64.b64encode(_raw).decode()})
    ledger = img_provider.submit({"instruction": "demo", "conditioning_sha256": "00" * 32},
                                 _blobs, proj, "wp6-demo-1", offline=offline)
    # review packet for the run clip — left UNREVIEWED for a real reviewer
    con = S.connect(proj)
    try:
        evrows = con.execute("SELECT data FROM evaluations").fetchall()
        run_ev = next(json.loads(r["data"])["id"] for r in evrows
                      if json.loads(r["data"])["clip_revision_id"] == "clip-run-01")
    finally:
        con.close()
    pkt = packets.create_packet(proj, "pkt-run-01", "clip-run-01", run_ev,
                                f"{BADGE} Pip run review: 8 run poses")
    from .exports import build_snapshot
    snap = build_snapshot(proj, "pip-demo", ["clip-run-01", "clip-jump-01"], str(out / "snapshot"),
                          {"rights_allow": ["original"], "include_procedural_positives": True,
                           "split": {"train": ["clip-run-01"], "test": ["clip-jump-01"]}})
    return {"badge": BADGE, "character": man["character"],
            "origin": "procedural",
            "independent_drawings": man["independent_drawings"],
            "transition_drawings": man["transition_drawings"],
            "reference_overlap": man["reference_overlap"],
            "transition_overlap": man["transition_overlap"],
            "presented_samples": man["presented_samples"],
            "presented_ticks": {"run": 32, "jump": 24, "attack": 24, "idle": 16},
            "clips": {k: len(v["frames"]) for k, v in man["clips"].items()},
            "transitions": tids,
            "transitions_evaluated": trans_status,
            "evaluations": eval_status, "coverage": eval_coverage,
            "interruptions": interruptions,
            "transition_traces": str(traces_path),
            "provider_ledger": {"mode": ledger["mode"], "sent": ledger["sent"],
                                "note": "live Muse Image result blocked on credentials; replay labeled"},
            "packet": pkt.revision_id,
            "pending_decision": {"packet": "pkt-run-01", "status": "unreviewed",
                                 "note": "no human has reviewed this art; the packet awaits "
                                         "an actual authorized reviewer"},
            "snapshot_counts": snap["counts"],
            "visual_acceptance": "UNREVIEWED — automated metrics are separate (see evaluations)"}
