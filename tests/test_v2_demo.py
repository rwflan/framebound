"""WP6 gate: full workflow on original art; no hidden auto-fitting; honest badges."""
import json
import unittest

from framebound.v2 import storage as S
from framebound.v2.demo_wp6 import run_wp6
from framebound.v2.media.timeline import select_slot
from framebound.v2.services import clips
from framebound.v2.services.errors import InvalidInput

import tempfile
from pathlib import Path


class GenuineDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp()
        cls.rep = run_wp6(str(Path(cls.td) / "wp6"))
        cls.proj = str(Path(cls.td) / "wp6" / "project")

    def test_independent_vs_presented_counts(self):
        self.assertEqual(self.rep["clips"], {"run": 8, "jump": 6, "attack": 6, "idle": 4})
        # 24 presented samples; 22 independent drawings (idle_0 == idle_2 by design: subtle
        # idle legitimately preserves its silhouette, documented, not judged by locomotion rules)
        self.assertEqual(self.rep["presented_samples"], 24)
        self.assertEqual(self.rep["independent_drawings"], 22)
        self.assertNotEqual(self.rep["independent_drawings"], self.rep["presented_samples"])

    def test_three_transitions_declared(self):
        self.assertTrue(self.rep["transitions_declared"])
        self.assertEqual(self.rep["transitions"], ["idle-run-01", "run-idle-01", "run-attack-01"])

    def test_evaluations_pass_with_honest_badges(self):
        self.assertTrue(all(s == "pass" for s in self.rep["evaluations"].values()))
        self.assertIn("replay", self.rep["badge"])
        self.assertFalse(self.rep["provider_ledger"]["sent"])
        self.assertEqual(self.rep["provider_ledger"]["mode"], "not_configured")

    def test_interruption_preserves_departure_and_entry(self):
        for intr in self.rep["interruptions"]:
            self.assertEqual(intr["departure_slot"], select_slot([4] * 8, intr["tick"], True))
            self.assertEqual(intr["entry"], "attack:0")
            self.assertTrue(intr["preserved"])

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

    def test_visual_acceptance_separate_from_technical(self):
        con = S.connect(self.proj)
        decs = [json.loads(r["data"]) for r in con.execute("SELECT data FROM review_events").fetchall()]
        con.close()
        approves = [d for d in decs if d["action"] == "approve"]
        self.assertTrue(approves)
        self.assertEqual(approves[0]["clip_revision_id"], "clip-run-01")
        self.assertIn("exact revision", self.rep["decision"])


if __name__ == "__main__":
    unittest.main()
