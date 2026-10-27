"""Production fixture builder for verification/dev (R0).

Builds a minimal disposable desk project using only production services, so
release verification never imports test helpers from an installed package.
All art is procedural-test fixtures; nothing here is human-approved.
"""
from __future__ import annotations

from pathlib import Path

from .checks import fixtures as F
from .services import assets, clips, contracts, packets

CONTRACT = {
    "schema_version": "2.0", "id": "contract-devseed-01", "character_revision_id": "char-01",
    "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
    "canvas": {"width": 64, "height": 64, "units": "native_px"},
    "timing": {"ticks_per_second": 60, "holds": [4] * 8},
    "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-01"},
    "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"} for i in range(8)],
    "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
    "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
}


def build_minimal_project(project_dir: str | Path) -> dict:
    """Create a disposable seeded project; returns ids and fixture paths."""
    td = str(project_dir)
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        assets.import_asset(td, str(src / rel), f"f-clean-{i}", source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][0]), "a-id", source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][1]), "a-st", source_kind="procedural")
    contracts.propose_contract(td, dict(CONTRACT))
    aids = [f"f-clean-{i}" for i in range(8)]
    clips.create_revision(td, "contract-devseed-01", "clip-devseed-bad",
                          aids, [f"p{i}" for i in range(8)])
    ev = clips.evaluate(td, "clip-devseed-bad")
    ev_id = ev.artifacts[0]["id"]
    packets.create_packet(td, "pkt-devseed-01", "clip-devseed-bad", ev_id, "devseed packet")
    return {"ev_id": ev_id, "packet_id": "pkt-devseed-01", "meta": meta, "src": str(src)}
