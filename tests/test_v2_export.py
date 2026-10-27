"""WP5 gate: moved snapshot loads with standard loaders; labels/preferences/hashes/durations/exclusions."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from framebound.v2.checks import fixtures as F
from framebound.v2.services import assets, clips, contracts, packets
from framebound.v2.services.authz import Actor
from framebound.v2.exports import build_snapshot, validate_snapshot

REV = Actor(type="reviewer", id="human-1")

def _contract(span0: float, contact_min: int) -> dict:
    return {
        "schema_version": "2.0", "id": "c-export-01", "character_revision_id": "ch",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"} for i in range(8)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "torso_span", "check": "visible_span", "required": True,
             "params": {"color_a": [255, 200, 40], "color_b": [255, 200, 40],
                        "window_a": [20, 18, 44, 34], "window_b": [20, 34, 44, 48],
                        "expected": span0, "max_delta": 3.0}},
            {"id": "support", "check": "declared_contacts", "required": True,
             "params": {"window": [8, 50, 56, 62], "min_visible": contact_min}}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
    }


class ExportSnapshot(unittest.TestCase):
    def _project(self, td: str) -> dict:
        import math
        from PIL import Image
        from framebound.v2.checks.raster import centroid, feature_points
        from framebound.v2.media.canonical import canonical_pixels
        src = Path(td) / "src"
        meta = F.build_cycle(src)
        px0 = canonical_pixels(Image.open(src / meta["clean"][0]).convert("RGBA"))
        ca = centroid(feature_points(px0, 64, 64, (255, 200, 40), [20, 18, 44, 34]))
        cb = centroid(feature_points(px0, 64, 64, (255, 200, 40), [20, 34, 44, 48]))
        n = sum(1 for y in range(50, 62) for x in range(8, 56) if px0[(y * 64 + x) * 4 + 3] >= 128)
        for i, rel in enumerate(meta["clean"]):
            assets.import_asset(td, str(src / rel), f"f{i}", source_kind="procedural")
        assets.import_asset(td, str(src / meta["clean"][0]), "a-id", source_kind="procedural")
        assets.import_asset(td, str(src / meta["clean"][1]), "a-st", source_kind="procedural")
        assets.import_asset(td, str(src / meta["faults"]["pulse"]), "f-wrong", source_kind="procedural")
        contracts.propose_contract(td, _contract(math.dist(ca, cb), max(1, n // 2)))
        aids = [f"f{i}" for i in range(8)]
        clips.create_revision(td, "c-export-01", "clip-clean", aids, [f"p{i}" for i in range(8)])
        bad = list(aids)
        bad[3] = "f-wrong"
        clips.create_revision(td, "c-export-01", "clip-bad", bad, [f"p{i}" for i in range(8)])
        ev_bad = clips.evaluate(td, "clip-bad")
        self.assertEqual(ev_bad.technical_status.value, "fail")
        # fix slot 3 as a child revision, evaluate, approve the EXACT fix
        clips.register_candidate(td, "clip-bad", "clip-fix", {3: "f3"},
                                 recipe="repair:restore-phase-guide")
        ev_fix = clips.evaluate(td, "clip-fix")
        self.assertEqual(ev_fix.technical_status.value, "pass")
        packets.record_review_event(td, REV, {"id": "ap-fix", "action": "approve",
                                             "clip_revision_id": "clip-fix", "note": "fix accepted"})
        return {"meta": meta}

    def test_snapshot_round_trip_after_move(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "demo-snap", ["clip-clean", "clip-bad", "clip-fix"], str(out),
                                 {"split": {"train": ["clip-clean", "clip-fix"], "test": ["clip-bad"]},
                                  "split_policy": "exclude",
                                  # mechanics demo only: fixtures stay labeled procedural-test throughout
                                  "include_procedural_positives": True})
            # leakage: clip-bad shares source drawings with train → test frames excluded with reason
            self.assertTrue(any(e.get("context") == "split" for e in man["exclusions"]), man["exclusions"])
            # preference pair: approved fix chosen, failed frame rejected, named reason
            prefs = [json.loads(l) for l in (out / "preferences.jsonl").read_text().splitlines() if l.strip()]
            self.assertTrue(prefs, "expected at least one eligible preference pair")
            for pr in prefs:
                self.assertIn("chosen_revision", pr)
                self.assertEqual(pr["chosen_revision"], "clip-fix")
                self.assertTrue(pr["rejected_issue"] and pr["reason"])
            # move the snapshot to a new directory: everything must still load
            moved = Path(td) / "moved"
            shutil.move(str(out), str(moved))
            rep = validate_snapshot(str(moved))
            self.assertTrue(rep["ok"], rep["issues"])
            self.assertEqual(rep["loaders"]["preferences"], len(prefs))
            self.assertGreater(rep["loaders"]["coco_images"], 0)
            self.assertGreater(rep["loaders"]["imagefolder_rows"], 0)
            # durations match contract holds
            temps = [json.loads(l) for l in (moved / "temporal.jsonl").read_text().splitlines()]
            for t in temps:
                self.assertEqual(t["duration_ticks"], sum(t["holds"]))
                self.assertEqual(sum(t["holds"]), 32)

    def test_strict_split_fails_on_leakage(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            with self.assertRaises(ValueError):
                build_snapshot(td, "s", ["clip-clean", "clip-bad"], str(Path(td) / "o"),
                               {"split": {"train": ["clip-clean"], "test": ["clip-bad"]},
                                "split_policy": "strict"})

    def test_rights_and_procedural_exclusions_visible(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            man = build_snapshot(td, "s2", ["clip-clean", "clip-bad", "clip-fix"], str(Path(td) / "o2"), {})
            kinds = {e["context"] for e in man["exclusions"]}
            self.assertIn("positive", kinds, man["exclusions"])
            # metadata labels every row with an origin; nothing is silently a positive
            metas = [json.loads(l) for l in (Path(td) / "o2" / "hf" / "metadata.jsonl").read_text().splitlines()]
            self.assertTrue(metas and all("label_origin" in m for m in metas))


if __name__ == "__main__":
    unittest.main()
