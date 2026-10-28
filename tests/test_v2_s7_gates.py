"""Second-remediation gates S7: runtime evidence from the playback harness.

Presented observations come from the runtime path; expectations are computed
independently in each test. Every injected fault must fail its verdict.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.checks import fixtures as F
from framebound.v2.media.canonical import canonical_pixels, pixel_sha256
from framebound.v2.media.timeline import select_slot
from framebound.v2.services import assets as AS
from framebound.v2.services import clips, contracts
from framebound.v2.services.errors import InvalidInput
from framebound.v2 import playback as PB


def _seed2(td: str) -> dict:
    """Two 2-slot clips on one contract family with world traces."""
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i in range(4):
        AS.import_asset(td, str(src / meta["clean"][i]), f"h{i}",
                        source_kind="procedural", rights="original")
    AS.import_asset(td, str(src / meta["clean"][0]), "hid",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "hst",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-H", project_id="p", identity_asset_ids=["hid"],
            style_asset_ids=["hst"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="x"))
    finally:
        con.close()
    for cid, budget in (("c-dep", 2), ("c-ent", 2)):
        contracts.propose_contract(td, {
            "schema_version": "2.0", "id": cid, "character_revision_id": "char-H",
            "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
            "canvas": {"width": 64, "height": 64, "units": "native_px"},
            "timing": {"ticks_per_second": 60, "holds": [4, 4]},
            "references": {"identity": "hid", "style": "hst",
                           "motion_guide_revision": "mg-H"},
            "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"}
                               for i in range(2)],
            "constraints": [{"id": "registration", "check": "native_registration",
                              "required": True}],
            "allowed_transforms": {"per_pose_scale": False,
                                   "rigid_translation_budget_px": budget}})
    clips.create_revision(td, "c-dep", "rev-dep", ["h0", "h1"], ["p0", "p1"])
    clips.create_revision(td, "c-ent", "rev-ent", ["h2", "h3"], ["p0", "p1"])
    clips.evaluate(td, "rev-dep")
    clips.evaluate(td, "rev-ent")
    return {"src": src, "meta": meta}


def _trace(td: str, rev: str, positions, planted) -> None:
    clips.record_world_trace(td, rev, positions, planted)


class TestPlaybackHarness(unittest.TestCase):
    def test_capture_matches_independent_departure_and_entry(self):
        with tempfile.TemporaryDirectory() as td:
            _seed2(td)
            _trace(td, "rev-dep", [[1.0, 0.0]] * 8, [True] * 8)
            _trace(td, "rev-ent", [[1.0, 0.0]] * 8, [True] * 8)
            rec = PB.interrupt(td, "rev-dep", 5, "rev-ent", 0,
                               support_window=[8, 50, 56, 62], world_tol=2.0,
                               entry_policy={"clip": "rev-ent", "slot": 0})
            # independent expectation: direct mapping + file pixels
            self.assertEqual(rec["departure"]["slot"], select_slot([4, 4], 5, True))
            con = S.connect(td)
            try:
                for key, slot, aid in (("departure", rec["departure"]["slot"], None),
                                       ("entry", 0, None)):
                    pass
                dep_bytes = S.blob_path(
                    td, S.get(con, "assets", "h1")[0]["byte_sha256"]).read_bytes()
                ent_bytes = S.blob_path(
                    td, S.get(con, "assets", "h2")[0]["byte_sha256"]).read_bytes()
            finally:
                con.close()
            want_dep = pixel_sha256(canonical_pixels(
                Image.open(io.BytesIO(dep_bytes)).convert("RGBA")))
            want_ent = pixel_sha256(canonical_pixels(
                Image.open(io.BytesIO(ent_bytes)).convert("RGBA")))
            self.assertEqual(rec["departure"]["pixel_sha256"], want_dep)
            self.assertEqual(rec["entry"]["pixel_sha256"], want_ent)
            self.assertEqual(rec["world_distance"], 0.0)
            self.assertEqual(rec["verdict"], "pass", rec)
            # a deliberately wrong expectation does NOT match (sensitive check)
            self.assertNotEqual(rec["departure"]["pixel_sha256"], want_ent)

    def test_contact_teleport_fails_with_both_feet_visible(self):
        with tempfile.TemporaryDirectory() as td:
            _seed2(td)
            _trace(td, "rev-dep", [[1.0, 0.0]] * 8, [True] * 8)
            _trace(td, "rev-ent", [[9.0, 0.0]] * 8, [True] * 8)
            rec = PB.interrupt(td, "rev-dep", 5, "rev-ent", 0,
                               support_window=[0, 0, 64, 64], world_tol=2.0,
                               entry_policy={"clip": "rev-ent", "slot": 0})
            # both endpoints planted and visibly supported, yet teleported
            self.assertGreater(rec["support"]["departure_px"], 0)
            self.assertGreater(rec["support"]["entry_px"], 0)
            self.assertEqual(rec["verdict"], "fail")
            self.assertTrue(any("teleport" in r for r in rec["reasons"]))

    def test_wrong_entry_and_delay_fail(self):
        with tempfile.TemporaryDirectory() as td:
            _seed2(td)
            _trace(td, "rev-dep", [[1.0, 0.0]] * 8, [True] * 8)
            _trace(td, "rev-ent", [[1.0, 0.0]] * 8, [True] * 8)
            wrong = PB.interrupt(td, "rev-dep", 5, "rev-ent", 1,
                                 entry_policy={"clip": "rev-ent", "slot": 0})
            self.assertEqual(wrong["verdict"], "fail")
            self.assertTrue(any("policy" in r for r in wrong["reasons"]))
            delayed = PB.interrupt(td, "rev-dep", 5, "rev-ent", 0,
                                   entry_policy={"clip": "rev-ent", "slot": 0},
                                   handoff_delay_ticks=1)
            self.assertEqual(delayed["verdict"], "fail")
            self.assertTrue(any("delayed" in r for r in delayed["reasons"]))

    def test_root_jump_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _seed2(td)
            _trace(td, "rev-dep", [[1.0, 0.0]] * 8, [True] * 8)
            _trace(td, "rev-ent", [[1.0, 0.0]] * 8, [True] * 8)
            # corrupt the entry registration past the frozen budget
            con = S.connect(td)
            try:
                row = con.execute(
                    "SELECT data FROM registrations WHERE id='rev-ent-fi-00-reg'").fetchone()
                reg = json.loads(row["data"])
                reg["translation_px"] = [12, 0]
                con.execute("UPDATE registrations SET data=? WHERE id='rev-ent-fi-00-reg'",
                            (json.dumps(reg),))
                con.commit()
            finally:
                con.close()
            rec = PB.interrupt(td, "rev-dep", 5, "rev-ent", 0,
                               entry_policy={"clip": "rev-ent", "slot": 0})
            self.assertEqual(rec["verdict"], "fail")
            self.assertTrue(any("root jump" in r for r in rec["reasons"]))

    def test_trace_binding_flows_into_evaluation_and_closure(self):
        with tempfile.TemporaryDirectory() as td:
            _seed2(td)
            _trace(td, "rev-dep", [[1.0, 0.0]] * 8, [True] * 8)
            _trace(td, "rev-ent", [[1.0, 0.0]] * 8, [True] * 8)
            rec = PB.interrupt(td, "rev-dep", 5, "rev-ent", 0,
                               entry_policy={"clip": "rev-ent", "slot": 0})
            self.assertEqual(rec["verdict"], "pass")
            PB.record_transition_trace(td, rec, origin="procedural")
            env = clips.evaluate(td, "rev-dep")
            con = S.connect(td)
            try:
                data, _ = S.get(con, "evaluations", env.artifacts[0]["id"])
            finally:
                con.close()
            raw = S.blob_path(td, data["evidence_manifest_sha256"]).read_bytes()
            manifest = json.loads(raw.decode())
            self.assertTrue(any(t["verdict"] == "pass"
                                for t in manifest.get("transitions", [])))
            from framebound.v2.exports import build_snapshot, validate_snapshot
            out = Path(td) / "snap"
            man = build_snapshot(td, "traces", ["rev-dep", "rev-ent"], str(out), {})
            self.assertTrue(any("transition_traces.jsonl" in f for f in man["files"]))
            rep = validate_snapshot(str(out))
            self.assertTrue(rep["ok"], rep["issues"])


if __name__ == "__main__":
    unittest.main()
