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
        # Labeled test reviewer approval goes through the real authority service.
        # Declaring an unstored guide is insufficient for trainable positives.
        from framebound.v2 import storage as S
        from framebound.v2.services import projects,characters,approvals
        projects.create_project(td,{'id':'p','name':'Export test fixture'})
        characters.propose_character(td,{'id':'ch','project_id':'p',
            'identity_asset_ids':['a-id'],'style_asset_ids':['a-st'],'view_set':['side'],
            'canvas':{'width':64,'height':64},'scale_ruler':'test-native'})
        con=S.connect(td)
        try:entries=[{'phase':f'p{i}','asset_id':f'f{i}',
                      'byte_sha256':S.get(con,'assets',f'f{i}')[0]['byte_sha256']} for i in range(8)]
        finally:con.close()
        approvals.propose_motion_guide(td,Actor(type='orchestrator',id='test-fixture'),
            {'id':'mg','character_revision_id':'ch','entries':entries})
        approvals.approve_reference(td,REV,'ch','mg')
        contracts.propose_contract(td, _contract(math.dist(ca, cb), max(1, n // 2)))
        aids = [f"f{i}" for i in range(8)]
        clips.create_revision(td, "c-export-01", "clip-clean", aids, [f"p{i}" for i in range(8)])
        bad = list(aids)
        bad[3] = "f-wrong"
        clips.create_revision(td, "c-export-01", "clip-bad", bad, [f"p{i}" for i in range(8)])
        ev_bad = clips.evaluate(td, "clip-bad")
        self.assertEqual(ev_bad.technical_status.value, "fail")
        # fix slot 3 as a child revision, evaluate, approve the EXACT fix through
        # a comparison packet (explicit pairwise comparison, not descendant approval)
        clips.register_candidate(td, "clip-bad", "clip-fix", {3: "f3"},
                                 recipe="repair:restore-phase-guide")
        ev_fix = clips.evaluate(td, "clip-fix")
        self.assertEqual(ev_fix.technical_status.value, "pass")
        packets.create_packet(td, "pkt-fix", "clip-fix", ev_fix.artifacts[0]["id"],
                              "correction review", comparison_revision_id="clip-bad")
        packets.record_review_event(td, REV, {"id": "ap-fix", "action": "approve",
                                             "clip_revision_id": "clip-fix",
                                             "packet_id": "pkt-fix",
                                             "expected_evaluation_id": ev_fix.artifacts[0]["id"],
                                             "note": "fix accepted over clip-bad"})
        return {"meta": meta}

    def test_snapshot_round_trip_after_move(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            out = Path(td) / "snap"
            # no straddle: the whole selected lineage stays in train, so the
            # explicit pair survives as a positive preference
            man = build_snapshot(td, "demo-snap", ["clip-clean", "clip-bad", "clip-fix"], str(out),
                                 {"split": {"train": ["clip-clean", "clip-fix", "clip-bad"]},
                                  "split_policy": "exclude",
                                  # mechanics demo only: fixtures stay labeled procedural-test throughout
                                  "include_procedural_positives": True})
            self.assertFalse(any(e.get("context", "") == "split-exclude"
                                 for e in man["exclusions"]), man["exclusions"])
            # preference pair: explicit human comparison only, named reason
            prefs = [json.loads(l) for l in (out / "preferences.jsonl").read_text().splitlines() if l.strip()]
            self.assertTrue(prefs, "expected at least one eligible preference pair")
            for pr in prefs:
                self.assertIn("chosen_revision", pr)
                self.assertEqual(pr["chosen_revision"], "clip-fix")
                self.assertEqual(pr["origin"], "human-comparison")
                self.assertTrue(pr["comparison_packet"] and pr["rejected_issue"] and pr["reason"])
                self.assertTrue(pr["chosen"] and pr["rejected"])
            weak = [json.loads(l) for l in (out / "weak_preferences.jsonl").read_text().splitlines() if l.strip()]
            self.assertTrue(all(w["origin"] == "technical-ranking" for w in weak))
            # move the snapshot to a new directory: everything must still load
            moved = Path(td) / "moved"
            shutil.move(str(out), str(moved))
            rep = validate_snapshot(str(moved))
            self.assertTrue(rep["ok"], rep["issues"])
            self.assertEqual(rep["loaders"]["preferences"], len(prefs))
            self.assertGreater(rep["loaders"]["coco_images"], 0)
            # every positive materialized through the standard loader path
            self.assertEqual(rep["loaders"]["rows"], man["counts"]["positives"])
            self.assertGreater(rep["loaders"]["rows"], 0)
            self.assertGreater(rep["loaders"]["annotations_checked"], 0)
            # durations match contract holds
            temps = [json.loads(l) for l in (moved / "temporal.jsonl").read_text().splitlines()]
            for t in temps:
                self.assertEqual(t["total_ticks"], sum(t["holds"]))
                self.assertEqual(sum(t["holds"]), 32)
                self.assertIn("missing", t["traces"])
                self.assertEqual(len(t["frames"]), len(t["holds"]))

    def test_strict_split_fails_on_leakage(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            with self.assertRaises(ValueError):
                build_snapshot(td, "s", ["clip-clean", "clip-bad"], str(Path(td) / "o"),
                               {"split": {"train": ["clip-clean"], "test": ["clip-bad"]},
                                "split_policy": "strict"})

    def test_exclude_removes_straddling_positives_and_pairs(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            out = Path(td) / "snap-ex"
            man = build_snapshot(td, "demo-ex", ["clip-clean", "clip-bad", "clip-fix"], str(out),
                                 {"split": {"train": ["clip-clean", "clip-fix"], "test": ["clip-bad"]},
                                  "split_policy": "exclude",
                                  "include_procedural_positives": True})
            # one character family across train+test: leaked positives are
            # removed (not retained with a logged exclusion) and the affected
            # pair is withheld with its own exclusion record
            self.assertTrue(any(e.get("context", "") == "split-exclude"
                                for e in man["exclusions"]), man["exclusions"])
            prefs = [json.loads(l) for l in (out / "preferences.jsonl").read_text().splitlines()
                     if l.strip()]
            self.assertEqual(prefs, [])
            hf = [json.loads(l) for l in (out / "hf" / "metadata.jsonl").read_text().splitlines()
                  if l.strip()]
            self.assertEqual([m for m in hf if m.get("split") == "train"], [])
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])

    def test_rights_and_procedural_exclusions_visible(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            # default policy: procedural fixtures are never positives; the empty
            # positive view succeeds with every frame explained, nothing invented
            man = build_snapshot(td, "s2", ["clip-clean", "clip-bad", "clip-fix"], str(Path(td) / "o2"), {})
            self.assertEqual(man["counts"]["positives"], 0)
            kinds = {e["context"] for e in man["exclusions"]}
            self.assertIn("positive", kinds, man["exclusions"])
            rep = validate_snapshot(str(Path(td) / "o2"))
            self.assertTrue(rep["ok"], rep["issues"])
            self.assertTrue(any("empty" in s for s in rep["skipped"]), rep["skipped"])
            # the research archive labels every row; nothing is silently a positive
            research = [json.loads(l) for l in
                        (Path(td) / "o2" / "research" / "metadata.jsonl").read_text().splitlines()]
            self.assertTrue(research and all("label_origin" in m for m in research))
            self.assertTrue(all(m["label_origin"] != "human-approved" for m in research))


if __name__ == "__main__":
    unittest.main()
