"""Second-remediation gates S6: training exports honor selection/decisions/splits.

Every gate corrupts or reassigns through the public export boundary and checks
the published (or refused) snapshot — never a helper's self-report.
"""
import base64
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.exports import build_snapshot, validate_snapshot
from framebound.v2.exports.dpo_adapter import load_preferences
from framebound.v2.services import clips, contracts, masks
from framebound.v2.services import corrections as C
from framebound.v2.services import packets
from framebound.v2.services import review_state as RS
from framebound.v2.services.authz import Actor

import sys
sys.path.insert(0, "/Volumes/datadisk0/data/appdata/repositories/framebound/tests")
from test_v2_r5_export import _seed, _fix_flow  # noqa: E402

REV = Actor(type="reviewer", id="human-1")
ORCH = Actor(type="orchestrator", id="spark-1")


def _approve_packet(td: str, rev: str, pkt: str, ev_id: str) -> None:
    packets.record_decision(td, REV, {"action": "approve", "clip_revision_id": rev,
                                      "packet_id": pkt, "expected_evaluation_id": ev_id})


class TestRevokedPreferences(unittest.TestCase):
    def test_revoked_chosen_comparison_is_not_positive_preference(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            # fix_flow approves + resolves rev-fix; now reject its chosen revision
            con = S.connect(td)
            try:
                ev = [D.Evaluation.model_validate_json(r["data"])
                      for r in con.execute("SELECT data FROM evaluations").fetchall()
                      if json.loads(r["data"])["clip_revision_id"] == "rev-fix"][-1]
            finally:
                con.close()
            packets.record_decision(td, REV, {"action": "reject",
                                              "clip_revision_id": "rev-fix",
                                              "packet_id": "pkt-fix",
                                              "expected_evaluation_id": ev.id})
            self.assertEqual(RS.current_state(td, "rev-fix")["acceptance"], "rejected")
            out = Path(td) / "snap"
            man = build_snapshot(td, "revoked", ["rev-fix"], str(out), {})
            self.assertEqual(man["counts"]["preferences"], 0)
            prefs = [json.loads(l) for l in
                     (out / "preferences.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(prefs, [])
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])


class TestSplitSemantics(unittest.TestCase):
    def _second_root(self, td: str) -> str:
        # independent root, same character + references, all-new pixels
        from framebound.v2.services import assets as AS
        src = Path(td) / "src2"
        src.mkdir()
        img = Image.new("RGBA", (64, 64), (200, 30, 30, 255))
        img.save(src / "alt.png")
        AS.import_asset(td, str(src / "alt.png"), "alt-all",
                        source_kind="generated", rights="original")
        aids = ["alt-all"] * 8
        clips.create_revision(td, "contract-R5", "rev-alt", aids,
                              [f"p{i}" for i in range(8)])
        clips.evaluate(td, "rev-alt")
        return "rev-alt"

    def test_same_identity_roots_cannot_straddle_heldout_splits(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            self._second_root(td)
            # strict: same family across train/test is refused before publish
            with self.assertRaises(ValueError):
                build_snapshot(td, "strict", ["rev-good", "rev-alt"], str(Path(td) / "s"),
                               {"split": {"train": ["rev-good"], "test": ["rev-alt"]},
                                "split_policy": "strict",
                                "include_procedural_positives": True})

    def test_exclude_removes_leaked_samples_and_validates(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            # exact duplicates across splits (same pixels, both revisions)
            clips.create_revision(td, "contract-R5", "rev-dup",
                                  [f"f{i}" for i in range(8)],
                                  [f"p{i}" for i in range(8)])
            clips.evaluate(td, "rev-dup")
            out = Path(td) / "snap"
            man = build_snapshot(td, "excl", ["rev-good", "rev-dup"], str(out),
                                 {"split": {"train": ["rev-good"], "test": ["rev-dup"]},
                                  "split_policy": "exclude",
                                  "include_procedural_positives": True})
            # leaked positives are REMOVED, not retained with a logged note
            hf = [json.loads(l) for l in
                  (out / "hf" / "metadata.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual([m for m in hf if m.get("split") == "train"
                              and m.get("clip") == "rev-good"], [])
            self.assertTrue(any(e.get("context", "") == "split-exclude"
                                for e in man["exclusions"]))
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])

    def test_exporter_never_publishes_what_validator_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            out = Path(td) / "snap"
            with self.assertRaises(ValueError):
                build_snapshot(td, "trav", ["rev-good"], str(out),
                               {"split": {"train": ["rev-good"], "test": ["rev-good"]},
                                "split_policy": "strict"})
            self.assertFalse((out / "manifest.json").exists())
            self.assertFalse((out / "COMPLETE").exists())


class TestSelectedClosure(unittest.TestCase):
    def test_selected_export_omits_unrelated_private_note(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            info = _fix_flow(td)
            # unrelated private note on an unselected revision
            packets.record_review_event(td, REV, {"action": "mark_issue",
                "clip_revision_id": "rev-unknown",
                "note": "PRIVATE curator note do-not-export"})
            out = Path(td) / "snap"
            build_snapshot(td, "sel", ["rev-fix"], str(out), {})
            events = [json.loads(l) for l in
                      (out / "closure" / "events.jsonl").read_text().splitlines()
                      if l.strip()]
            notes = " ".join(e.get("note", "") for e in events)
            self.assertNotIn("PRIVATE", notes)
            self.assertNotIn("rev-unknown", notes)
            # ... but the selected task's own history is present
            clips_txt = " ".join(e.get("clip_revision_id", "") for e in events)
            self.assertIn("rev-fix", clips_txt)

    def test_closure_resolves_without_db(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            build_snapshot(td, "db", ["rev-good", "rev-bad", "rev-fix"], str(out),
                           {"include_procedural_positives": True})
            moved = Path(td) / "moved"
            shutil.move(str(out), str(moved))
            (Path(td) / "framebound.sqlite3").unlink()
            shutil.rmtree(Path(td) / "blobs")
            shutil.rmtree(Path(td) / "src", ignore_errors=True)
            shutil.rmtree(Path(td) / "src2", ignore_errors=True)
            rep = validate_snapshot(str(moved))
            self.assertTrue(rep["ok"], rep["issues"])
            # training images + pairs still materialize from the snapshot alone
            self.assertGreater(rep["loaders"]["coco_images"], 0)
            rows = load_preferences(str(moved))
            for row in rows:
                self.assertTrue(row["chosen_images"] and row["rejected_images"])
                for im in row["chosen_images"] + row["rejected_images"]:
                    self.assertGreater(im["size"][0], 0)

    def test_unknown_rights_reference_withheld_from_closure(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            from framebound.v2.services import assets as AS
            from framebound.v2.services import approvals as A
            from framebound.v2.checks import fixtures as F
            src = Path(td) / "src"
            meta = F.build_cycle(src)
            AS.import_asset(td, str(src / meta["clean"][2]), "id-mystery",
                            source_kind="generated", rights="mystery-terms")
            con = S.connect(td)
            try:
                S.insert(con, D.CharacterRevision(
                    id="char-myst", project_id="p", identity_asset_ids=["id-mystery"],
                    style_asset_ids=["st-art"], view_set=["side"],
                    canvas={"width": 64, "height": 64}, scale_ruler="x"))
            finally:
                con.close()
            con = S.connect(td)
            try:
                hashes = {"id-mystery": S.get(con, "assets", "id-mystery")[0]["byte_sha256"]}
                hashes.update({f"f{i}": S.get(con, "assets", f"f{i}")[0]["byte_sha256"]
                               for i in range(8)})
            finally:
                con.close()
            A.propose_motion_guide(td, ORCH, {
                "schema_version": "2.0", "id": "mg-myst", "character_revision_id": "char-myst",
                "entries": [{"phase": f"p{i}", "asset_id": "f0",
                             "byte_sha256": hashes["f0"]} for i in range(8)]})
            contracts.propose_contract(td, {
                "schema_version": "2.0", "id": "contract-myst", "character_revision_id": "char-myst",
                "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
                "canvas": {"width": 64, "height": 64, "units": "native_px"},
                "timing": {"ticks_per_second": 60, "holds": [4] * 8},
                "references": {"identity": "id-mystery", "style": "st-art",
                               "motion_guide_revision": "mg-myst"},
                "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                                   for i in range(8)],
                "constraints": [{"id": "registration", "check": "native_registration",
                                 "required": True}],
                "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
            clips.create_revision(td, "contract-myst", "rev-myst",
                                  [f"f{i}" for i in range(8)],
                                  [f"p{i}" for i in range(8)])
            clips.evaluate(td, "rev-myst")
            out = Path(td) / "snap"
            man = build_snapshot(td, "myst", ["rev-myst"], str(out),
                                 {"include_procedural_positives": True})
            self.assertTrue(any(e.get("context", "") == "closure-rights"
                                for e in man["exclusions"]), man["exclusions"])
            refs = list((out / "closure" / "references").glob("*.png"))
            self.assertFalse(any("mystery" in r.read_bytes().hex() for r in refs))
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])

    def test_traversal_ids_cannot_escape_staging(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            from framebound.v2.services import assets as AS
            evil_ids = ["../../evil", "a/b", "x" * 120, "..", "a\\b"]
            for i, eid in enumerate(evil_ids):
                src = Path(td) / f"evil{i}.png"
                Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(src)
                AS.import_asset(td, str(src), eid, source_kind="procedural",
                                rights="original")
            # baseline AFTER project writes: only export-created files may
            # appear below, and all of them inside the staging directory
            before = set()
            for root, _dirs, files in __import__("os").walk(td):
                for f in files:
                    before.add(str(Path(root) / f))
            out = Path(td) / "snap"
            man = build_snapshot(td, "trav", ["rev-bad"], str(out), {})
            after = set()
            for root, _dirs, files in __import__("os").walk(td):
                for f in files:
                    after.add(str(Path(root) / f))
            outside = {f for f in after - before if not f.startswith(str(out))}
            self.assertEqual(outside, set())
            for rel in man["files"]:
                self.assertNotIn("..", Path(rel).parts)
                self.assertFalse(Path(rel).is_absolute())
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])


class TestTemporalAndCorruption(unittest.TestCase):
    def test_temporal_duplicate_slot_rejected_with_same_counts(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            build_snapshot(td, "tmp", ["rev-fix"], str(out), {})
            rows = [json.loads(l) for l in
                    (out / "temporal.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(len(rows), 1)
            frames = rows[0]["frames"]
            # duplicate a slot, drop another: counts identical, order broken
            frames[3] = dict(frames[3])
            frames[3]["slot"] = 2
            rows[0]["frames"] = frames
            (out / "temporal.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n")
            rep = validate_snapshot(str(out))
            self.assertFalse(rep["ok"])
            self.assertTrue(any("slot" in i for i in rep["issues"]))

    def test_world_trace_flows_into_temporal(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            clips.record_world_trace(td, "rev-good",
                                     [[float(i), 0.0] for i in range(32)],
                                     [True] * 32)
            out = Path(td) / "snap"
            build_snapshot(td, "wt", ["rev-good"], str(out), {})
            rows = [json.loads(l) for l in
                    (out / "temporal.jsonl").read_text().splitlines() if l.strip()]
            row = next(r for r in rows if r["clip_revision_id"] == "rev-good")
            self.assertEqual(row["traces"]["world_positions"][0], [0.0, 0.0])
            self.assertNotIn("world_positions", row["traces"]["missing"])

    def test_corrupt_dependency_fails_for_the_right_reason(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            build_snapshot(td, "cor", ["rev-fix"], str(out),
                           {"include_procedural_positives": True})
            # swap two packaged positive bytes: counts preserved, pixels wrong
            import hashlib
            pngs = sorted((out / "hf" / "data").glob("*.png"))
            self.assertGreaterEqual(len(pngs), 2)
            a, b = pngs[0].read_bytes(), pngs[1].read_bytes()
            pngs[0].write_bytes(b)
            pngs[1].write_bytes(a)
            rep = validate_snapshot(str(out))
            self.assertFalse(rep["ok"])
            self.assertTrue(any("hash mismatch" in i or "differ" in i
                                for i in rep["issues"]), rep["issues"])

    def test_dpo_adapter_opens_real_pairs(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "dpo", ["rev-good", "rev-bad", "rev-fix"], str(out),
                                 {"include_procedural_positives": True})
            self.assertGreater(man["counts"]["preferences"], 0)
            rows = load_preferences(str(out))
            self.assertTrue(rows)
            for row in rows:
                self.assertTrue(row["conditioning"]["contract"])
                self.assertTrue(row["conditioning"]["chosen_evaluation"])
                for im in row["chosen_images"] + row["rejected_images"]:
                    self.assertGreater(im["size"][0], 0)
                    self.assertEqual(im["mode"], "RGBA")


if __name__ == "__main__":
    unittest.main()
