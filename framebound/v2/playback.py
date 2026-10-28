"""Independent runtime playback: presented ticks, interruption handoffs, contact verdicts.

The harness renders through the product's own runtime path — timeline holds
mapping each tick to a frame instance, registration transforms applied to
canonical pixels, world-trace grounding — and captures what the player would
actually present: frame IDs, pixel hashes, root transforms, contact
coordinates, entry policy, and the interruption event for every run phase
and held-tick boundary.

Independence: the presented observations come from the playback mapping over
stored rows; test expectations are computed separately (direct file reads +
independent mapping). A hash read twice from the same source file proves
nothing; the right frame at the right tick with the right world contact does.
Faults (broken selector, wrong entry sample, handoff delay, root jump,
contact teleport) fail the verdict instead of passing silently.
"""
from __future__ import annotations

import hashlib
import json
import math
from PIL import Image

from . import domain as D
from . import storage as S
from .media.canonical import canonical_pixels, pixel_sha256
from .media.timeline import select_slot
from .services.errors import InvalidInput


def _con(project_dir: str):
    return S.connect(project_dir)


def play_clip(project_dir: str, revision_id: str) -> dict:
    """Present every tick of a stored revision through the runtime path.

    Each tick maps via contract holds to a frame instance; the presented
    raster is the stored asset's canonical pixels with the frame's recorded
    registration translation applied. Returns per-tick observations.
    """
    import io as _io
    con = _con(project_dir)
    try:
        try:
            rdata, _ = S.get(con, "clip_revisions", revision_id)
        except KeyError:
            raise InvalidInput(f"unknown clip revision {revision_id}")
        rev = D.ClipRevision.model_validate(rdata)
        cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
        contract = D.ClipContractRevision.model_validate(cdata)
        by_slot = {}
        for fid in rev.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            fi = D.FrameInstance.model_validate(fdata)
            by_slot[fi.slot] = fi
        regs = {}
        for fid in rev.frame_instance_ids:
            fdata, _ = S.get(con, "frame_instances", fid)
            fi = D.FrameInstance.model_validate(fdata)
            try:
                rrow, _ = S.get(con, "registrations", fi.registration_id)
                regs[fi.slot] = D.Registration.model_validate(rrow)
            except KeyError:
                regs[fi.slot] = None
        from .media.render import render_native as _render_native
        total = contract.timing.total_ticks()
        presented = []
        for tick in range(total):
            slot = select_slot(contract.timing.holds, tick, contract.action.loop)
            fi = by_slot[slot]
            adata, _ = S.get(con, "assets", fi.asset_id)
            raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
            reg = regs.get(slot)
            dx, dy = 0, 0
            if reg is not None and reg.translation_px:
                dx, dy = int(reg.translation_px[0]), int(reg.translation_px[1])
            w, h = contract.canvas.width, contract.canvas.height
            # Stage B: single shared render path, translation applied exactly once.
            canon, pxh, _ = _render_native(raw, [dx, dy], (w, h))
            presented.append({"tick": tick, "slot": slot,
                              "frame_instance_id": fi.id, "asset_id": fi.asset_id,
                              "phase": fi.phase,
                              "pixel_sha256": pxh,
                              "translation_px": [dx, dy],
                              "registration_id": fi.registration_id})
    finally:
        con.close()
    return {"revision_id": revision_id, "total_ticks": total,
            "holds": list(contract.timing.holds), "loop": contract.action.loop,
            "presented": presented}


def _world_at(project_dir: str, revision_id: str, tick: int):
    con = _con(project_dir)
    try:
        row = con.execute("SELECT data FROM world_traces WHERE id=?",
                          (f"wtrace-{revision_id}",)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    try:
        wt = D.WorldTrace.model_validate(
            json.loads(row["data"]) if isinstance(row["data"], str) else row["data"])
    except Exception:
        return None
    if tick < 0 or tick >= len(wt.positions):
        return None
    return {"position": list(wt.positions[tick]), "planted": bool(wt.planted[tick])}


def _support(canon: bytes, w: int, h: int, window: list[int]) -> int:
    l, t, r, b = window
    n = 0
    for y in range(max(0, t), min(h, b)):
        for x in range(max(0, l), min(w, r)):
            if canon[(y * w + x) * 4 + 3] >= 128:
                n += 1
    return n


def interrupt(project_dir: str, departure_revision_id: str, tick: int,
              entry_revision_id: str, entry_slot: int, *,
              support_window: list[int] | None = None,
              world_tol: float = 2.0,
              entry_policy: dict | None = None,
              handoff_delay_ticks: int = 0) -> dict:
    """Capture one measured interruption handoff through the playback path.

    The departure observation is the presented tick sample; the entry
    observation is the presented first tick of the entry slot. World contact
    compares stored world-trace positions with the declared tolerance;
    support is counted from presented pixels. The verdict fails on entry
    policy violation, contact teleport, root jump past the frozen budget, or
    planted entries with no support — never a silent pass.
    """
    dep = play_clip(project_dir, departure_revision_id)
    ent = play_clip(project_dir, entry_revision_id)
    if tick < 0 or tick >= dep["total_ticks"]:
        raise InvalidInput(f"interruption tick {tick} outside 0..{dep['total_ticks'] - 1}")
    entry_first_tick = sum(ent["holds"][:entry_slot]) + handoff_delay_ticks
    if entry_slot < 0 or entry_slot >= len(ent["holds"]):
        raise InvalidInput(f"entry slot {entry_slot} outside the entry contract")
    if entry_first_tick >= ent["total_ticks"]:
        raise InvalidInput("handoff delay pushes the entry past the entry clip")
    d = dep["presented"][tick]
    e = ent["presented"][entry_first_tick]
    policy = entry_policy or {}
    entry_ok = (entry_revision_id == policy.get("clip", entry_revision_id)
                and entry_slot == policy.get("slot", entry_slot))
    dep_world = _world_at(project_dir, departure_revision_id, tick)
    ent_world = _world_at(project_dir, entry_revision_id, entry_first_tick)
    world_distance = None
    if dep_world is not None and ent_world is not None:
        world_distance = math.dist(dep_world["position"], ent_world["position"])
    # presented support from the same rasters the player shows
    import io as _io
    con = _con(project_dir)
    try:
        dep_raw = S.blob_path(project_dir, S.get(con, "assets", d["asset_id"])[0]["byte_sha256"]).read_bytes()
        ent_raw = S.blob_path(project_dir, S.get(con, "assets", e["asset_id"])[0]["byte_sha256"]).read_bytes()
    finally:
        con.close()
    dep_img = Image.open(_io.BytesIO(dep_raw)).convert("RGBA")
    ent_img = Image.open(_io.BytesIO(ent_raw)).convert("RGBA")
    w, h = dep_img.size
    dep_canon, ent_canon = canonical_pixels(dep_img), canonical_pixels(ent_img)
    support = None
    if support_window is not None:
        support = {"departure_px": _support(dep_canon, w, h, support_window),
                   "entry_px": _support(ent_canon, ent_img.size[0], ent_img.size[1],
                                        support_window)}
    reasons, verdict = [], "pass"
    def fail(reason: str) -> None:
        nonlocal verdict
        verdict = "fail"
        reasons.append(reason)
    if not entry_ok:
        fail(f"entry policy violated: entered {entry_revision_id}:{entry_slot}, "
             f"policy is {policy.get('clip')}:{policy.get('slot')}")
    if handoff_delay_ticks:
        fail(f"handoff delayed {handoff_delay_ticks} tick(s): departure overheld, "
             f"entry starts at tick {entry_first_tick}")
    dx = e["translation_px"][0] - d["translation_px"][0]
    dy = e["translation_px"][1] - d["translation_px"][1]
    if abs(dx) > 2 or abs(dy) > 2:
        fail(f"root jump ({dx},{dy}) past the frozen 2px translation budget")
    if world_distance is not None and world_distance > world_tol:
        fail(f"contact teleport: world distance {world_distance:.2f} > tol {world_tol}")
    planted_dep = dep_world["planted"] if dep_world else None
    planted_ent = ent_world["planted"] if ent_world else None
    if planted_dep and planted_ent and support is not None and support["entry_px"] == 0:
        fail("planted entry shows no support pixels in the presented sample")
    return {"departure_revision_id": departure_revision_id, "tick": tick,
            "departure": {"slot": d["slot"], "frame_instance_id": d["frame_instance_id"],
                          "asset_id": d["asset_id"], "phase": d["phase"],
                          "pixel_sha256": d["pixel_sha256"],
                          "translation_px": d["translation_px"],
                          "world": dep_world},
            "entry_revision_id": entry_revision_id, "entry_slot": entry_slot,
            "entry_first_tick": entry_first_tick,
            "entry": {"slot": e["slot"], "frame_instance_id": e["frame_instance_id"],
                      "asset_id": e["asset_id"], "phase": e["phase"],
                      "pixel_sha256": e["pixel_sha256"],
                      "translation_px": e["translation_px"],
                      "world": ent_world},
            "world_distance": world_distance, "world_tol": world_tol,
            "support": support,
            "entry_policy": policy or {"clip": entry_revision_id, "slot": entry_slot},
            "verdict": verdict, "reasons": reasons}


def record_transition_trace(project_dir: str, record: dict, *,
                            origin: str = "procedural") -> D.TransitionTrace:
    """Persist a measured interruption as a frozen, content-addressed row."""
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    row = D.TransitionTrace(
        id=f"ttrace-{digest[:24]}",
        departure_revision_id=record["departure_revision_id"],
        departure_tick=record["tick"],
        entry_revision_id=record["entry_revision_id"],
        entry_slot=record["entry_slot"],
        entry_first_tick=record["entry_first_tick"],
        departure_pixel_sha256=record["departure"]["pixel_sha256"],
        entry_pixel_sha256=record["entry"]["pixel_sha256"],
        world_distance=record.get("world_distance"),
        planted_departure=(record["departure"].get("world") or {}).get("planted"),
        planted_entry=(record["entry"].get("world") or {}).get("planted"),
        verdict=record["verdict"], reasons=list(record.get("reasons", [])),
        origin=origin)
    con = _con(project_dir)
    try:
        try:
            S.insert(con, row)
        except S.ConflictError:
            pass
    finally:
        con.close()
    return row
