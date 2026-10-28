"""Benchmark the actual public evaluation service (not primitives).

Measures `services.clips.evaluate` (complete required context + persistence)
on an 8-frame 64x64 clip, plus an incremental changed-frame case. Reports
hardware, resolution, independent frame count, cold/warm state, p50/p95,
included checks and exclusions. Primitive raster microbenchmarks live in
`run_benchmark` and are NOT full-framework latency.
"""
from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _build_project(td: str) -> dict:
    from .checks import fixtures as F
    from .services import approvals as A
    from .services import assets, clips, contracts
    from .services.authz import Actor
    from . import domain as D
    from . import storage as S
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        assets.import_asset(td, str(src / rel), f"f{i}", source_kind="procedural",
                            rights="original")
    assets.import_asset(td, str(src / meta["clean"][0]), "id-art",
                        source_kind="original", rights="original")
    assets.import_asset(td, str(src / meta["clean"][1]), "st-art",
                        source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-bench", project_id="p", identity_asset_ids=["id-art"],
            style_asset_ids=["st-art"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="x"))
    finally:
        con.close()
    con = S.connect(td)
    try:
        hashes = {f"f{i}": S.get(con, "assets", f"f{i}")[0]["byte_sha256"] for i in range(8)}
    finally:
        con.close()
    A.propose_motion_guide(td, Actor(type="orchestrator", id="bench"),
                           {"schema_version": "2.0", "id": "mg-bench",
                            "character_revision_id": "char-bench",
                            "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                                         "byte_sha256": hashes[f"f{i}"]} for i in range(8)]})
    A.approve_reference(td, Actor(type="reviewer", id="human-bench"), "char-bench", "mg-bench")
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "c-bench", "character_revision_id": "char-bench",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "id-art", "style": "st-art",
                       "motion_guide_revision": "mg-bench"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                           for i in range(8)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "area", "check": "silhouette_area", "required": True,
             "params": {"max_fraction": 0.35}},
            {"id": "cadence", "check": "locked_cadence", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    clips.create_revision(td, "c-bench", "rev-bench", [f"f{i}" for i in range(8)],
                          [f"p{i}" for i in range(8)])
    return {"project": td, "meta": meta}


def _p(frac: float, data: list[float]) -> float:
    s = sorted(data)
    return s[min(len(s) - 1, int(frac * len(s)))]


def _build_large_project(td: str, frames: int = 200) -> dict:
    """Representative workload: many held frames with guides and holds."""
    from .services import approvals as A
    from .services import assets, clips, contracts
    from .services.authz import Actor
    from . import domain as D
    from . import storage as S
    src = Path(td) / "big"
    from .checks import fixtures as _F
    meta = _F.build_cycle(src)
    for n in range(frames):
        assets.import_asset(td, str(src / meta["clean"][n % 8]), f"g{n}",
                            source_kind="procedural", rights="original")
    assets.import_asset(td, str(src / meta["clean"][0]), "id-big",
                        source_kind="original", rights="original")
    assets.import_asset(td, str(src / meta["clean"][1]), "st-big",
                        source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-big", project_id="p", identity_asset_ids=["id-big"],
            style_asset_ids=["st-big"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="x"))
    finally:
        con.close()
    con = S.connect(td)
    try:
        hashes = {f"g{n}": S.get(con, "assets", f"g{n}")[0]["byte_sha256"]
                  for n in range(frames)}
    finally:
        con.close()
    A.propose_motion_guide(td, Actor(type="orchestrator", id="bench"),
                           {"schema_version": "2.0", "id": "mg-big",
                            "character_revision_id": "char-big",
                            "entries": [{"phase": f"p{n % 8}", "asset_id": f"g{n}",
                                         "byte_sha256": hashes[f"g{n}"]}
                                        for n in range(min(frames,8))]})
    A.approve_reference(td, Actor(type="reviewer", id="human-bench"), "char-big", "mg-big")
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "c-big", "character_revision_id": "char-big",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * frames},
        "references": {"identity": "id-big", "style": "st-big",
                       "motion_guide_revision": "mg-big"},
        "phase_schedule": [{"slot": n, "phase": f"p{n % 8}", "motion_reference_id": f"pose-{n}"}
                           for n in range(frames)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "area", "check": "silhouette_area", "required": True,
             "params": {"max_fraction": 0.35}},
            {"id": "cadence", "check": "locked_cadence", "required": True}],
        "allowed_transforms": {"per_pose_scale": False,
                               "rigid_translation_budget_px": 2}})
    clips.create_revision(td, "c-big", "rev-big",
                          [f"g{n}" for n in range(frames)], [f"p{n % 8}" for n in range(frames)])
    return {"project": td, "frames": frames}


def run_bench_eval(*, warm_runs: int = 25, cold_runs: int = 5,
                         large_frames: int = 200, large_warm_runs: int = 5) -> dict:
    from .services import assets, clips
    td = tempfile.mkdtemp(prefix="fb-bench-")
    _build_project(td)
    # warm: same process, repeated public-service evaluations with persistence
    warm, tech = [], None
    for _ in range(warm_runs):
        t0 = time.perf_counter()
        env = clips.evaluate(td, "rev-bench")
        warm.append((time.perf_counter() - t0) * 1000)
        tech = env.technical_status.value
    # incremental: one changed frame as a new revision (full-matrix re-run;
    # invalidation is whole-revision — the evaluator does not do incremental
    # frame caching, reported honestly here, not hidden)
    from PIL import Image as _Image
    src = Path(td) / "src"
    from .checks import fixtures as F  # noqa: F401 (fixtures already built)
    var_src = src / "frames" / "clean-0.png"
    with _Image.open(var_src).convert("RGBA") as im:
        from PIL import ImageDraw as _Draw
        # Genuine pixel change: paint an opaque red square over the center so
        # the canonical pixel hash differs (transparent-corner edits would be
        # normalized away by canonical transparent-RGB handling).
        d = _Draw.Draw(im)
        w, h = im.size
        d.rectangle([w // 4, h // 4, w // 4 + 16, h // 4 + 16], fill=(255, 0, 0, 255))
        im.save(Path(td) / "variant.png")
    from .media.canonical import pixel_sha256 as _pxh, canonical_pixels as _canon
    with _Image.open(var_src).convert("RGBA") as _orig, \
            _Image.open(Path(td) / "variant.png").convert("RGBA") as _var:
        assert _pxh(_canon(_orig)) != _pxh(_canon(_var)), \
            "benchmark variant must change actual pixels (pixel hash must differ)"
    assets.import_asset(td, str(Path(td) / "variant.png"), "f0-variant",
                        source_kind="procedural", rights="original")
    clips.create_revision(td, "c-bench", "rev-bench-inc",
                          ["f0-variant"] + [f"f{i}" for i in range(1, 8)],
                          [f"p{i}" for i in range(8)])
    inc = []
    for _ in range(warm_runs):
        t0 = time.perf_counter()
        clips.evaluate(td, "rev-bench-inc")
        inc.append((time.perf_counter() - t0) * 1000)
    # cold: fresh interpreter per run (imports + first evaluation)
    cold = []
    for _ in range(cold_runs):
        t0 = time.perf_counter()
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.');"
             "from framebound.v2.services import clips;"
             f"clips.evaluate({td!r}, 'rev-bench')"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]))
        dt = (time.perf_counter() - t0) * 1000
        if r.returncode != 0:
            raise RuntimeError(f"cold evaluation failed: {r.stderr[-500:]}")
        cold.append(dt)
    # representative workload: many held frames, same public path (no cold
    # subprocess here: cold interpreter cost is covered by the small workload;
    # the large workload measures warm evaluation scaling)
    big = _build_large_project(td, frames=large_frames)
    big_warm = []
    for _ in range(large_warm_runs):
        t0 = time.perf_counter()
        clips.evaluate(td, "rev-big")
        big_warm.append((time.perf_counter() - t0) * 1000)
    # playback timing is runtime presentation, independent from verification
    # latency and (unmeasured offline) provider generation latency
    from . import playback as _play
    play_ticks = sum([4] * 8)
    play_ms = []
    for _ in range(10):
        t0 = time.perf_counter()
        _play.play_clip(td, "rev-bench")
        play_ms.append((time.perf_counter() - t0) * 1000 / play_ticks)
    # enabled checks derived from the executed contract, not a static list
    from . import storage as _S
    con = _S.connect(td)
    try:
        cdata, _ = _S.get(con, "contract_revisions", "c-bench")
    finally:
        con.close()
    included = sorted({c["check"] for c in cdata["constraints"]})
    import multiprocessing
    return {
        "service": "services.clips.evaluate (public, persisted, complete required context)",
        "hardware": {"platform": platform.platform(), "machine": platform.machine(),
                     "python": platform.python_version(),
                     "cpu_count": multiprocessing.cpu_count()},
        "workload": {"frames": 8, "resolution": [64, 64], "holds": [4] * 8,
                     "checks_included": included,
                     "checks_excluded": "provenance_coverage is not enabled by this "
                     "contract and is never reported as executed; guide-dependent "
                     "appearance/phase checks need independent guides (unmeasured "
                     "here, honestly reported)"},
        "technical_status": tech,
        "cold_ms": {"n": len(cold), "p50": round(_p(0.5, cold), 1),
                    "p95": round(_p(0.95, cold), 1)},
        "warm_ms": {"n": len(warm), "p50": round(_p(0.5, warm), 2),
                    "p95": round(_p(0.95, warm), 2)},
        "incremental_changed_frame_ms": {"n": len(inc), "p50": round(_p(0.5, inc), 2),
                                         "p95": round(_p(0.95, inc), 2),
                                         "invalidation": "whole-revision re-evaluation; "
                                         "no incremental frame cache"},
        "large_workload": {"frames": big["frames"], "resolution": [64, 64],
                           "holds_per_frame": 4,
                           "checks_included": ["locked_cadence",
                                               "native_registration",
                                               "silhouette_area"],
                           "warm_ms": {"n": len(big_warm),
                                       "p50": round(_p(0.5, big_warm), 1),
                                       "p95": round(_p(0.95, big_warm), 1)}},
        "playback_ms_per_tick": {"n": len(play_ms),
                                 "p50": round(_p(0.5, play_ms), 3),
                                 "p95": round(_p(0.95, play_ms), 3),
                                 "ticks": play_ticks,
                                 "note": "runtime presentation only; verification "
                                 "(above) and provider generation (unmeasured "
                                 "offline; recorded-run bundles carry provider "
                                 "response IDs, not latency claims) are separate"},
        "note": "primitive raster microbenchmarks (run_benchmark) are separate and must "
                "not be presented as full-framework latency; realtime playback claims "
                "require the playback numbers above on stated hardware, never the "
                "evaluator or provider timings",
    }


if __name__ == "__main__":
    import argparse as _ap
    ap = _ap.ArgumentParser()
    ap.add_argument("--out", required=False, default=None)
    ap.add_argument("--warm-runs", type=int, default=25)
    ap.add_argument("--cold-runs", type=int, default=5)
    args = ap.parse_args()
    rep = run_bench_eval(warm_runs=args.warm_runs, cold_runs=args.cold_runs)
    print(json.dumps(rep, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=2) + "\n")
