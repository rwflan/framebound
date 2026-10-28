"""R7 gate: procedural replay with honest labels, measured traces, real flight.

The synthetic suite still catches controlled faults (injected separately, never
mixed into demo totals) but never produces fake human labels. Flight/support
semantics are exercised through presented pixels; interruptions are measured
traces over all eight run phases plus held-tick boundaries.
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import storage as S
from framebound.v2.demo_character import SUPPORT_WINDOW, build_character
from framebound.v2.demo_wp6 import _support_min, run_wp6
from framebound.v2.media.timeline import select_slot
from framebound.v2.services import assets, clips
from framebound.v2.services.errors import InvalidInput


class GenuineDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp()
        cls.rep = run_wp6(str(Path(cls.td) / "wp6"))
        cls.proj = str(Path(cls.td) / "wp6" / "project")

    def test_counts_are_scoped_never_double_counted(self):
        man_clips = self.rep["clips"]
        self.assertEqual(man_clips, {"run": 8, "jump": 6, "attack": 6, "idle": 4})
        # 22 independent clip rasters (idle_0 == idle_2 by design), 24 presented
        # samples, 6 transition drawings tracked separately, overlaps explicit
        self.assertEqual(self.rep["independent_drawings"], 22)
        self.assertEqual(self.rep["transition_drawings"], 6)
        self.assertEqual(self.rep["presented_samples"], 24)
        self.assertNotEqual(self.rep["independent_drawings"], self.rep["presented_samples"])
        self.assertEqual(self.rep["presented_ticks"], {"run": 32, "jump": 24, "attack": 24, "idle": 16})
        # masters duplicate clip frames by design; entries may too — listed, not hidden
        self.assertIn("identity", self.rep["reference_overlap"])
        self.assertTrue(self.rep["transition_overlap"])
        self.assertEqual(self.rep["origin"], "procedural")
        self.assertIn("procedural", self.rep["badge"])

    def test_three_transitions_evaluated(self):
        self.assertEqual(sorted(self.rep["transitions"]),
                         ["idle-run-01", "run-attack-01", "run-idle-01"])
        self.assertTrue(all(s == "pass" for s in self.rep["transitions_evaluated"].values()),
                        self.rep["transitions_evaluated"])

    def test_evaluations_pass_with_honest_badges(self):
        self.assertTrue(all(s == "pass" for s in self.rep["evaluations"].values()))
        self.assertTrue(all(isinstance(c, dict) and c["required_total"] > 0
                            for c in self.rep["coverage"].values()))
        self.assertIn("replay", self.rep["badge"])
        self.assertEqual(self.rep["origin"], "procedural")
        self.assertFalse(self.rep["provider_ledger"]["sent"])
        self.assertEqual(self.rep["provider_ledger"]["mode"], "not_configured")

    def test_no_scripted_human_approval(self):
        con = S.connect(self.proj)
        try:
            decs = [json.loads(r["data"]) for r in
                    con.execute("SELECT data FROM review_events").fetchall()]
            tasks = [json.loads(r["data"]) for r in
                     con.execute("SELECT data FROM correction_tasks").fetchall()]
        finally:
            con.close()
        approves = [d for d in decs if d["action"] == "approve"]
        self.assertEqual(approves, [], "replay must not record its own human approval")
        self.assertEqual(tasks, [])
        self.assertEqual(self.rep["pending_decision"]["status"], "unreviewed")
        self.assertIn("UNREVIEWED", self.rep["visual_acceptance"])
        self.assertNotIn("decision", {k for k in self.rep if k == "decision"})

    def test_procedural_source_kind_everywhere(self):
        con = S.connect(self.proj)
        try:
            kind_rights = {(json.loads(r["data"])["source_kind"], json.loads(r["data"])["rights"])
                           for r in con.execute("SELECT data FROM assets").fetchall()}
        finally:
            con.close()
        self.assertTrue(kind_rights)
        self.assertTrue(all(k == "procedural" for k, _ in kind_rights),
                        f"demo art must be labeled procedural: {kind_rights}")
        self.assertTrue(all(r == "original" for _, r in kind_rights))
        # ...and the export keeps it out of positives without an explicit opt-in
        self.assertEqual(self.rep["snapshot_counts"]["positives"], 0)

    def test_run_contact_and_jump_flight_match_pixels(self):
        char_dir = Path(self.td) / "wp6" / "character"
        man = build_character(str(char_dir) + "-measure")
        # run declares continuous contact: every frame shows support
        run_sup = [_support_min(Image.open(Path(str(char_dir) + "-measure") / rel).convert("RGBA"))
                   for rel in man["clips"]["run"]["frames"]]
        self.assertTrue(all(s > 0 for s in run_sup), run_sup)
        # jump declares flight at slots 2,3,4: those rasters are truly airborne
        jump_sup = [_support_min(Image.open(Path(str(char_dir) + "-measure") / rel).convert("RGBA"))
                    for rel in man["clips"]["jump"]["frames"]]
        for s in (2, 3, 4):
            self.assertEqual(jump_sup[s], 0, f"flight slot {s} shows support: {jump_sup}")
        for s in (0, 1, 5):
            self.assertGreater(jump_sup[s], 0, f"contact slot {s} shows no support")

    def test_interruptions_cover_all_phases_and_boundaries_measured(self):
        intrs = self.rep["interruptions"]
        slots = sorted({i["departure_slot"] for i in intrs})
        self.assertEqual(slots, [0, 1, 2, 3, 4, 5, 6, 7])
        ticks = sorted({i["tick"] for i in intrs})
        # every held-tick boundary crossed: 3->4, 7->8, ... 27->28
        for edge in (4, 8, 12, 16, 20, 24, 28):
            self.assertIn(edge - 1, ticks)
            self.assertIn(edge, ticks)
        for i in intrs:
            self.assertEqual(i["departure_slot"], select_slot([4] * 8, i["tick"], True))
            self.assertEqual(i["entry"], "clip-attack-01:0")
            # measured through the playback harness, not assigned: the
            # departure/entry observations carry presented pixel hashes, the
            # entry slot matches policy, and contact verdicts are computed
            self.assertTrue(i["departure_pixels_intact"], i)
            self.assertTrue(i["entry_slot_correct"], i)
            self.assertTrue(i["entry_pixels_intact"], i)
            self.assertEqual(i["verdict"], "pass", i)
            self.assertTrue(i["contact_continuous"], i)
            self.assertGreater(i["departure_support_px"], 0)
            self.assertGreater(i["entry_support_px"], 0)
        traces = json.loads((Path(self.td) / "wp6" / "transition_traces.json").read_text())
        self.assertEqual(len(traces["interruptions"]), len(intrs))
        self.assertIn("attack", traces["entry_policy"]["clip"])

    def test_mirror_prohibited_for_asymmetric_design(self):
        con = S.connect(self.proj)
        ch, _ = S.get(con, "character_revisions", "pip-rev-01")
        self.assertNotEqual(ch["asymmetry"], "symmetric")
        con.close()
        with self.assertRaises(InvalidInput):
            clips.register_candidate(self.proj, "clip-run-01", "clip-mirror",
                                     {0: "pip_run_00"}, recipe="mirror whole drawing")

    def test_per_pose_fit_blocked(self):
        with self.assertRaises(InvalidInput):
            clips.register_candidate(self.proj, "clip-run-01", "clip-fit",
                                     {0: "pip_run_00"}, recipe="independent-fit per pose")

    def test_injected_faults_stay_labeled_regressions(self):
        # a controlled fault fails the declared profile without touching demo totals
        from framebound.v2.checks import fixtures as F
        src = Path(self.td) / "fault-src"
        meta = F.build_cycle(src)
        assets.import_asset(self.proj, str(src / meta["faults"]["pulse"]), "fx-pulse-test",
                            source_kind="procedural", rights="original")
        aids = [f"pip_run_{i:02d}" for i in range(8)]
        aids[2] = "fx-pulse-test"
        con = S.connect(self.proj)
        try:
            cdata, _ = S.get(con, "contract_revisions", "contract-run-run")
        finally:
            con.close()
        phases = [e["phase"] for e in sorted(cdata["phase_schedule"], key=lambda e: e["slot"])]
        clips.create_revision(self.proj, "contract-run-run", "clip-injected", aids, phases)
        ev = clips.evaluate(self.proj, "clip-injected")
        self.assertEqual(ev.technical_status.value, "fail")
        codes = {i["code"] for i in ev.issues}
        self.assertIn("torso_span", codes)
        # the demo report is untouched by the injected regression
        self.assertEqual(self.rep["independent_drawings"], 22)
        self.assertEqual(self.rep["presented_samples"], 24)


class RecordedRun(unittest.TestCase):
    def _approved_project(self, td: str) -> dict:
        from framebound.v2.checks import fixtures as F
        from framebound.v2.services import approvals as A
        from framebound.v2.services import briefs as B
        from framebound.v2.services import contracts as CT
        from framebound.v2.services.authz import Actor
        src = Path(td) / "src"
        meta = F.build_cycle(src)
        for i, rel in enumerate(meta["clean"]):
            assets.import_asset(td, str(src / rel), f"f{i}", source_kind="original",
                                rights="original")
        assets.import_asset(td, str(src / meta["clean"][0]), "id-art",
                            source_kind="original", rights="original")
        assets.import_asset(td, str(src / meta["clean"][1]), "st-art",
                            source_kind="original", rights="original")
        con = S.connect(td)
        try:
            from framebound.v2 import domain as D
            S.insert(con, D.CharacterRevision(
                id="char-RR", project_id="p", identity_asset_ids=["id-art"],
                style_asset_ids=["st-art"], view_set=["side"],
                canvas={"width": 64, "height": 64}, scale_ruler="x"))
        finally:
            con.close()
        con = S.connect(td)
        try:
            hashes = {f"f{i}": S.get(con, "assets", f"f{i}")[0]["byte_sha256"] for i in range(8)}
        finally:
            con.close()
        A.propose_motion_guide(td, Actor(type="orchestrator", id="s"),
                               {"schema_version": "2.0", "id": "mg-RR",
                                "character_revision_id": "char-RR",
                                "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                                             "byte_sha256": hashes[f"f{i}"]} for i in range(8)]})
        CT.propose_contract(td, {
            "schema_version": "2.0", "id": "c-RR", "character_revision_id": "char-RR",
            "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
            "canvas": {"width": 64, "height": 64, "units": "native_px"},
            "timing": {"ticks_per_second": 60, "holds": [4] * 8},
            "references": {"identity": "id-art", "style": "st-art",
                           "motion_guide_revision": "mg-RR"},
            "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                               for i in range(8)],
            "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
            "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
        A.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-RR", "mg-RR")
        clips.create_revision(td, "c-RR", "rev-rr-base", [f"f{i}" for i in range(8)],
                              [f"p{i}" for i in range(8)])
        clips.evaluate(td, "rev-rr-base")
        return {}

    def test_offline_records_pending_without_fabrication(self):
        import os
        from framebound.v2 import recorded_run as RR
        with tempfile.TemporaryDirectory() as td:
            self._approved_project(td)
            def _explode(req):
                raise AssertionError("no network from a pending bundle")
            os.environ["MODEL_API_KEY"] = "bogus-key-present"
            try:
                out = RR.run_recorded(td, str(Path(td) / "bundle.json"),
                                      contract_id="c-RR", slot=0,
                                      baseline_revision_id="rev-rr-base",
                                      new_revision_id="rev-rr-gen",
                                      offline=True, transport=_explode)
            finally:
                del os.environ["MODEL_API_KEY"]
            self.assertEqual(out["origin"], "blocked")
            self.assertIn("MODEL_API_KEY", out["blocker"])
            self.assertTrue(out["prepared"]["conditioning_sha256"])
            self.assertFalse((Path(td) / "bundle.json.output.png").exists())
            con = S.connect(td)
            try:
                revs = con.execute("SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"]
            finally:
                con.close()
            self.assertEqual(revs, 1)  # nothing registered, nothing invented

    def test_simulated_run_labels_origin_and_stays_unreviewed(self):
        import base64
        import os as _os
        from framebound.v2 import recorded_run as RR
        with tempfile.TemporaryDirectory() as td:
            self._approved_project(td)
            _os.environ["MODEL_API_KEY"] = "simulated-key"
            self.addCleanup(_os.environ.pop, "MODEL_API_KEY")
            raw = S.blob_path(td, S.get(S.connect(td), "assets", "f0")[0]["byte_sha256"]).read_bytes()
            png_b64 = base64.b64encode(raw).decode()
            seen = []
            def fake(req):
                n = sum(1 for m in req["body"]["input"]
                        for c in m["content"] if c.get("type") == "input_image")
                seen.append({"model": req["body"].get("model"), "n_images": n,
                             "has_prev": "previous_response_id" in req["body"]})
                return {"status": "completed", "id": "resp-sim",
                        "output": [{"type": "image_generation_call", "id": "img-1",
                                    "result": png_b64}], "usage": {"total_tokens": 1}}
            out = RR.run_recorded(td, str(Path(td) / "bundle.json"),
                                  contract_id="c-RR", slot=0,
                                  baseline_revision_id="rev-rr-base",
                                  new_revision_id="rev-rr-gen",
                                  offline=False, transport=fake,
                                  idempotency_key="rr-sim-1")
            self.assertEqual(out["origin"], "provider-simulated")
            self.assertNotEqual(out["origin"], "live")
            self.assertEqual(out["acceptance"], "unreviewed")
            # all four capabilities ran through the controller, each with its
            # own request/response identity
            caps = {c["capability"]: c for c in out["capabilities"]}
            self.assertEqual(set(caps), {"spark-critique", "image-generation",
                                         "image-edit", "sam-segmentation"})
            for name, cap in caps.items():
                self.assertEqual(cap["status"], "recorded", name)
                self.assertTrue(cap["request_artifact"], name)
            gen = [s for s in seen if s["model"] == "muse-image-1.0"
                   and not s["has_prev"]]
            self.assertEqual(len(gen), 1)
            # identity + style + approved phase-guide pixels
            self.assertEqual(gen[0]["n_images"], 3)
            edit = [s for s in seen if s["has_prev"]]
            self.assertEqual(len(edit), 1)
            self.assertTrue((Path(td) / "bundle.json.output.png").is_file())
            con = S.connect(td)
            try:
                decs = [json.loads(r["data"]) for r in
                        con.execute("SELECT data FROM review_events").fetchall()]
            finally:
                con.close()
            self.assertEqual([d for d in decs if d["action"] == "approve"], [])
            # the recorded revision evaluates through the normal gate
            self.assertIn(out["registration"]["technical_status"],
                          ("pass", "fail", "incomplete", "error"))
            self.assertTrue(out["registration"]["packet_id"])
            self.assertTrue(out["generation"]["request_artifact"]
                            and out["generation"]["response_artifact"])


if __name__ == "__main__":
    unittest.main()
