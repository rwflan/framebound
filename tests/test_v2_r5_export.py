"""R5 regressions: pixel-correct masks, honest training views, portable snapshots.

Every probe targets the audited defect at the public boundary: mask geometry
through _rle/decode round-trips, policy through default exports, approval
folding through approve->reject, preferences through explicit comparisons,
portability through moved-snapshot validation without the database.
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from pycocotools import mask as coco_mask

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.checks import fixtures as F
from framebound.v2.exports import build_snapshot, validate_snapshot
from framebound.v2.exports.snapshot import _rle
from framebound.v2.services import approvals as A
from framebound.v2.services import clips, contracts, masks as M, packets
from framebound.v2.services import corrections as C
from framebound.v2.services import eligibility as EL
from framebound.v2.services.authz import Actor

ORCH = Actor(type="orchestrator", id="spark-1")
REV = Actor(type="reviewer", id="human-1")

try:
    import _lzma  # noqa: F401
    import lzma  # noqa: F401
    import datasets  # noqa: F401
    _HAS_DATASETS = True
except ImportError:
    _HAS_DATASETS = False


def _seed(td: str) -> dict:
    """Generated-original clean frames + blank/unknown variants; approved guides."""
    from framebound.v2.services import assets as AS
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        AS.import_asset(td, str(src / rel), f"f{i}", source_kind="generated",
                        rights="original")
    AS.import_asset(td, str(src / meta["faults"]["blank"]), "fx-blank",
                    source_kind="procedural", rights="original")
    raw = S.blob_path(td, S.get(S.connect(td), "assets", "f3")[0]["byte_sha256"]).read_bytes()
    Path(td, "unk.png").write_bytes(raw)
    AS.import_asset(td, str(Path(td) / "unk.png"), "fx-unknown",
                    source_kind="generated", rights="unknown")
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-R5", project_id="p", identity_asset_ids=["id-art"],
            style_asset_ids=["st-art"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="x"))
    finally:
        con.close()
    con = S.connect(td)
    try:
        hashes = {f"f{i}": S.get(con, "assets", f"f{i}")[0]["byte_sha256"]
                  for i in range(8)}
    finally:
        con.close()
    A.propose_motion_guide(td, ORCH, {
        "schema_version": "2.0", "id": "mg-R5", "character_revision_id": "char-R5",
        "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                     "byte_sha256": hashes[f"f{i}"]} for i in range(8)]})
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-R5", "character_revision_id": "char-R5",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "id-art", "style": "st-art",
                       "motion_guide_revision": "mg-R5"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                           for i in range(8)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "area", "check": "silhouette_area", "required": True,
             "params": {"max_fraction": 0.35}}],
        "allowed_transforms": {"per_pose_scale": False,
                               "rigid_translation_budget_px": 2}})
    A.approve_reference(td, REV, "char-R5", "mg-R5")
    aids = [f"f{i}" for i in range(8)]
    clips.create_revision(td, "contract-R5", "rev-good", aids,
                          [f"p{i}" for i in range(8)])
    bad = list(aids)
    bad[3] = "fx-blank"
    clips.create_revision(td, "contract-R5", "rev-bad", bad,
                          [f"p{i}" for i in range(8)])
    unk = list(aids)
    unk[3] = "fx-unknown"
    clips.create_revision(td, "contract-R5", "rev-unknown", unk,
                          [f"p{i}" for i in range(8)])
    ev_good = clips.evaluate(td, "rev-good")
    ev_bad = clips.evaluate(td, "rev-bad")
    return {"ev_good": ev_good, "ev_bad": ev_bad}


def _fix_flow(td: str) -> dict:
    """Issue -> mask -> claim -> submit rev-fix -> comparison packet + approval."""
    env, task = C.open_issue(td, REV, {"action": "mark_issue",
                                       "clip_revision_id": "rev-bad",
                                       "frame_range": [12, 15],
                                       "roi": {"left": 30, "top": 30,
                                               "right": 31, "bottom": 31},
                                       "note": "hole", "category": "hole"})
    Image.new("L", (64, 64), 255).save(Path(td) / "full.png")
    from framebound.v2.services import assets as AS
    try:
        AS.import_asset(td, str(Path(td) / "full.png"), "m-full",
                        source_kind="original", rights="original")
    except Exception:
        pass
    M.approve_mask(td, REV, task.source_issue_event_id, "m-full", [3])
    cl = C.claim(td, ORCH, task.id, C.get_task(td, task.id)["version"])
    out = C.submit_correction(td, ORCH, task.id, claim_token=cl["claim_token"],
                              expected_version=cl["version"],
                              new_revision_id="rev-fix", slot_asset_ids={3: "f3"},
                              recipe="repair:bounded-patch",
                              baseline_evaluation_id=task.baseline_evaluation_id,
                              idempotency_key="r5-fix")
    assert out["ok"], out
    con = S.connect(td)
    try:
        ev_fix = [D.Evaluation.model_validate_json(r["data"])
                  for r in con.execute("SELECT data FROM evaluations").fetchall()
                  if json.loads(r["data"])["clip_revision_id"] == "rev-fix"][-1]
    finally:
        con.close()
    pkt = packets.create_packet(td, "pkt-fix", "rev-fix", ev_fix.id, "review",
                                comparison_revision_id="rev-bad")
    packets.record_decision(td, REV, {"action": "approve", "clip_revision_id": "rev-fix",
                                      "packet_id": pkt.revision_id and "pkt-fix",
                                      "expected_evaluation_id": ev_fix.id})
    # The corrected candidate is releasable only once its task is resolved
    # against the published candidate (an approved-but-unresolved candidate
    # stays blocked by design).
    C.resolve_issue(td, REV, task.source_issue_event_id, "rev-fix",
                    packet_id="pkt-fix")
    return {"task": task, "ev_fix": ev_fix}


class TestMaskGeometry(unittest.TestCase):
    def test_3x5_asymmetric_mask_exact_round_trip(self):
        m = np.zeros((3, 5), dtype=np.uint8)
        m[0, 1:4] = 1
        m[2, 4] = 1
        raw = bytes(m.ravel().tolist())
        rle = _rle(raw, 5, 3)
        decoded = coco_mask.decode({**rle, "counts": rle["counts"].encode()})
        self.assertEqual(decoded.shape, (3, 5))
        self.assertTrue(np.array_equal(np.asarray(decoded),
                                       np.asarray(m)),
                        "scrambled geometry must fail pixel comparison")
        self.assertEqual(int(np.asarray(decoded).sum()), 4)
        ys, xs = np.nonzero(np.asarray(decoded))
        bbox = [int(xs.min()), int(ys.min()),
                int(xs.max()) - int(xs.min()) + 1, int(ys.max()) - int(ys.min()) + 1]
        self.assertEqual(bbox, [1, 0, 4, 3])
        # the old defect preserved area while scrambling position: prove this
        # test would have caught it
        scrambled = np.frombuffer(raw, dtype=np.uint8).reshape((3, 5), order="F")
        self.assertFalse(np.array_equal(scrambled, np.asarray(m)))
        self.assertEqual(int(scrambled.sum()), 4)

    def test_rle_rejects_misaligned_masks(self):
        with self.assertRaises(ValueError):
            _rle(bytes(10), 5, 3)


class TestPolicyViews(unittest.TestCase):
    def test_default_export_excludes_procedural_unknown_and_unreviewed(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "pol", ["rev-good", "rev-bad", "rev-unknown"],
                                 str(out), {})
            # nothing eligible: no human approval yet -> legitimately empty positives
            self.assertEqual(man["counts"]["positives"], 0)
            hf_files = {m["file_name"] for m in
                        [json.loads(l) for l in
                         (out / "hf" / "metadata.jsonl").read_text().splitlines() if l.strip()]} \
                if (out / "hf" / "metadata.jsonl").read_text().strip() else set()
            self.assertEqual(hf_files, set())
            research = [json.loads(l) for l in
                        (out / "research" / "metadata.jsonl").read_text().splitlines() if l.strip()]
            by_asset = {m["asset_id"]: m for m in research}
            self.assertEqual(by_asset["fx-unknown"]["exclusion"] is not None, True)
            self.assertIn("rights", by_asset["fx-unknown"]["exclusion"])
            self.assertEqual(by_asset["fx-blank"]["label_origin"], "procedural-test")
            # unknown-rights asset bytes never copied into the positive view
            self.assertFalse(list((out / "hf" / "data").glob("*")))
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])
            self.assertTrue(any("empty" in s for s in rep["skipped"]))

    def test_approved_positive_and_later_reject(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            ev_id = clips.evaluate(td, "rev-good").artifacts[0]["id"]
            pkt = packets.create_packet(td, "pkt-good", "rev-good", ev_id, "review")
            packets.record_decision(td, REV, {"action": "approve",
                                              "clip_revision_id": "rev-good",
                                              "packet_id": "pkt-good",
                                              "expected_evaluation_id": ev_id})
            self.assertTrue(EL.release_eligibility(td, "rev-good")["eligible"])
            man = build_snapshot(td, "pol2", ["rev-good"], str(Path(td) / "s1"), {})
            self.assertEqual(man["counts"]["positives"], 8)
            hf = [json.loads(l) for l in
                  (Path(td) / "s1" / "hf" / "metadata.jsonl").read_text().splitlines() if l.strip()]
            self.assertTrue(hf and all(m["label_origin"] == "human-approved" for m in hf))
            # a later reject invalidates current positive eligibility
            packets.record_decision(td, REV, {"action": "reject",
                                              "clip_revision_id": "rev-good",
                                              "packet_id": "pkt-good",
                                              "expected_evaluation_id": ev_id,
                                              "note": "second look"})
            self.assertFalse(EL.release_eligibility(td, "rev-good")["eligible"])
            man2 = build_snapshot(td, "pol3", ["rev-good"], str(Path(td) / "s2"), {})
            self.assertEqual(man2["counts"]["positives"], 0)
            self.assertTrue(any("reject" in e["reason"] or "supersede" in e["reason"]
                                or "ineligible" in e["reason"] or "Revision" in e["reason"]
                                or "revision" in e["reason"]
                                for e in man2["exclusions"]))

    def test_system_decision_never_becomes_human_approval(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            from framebound.v2.services.errors import AuthorizationError
            ev_id = clips.evaluate(td, "rev-good").artifacts[0]["id"]
            packets.create_packet(td, "pkt-sys", "rev-good", ev_id, "review")
            SYS = Actor(type="system", id="demo-script")
            # the gate refuses self-asserted system approval outright
            with self.assertRaises(AuthorizationError):
                packets.record_review_event(td, SYS, {"id": "sys-approve", "action": "approve",
                                                      "clip_revision_id": "rev-good",
                                                      "packet_id": "pkt-sys"})
            self.assertFalse(EL.release_eligibility(td, "rev-good")["eligible"])
            man = build_snapshot(td, "sys", ["rev-good"], str(Path(td) / "s"), {})
            self.assertEqual(man["counts"]["positives"], 0)
            research = [json.loads(l) for l in
                        (Path(td) / "s" / "research" / "metadata.jsonl").read_text().splitlines()
                        if l.strip()]
            self.assertTrue(all(m["human_decision"] == "unreviewed" for m in research))


class TestPreferences(unittest.TestCase):
    def test_explicit_comparison_pair_and_weak_view(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "pref", ["rev-good", "rev-bad", "rev-fix"],
                                 str(out), {'include_procedural_positives':True})
            prefs = [json.loads(l) for l in
                     (out / "preferences.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(len(prefs), 1)
            pr = prefs[0]
            self.assertEqual(pr["origin"], "human-comparison")
            self.assertEqual(pr["chosen_revision"], "rev-fix")
            self.assertEqual(pr["rejected_revision"], "rev-bad")
            self.assertTrue(pr["comparison_packet"] and pr["rejected_issue"])
            self.assertIn("not identical generation prompts",
                          pr["conditioning"]["execution"])
            ch = {f["sha256"] for f in pr["chosen"]}
            rj = {f["sha256"] for f in pr["rejected"]}
            self.assertTrue(ch and rj and ch != rj)
            weak = [json.loads(l) for l in
                    (out / "weak_preferences.jsonl").read_text().splitlines() if l.strip()]
            self.assertTrue(all(w["origin"] == "technical-ranking" for w in weak))
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])
            self.assertEqual(rep["loaders"]["preferences"], 1)

    def test_descendant_approval_alone_yields_no_pair(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            env, task = C.open_issue(td, REV, {"action": "mark_issue",
                                               "clip_revision_id": "rev-bad",
                                               "frame_range": [12, 15],
                                               "note": "hole", "category": "hole"})
            Image.new("L", (64, 64), 255).save(Path(td) / "full.png")
            from framebound.v2.services import assets as AS
            AS.import_asset(td, str(Path(td) / "full.png"), "m-full",
                            source_kind="original", rights="original")
            M.approve_mask(td, REV, task.source_issue_event_id, "m-full", [3])
            cl = C.claim(td, ORCH, task.id, C.get_task(td, task.id)["version"])
            out = C.submit_correction(td, ORCH, task.id, claim_token=cl["claim_token"],
                                      expected_version=cl["version"],
                                      new_revision_id="rev-fix2", slot_asset_ids={3: "f3"},
                                      recipe="repair:bounded-patch",
                                      baseline_evaluation_id=task.baseline_evaluation_id,
                                      idempotency_key="k-desc")
            self.assertTrue(out["ok"])
            # plain packet approval, no comparison: not an explicit pair
            con = S.connect(td)
            try:
                evs = [json.loads(r["data"]) for r in
                       con.execute("SELECT data FROM evaluations").fetchall()]
                ev_fix = [e for e in evs if e["clip_revision_id"] == "rev-fix2"][-1]
            finally:
                con.close()
            packets.create_packet(td, "pkt-plain", "rev-fix2", ev_fix["id"], "review")
            packets.record_review_event(td, REV, {"action": "approve",
                                                  "clip_revision_id": "rev-fix2",
                                                  "packet_id": "pkt-plain"})
            man = build_snapshot(td, "desc", ["rev-bad", "rev-fix2"], str(Path(td) / "s"), {})
            prefs = (Path(td) / "s" / "preferences.jsonl").read_text().strip()
            self.assertEqual(prefs, "")


class TestPortability(unittest.TestCase):
    def test_moved_snapshot_loads_without_database_or_network(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "move", ["rev-good", "rev-bad", "rev-fix"],
                                 str(out), {"include_procedural_positives": True,
                                            "split": {"train": ["rev-good", "rev-fix"],
                                                      "test": []}})
            moved = Path(td) / "moved"
            shutil.copytree(out, moved)
            rep = validate_snapshot(str(moved))
            self.assertTrue(rep["ok"], rep["issues"])
            # no absolute local paths, credentials, or expiring provider URLs
            blob = "\n".join(p.read_text(errors="replace") for p in moved.rglob("*.json*"))
            self.assertNotIn(td, blob)
            self.assertNotIn("MODEL_API_KEY", blob)
            self.assertNotIn("api.meta.ai", blob)
            # every packaged file rehashes; no stale extras
            self.assertEqual(rep["loaders"]["coco_images"], man["counts"]["images"])
            # temporal rows resolve ordered frames against packaged bytes
            temps = [json.loads(l) for l in
                     (moved / "temporal.jsonl").read_text().splitlines() if l.strip()]
            by_id = {t["clip_revision_id"]: t for t in temps}
            self.assertEqual(len(by_id["rev-good"]["frames"]), 8)
            self.assertEqual(by_id["rev-good"]["total_ticks"], 32)
            self.assertIn("missing", by_id["rev-good"]["traces"])

    def test_mutated_pixels_fail_validation(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            build_snapshot(td, "mut", ["rev-good", "rev-bad", "rev-fix"],
                           str(out), {"include_procedural_positives": True,
                                      "split": {"train": ["rev-good", "rev-fix"], "test": []}})
            target = sorted((out / "hf" / "data").glob("*.png"))[0]
            img = Image.open(target).convert("RGBA")
            img.putpixel((0, 0), (255, 0, 0, 255))
            img.save(target)
            rep = validate_snapshot(str(out))
            self.assertFalse(rep["ok"])
            self.assertTrue(rep["issues"])

    def test_export_snapshot_row_and_atomic_reuse_rules(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "atom", ["rev-good"], str(out), {})
            con = S.connect(td)
            try:
                row, _ = S.get(con, "export_snapshots", "snap-atom")
            finally:
                con.close()
            self.assertEqual(row["byte_manifest"]["manifest.json"] if "manifest.json" in row["byte_manifest"] else None, None)
            self.assertTrue(set(row["byte_manifest"]) >= {"hf/metadata.jsonl", "coco/annotations.json"})
            # rebuild identical content under the same name: dedupe, no conflict
            man2 = build_snapshot(td, "atom", ["rev-good"], str(Path(td) / "snap2"), {})
            self.assertEqual(man2["files"], man["files"])
            # retrying the identical request returns its identity (no rebuild,
            # no overwrite); an incompatible payload to the same name conflicts
            man3 = build_snapshot(td, "atom", ["rev-good"], str(out), {})
            self.assertEqual(man3["inputs_digest"], man["inputs_digest"])
            self.assertTrue((out / "manifest.json").is_file())
            with self.assertRaises(Exception):
                build_snapshot(td, "atom", ["rev-bad"], str(out), {})
            foreign = Path(td) / "foreign"
            foreign.mkdir()
            (foreign / "keep.txt").write_text("user data")
            with self.assertRaises(Exception):
                build_snapshot(td, "atom", ["rev-good"], str(foreign),
                               {"replace": True})

    def test_no_lzma_stub_in_process(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            build_snapshot(td, "lz", ["rev-bad"], str(Path(td) / "s"), {})
            validate_snapshot(str(Path(td) / "s"))
            self.assertFalse(getattr(sys.modules.get("lzma"), "_framebound_stub", False))

    @unittest.skipUnless(_HAS_DATASETS, "needs an interpreter with _lzma + datasets")
    def test_datasets_imagefolder_materializes_pixels(self):
        import datasets
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            _fix_flow(td)
            out = Path(td) / "snap"
            man = build_snapshot(td, "ds", ["rev-good", "rev-bad", "rev-fix"],
                                 str(out), {"include_procedural_positives": True,
                                            "split": {"train": ["rev-good", "rev-fix"],
                                                      "test": []}})
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])
            self.assertEqual(rep["loaders"].get("method"), "datasets-imagefolder")
            ds = datasets.load_dataset("imagefolder", data_dir=str(out / "hf"), split="train")
            self.assertEqual(len(ds), man["counts"]["positives"])
            px = ds[0]["image"]
            px.load()
            self.assertGreater(px.size[0], 0)


if __name__ == "__main__":
    unittest.main()
