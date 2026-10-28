"""E2E project builder (production services only): two revisions differing at
slot 3, one plain packet, reviewed guides, no human decisions yet."""
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from framebound.v2.checks import fixtures as F
from framebound.v2.services import approvals as A
from framebound.v2.services import assets, clips, contracts, packets
from framebound.v2.services.authz import Actor

REV = Actor(type="reviewer", id="human-1")
ORCH = Actor(type="orchestrator", id="e2e-setup")


def main(out: str) -> dict:
    td = out
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        assets.import_asset(td, str(src / rel), f"f-e2e-{i}", source_kind="procedural")
    assets.import_asset(td, str(src / meta["faults"]["blank"]), "fx-e2e-blank",
                        source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][0]), "a-e2e-id", source_kind="original")
    assets.import_asset(td, str(src / meta["clean"][1]), "a-e2e-st", source_kind="original")
    Image.new("L", (64, 64), 255).save(Path(td) / "src" / "mask-full.png")
    assets.import_asset(td, str(Path(td) / "src" / "mask-full.png"), "m-e2e-full",
                        source_kind="original")
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-e2e-01", "character_revision_id": "char-e2e-01",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "a-e2e-id", "style": "a-e2e-st",
                       "motion_guide_revision": "mg-e2e-01"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"} for i in range(8)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    base = [f"f-e2e-{i}" for i in range(8)]
    clips.create_revision(td, "contract-e2e-01", "rev-base", base, [f"p{i}" for i in range(8)])
    fixed = list(base)
    fixed[3] = "fx-e2e-blank"
    clips.create_revision(td, "contract-e2e-01", "rev-diff", fixed, [f"p{i}" for i in range(8)])
    ev_base = clips.evaluate(td, "rev-base")
    ev_diff = clips.evaluate(td, "rev-diff")
    packets.create_packet(td, "pkt-base", "rev-base", ev_base.artifacts[0]["id"], "e2e baseline")
    packets.create_packet(td, "pkt-diff", "rev-diff", ev_diff.artifacts[0]["id"], "e2e faulty")
    info = {"packet_id": "pkt-base", "rev_base": "rev-base", "rev_diff": "rev-diff",
            "ev_base": ev_base.artifacts[0]["id"], "ev_diff": ev_diff.artifacts[0]["id"],
            "mask_asset": "m-e2e-full"}
    print(json.dumps(info))
    return info


if __name__ == "__main__":
    main(sys.argv[1])
