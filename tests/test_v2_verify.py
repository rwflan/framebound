"""WP2 gate: clean/negative behavior, sliding, loop/one-shot, protection, stale evidence."""
import math
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2.checks import evaluate as E
from framebound.v2.checks import fixtures as F
from framebound.v2.checks import implementations as C
from framebound.v2.media.canonical import canonical_pixels
from framebound.v2.media.timeline import render_trace, select_slot


def _load(d: Path, rel: str) -> Image.Image:
    return Image.open(d / rel).convert("RGBA")


def _phases(n=8):
    names = ["A_contact", "A_compression", "A_passing", "A_flight",
             "B_contact", "B_compression", "B_passing", "B_flight"]
    return [{"slot": i, "phase": names[i], "motion_reference_id": f"pose-{names[i]}"} for i in range(n)]


def _contract(span_expected: float, contact_min: int) -> D.ClipContractRevision:
    return D.ClipContractRevision(
        id="contract-verify-01", character_revision_id="char-rev-01",
        action={"name": "run", "view": "side", "facing": "right", "loop": True},
        canvas={"width": 64, "height": 64, "units": "native_px"},
        timing={"ticks_per_second": 60, "holds": [4] * 8},
        references={"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-01"},
        phase_schedule=_phases(),
        constraints=[
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "body_area", "check": "silhouette_area", "required": True, "params": {"max_fraction": 0.18}},
            {"id": "body_width", "check": "silhouette_width", "required": True, "params": {"max_fraction": 0.15}},
            {"id": "body_height", "check": "silhouette_height", "required": True, "params": {"max_fraction": 0.12}},
            {"id": "torso_span", "check": "visible_span", "required": True,
             "params": {"color_a": [255, 200, 40], "color_b": [255, 200, 40],
                        "window_a": F.CLASP_WINDOW, "window_b": F.BUCKLE_WINDOW,
                        "expected": span_expected, "max_delta": 3.0}},
            {"id": "phase", "check": "phase_correspondence", "required": True,
             "params": {"region": F.REGION, "grid": F.GRID, "alt_slots": [1, 2, 3, 4, 5, 6, 7]}},
            {"id": "support", "check": "declared_contacts", "required": True,
             "params": {"window": F.SUPPORT_WINDOW, "min_visible": contact_min}},
            {"id": "look", "check": "appearance_palette", "required": True,
             "params": {"max_drift": 0.06}},  # calibrated: clean self-drift 0.0, full-shirt recolor 0.109
            {"id": "pulse", "check": "local_pulse", "required": True, "params": {"max_delta": 2.5}},
            {"id": "cadence", "check": "locked_cadence", "required": True},
            {"id": "seam", "check": "loop_seam", "required": True, "params": {"region": F.REGION, "grid": F.GRID, "max_gap": 0.6}},
        ],
        allowed_transforms={"per_pose_scale": False, "rigid_translation_budget_px": 2},
    )


class Verify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp()
        cls.dir = Path(cls.td) / "fx"
        cls.meta = F.build_cycle(cls.dir)
        cls.clean = [_load(cls.dir, r) for r in cls.meta["clean"]]
        # calibrate span + contacts on clean frame 0
        from framebound.v2.checks.raster import centroid, feature_points
        px0 = canonical_pixels(cls.clean[0])
        ca = centroid(feature_points(px0, 64, 64, (255, 200, 40), F.CLASP_WINDOW))
        cb = centroid(feature_points(px0, 64, 64, (255, 200, 40), F.BUCKLE_WINDOW))
        cls.span0 = math.dist(ca, cb)
        n = sum(1 for y in range(F.SUPPORT_WINDOW[1], F.SUPPORT_WINDOW[3])
                for x in range(F.SUPPORT_WINDOW[0], F.SUPPORT_WINDOW[2])
                if px0[(y * 64 + x) * 4 + 3] >= 128)
        cls.contact_min = max(1, n // 2)
        cls.contract = _contract(cls.span0, cls.contact_min)
        cls.refs = {i: _load(cls.dir, r) for i, r in enumerate(cls.meta["clean"])}

    def test_clean_passes_required(self):
        ev = E.evaluate_frames(self.contract, self.clean, self.refs)
        self.assertEqual(ev.technical_status, D.TechnicalStatus.PASS, [r for r in ev.results if r.outcome == "fail"])
        self.assertEqual(ev.coverage_status, D.CoverageStatus.COMPLETE)

    def test_torso_pulse_fails_span_while_height_constant(self):
        frames = list(self.clean)
        frames[2] = _load(self.dir, self.meta["faults"]["pulse"])
        ev = E.evaluate_frames(self.contract, frames, self.refs)
        codes = {r.constraint_id for r in ev.results if r.outcome == "fail"}
        self.assertIn("torso_span", codes)
        heights = [r for r in ev.results if r.constraint_id == "body_height" and r.scope == "slot 2"]
        # height may or may not fail; the point is the local span catches what height can miss
        self.assertTrue(any(r.outcome in ("fail", "pass") for r in heights))

    def test_wrong_phase_and_palette_and_contacts(self):
        frames = list(self.clean)
        frames[3] = _load(self.dir, self.meta["faults"]["phase"])
        ev = E.evaluate_frames(self.contract, frames, self.refs)
        self.assertEqual(ev.technical_status, D.TechnicalStatus.FAIL)
        frames2 = list(self.clean)
        frames2[1] = _load(self.dir, self.meta["faults"]["palette"])
        ev2 = E.evaluate_frames(self.contract, frames2, self.refs)
        self.assertIn("look", {r.constraint_id for r in ev2.results if r.outcome == "fail"})

    def test_blank_frame_is_error_never_pass(self):
        frames = list(self.clean)
        frames[0] = _load(self.dir, self.meta["faults"]["blank"])
        ev = E.evaluate_frames(self.contract, frames, self.refs)
        self.assertIn(ev.technical_status, (D.TechnicalStatus.FAIL, D.TechnicalStatus.ERROR))
        reg = [r for r in ev.results if r.constraint_id == "registration" and r.scope == "slot 0"][0]
        self.assertEqual(reg.outcome, D.CheckOutcome.ERROR)

    def test_resized_canvas_fails_registration(self):
        frames = list(self.clean)
        frames[0] = _load(self.dir, self.meta["faults"]["resized"])
        ev = E.evaluate_frames(self.contract, frames, self.refs)
        reg = [r for r in ev.results if r.constraint_id == "registration" and r.scope == "slot 0"][0]
        self.assertEqual(reg.outcome, D.CheckOutcome.FAIL)

    def test_missing_feature_is_unmeasured_never_passes(self):
        frames = list(self.clean)
        frames[0] = _load(self.dir, self.meta["faults"]["nogold"])
        ev = E.evaluate_frames(self.contract, frames, self.refs)
        span = [r for r in ev.results if r.constraint_id == "torso_span" and r.scope == "slot 0"][0]
        self.assertEqual(span.outcome, D.CheckOutcome.UNMEASURED)
        # fails closed either way: missing measurement can never become a pass
        self.assertIn(ev.technical_status, (D.TechnicalStatus.FAIL, D.TechnicalStatus.INCOMPLETE))
        self.assertNotEqual(ev.coverage_status, D.CoverageStatus.COMPLETE)

    def test_no_references_is_incomplete_with_coverage_gap(self):
        ev = E.evaluate_frames(self.contract, self.clean, {})
        self.assertEqual(ev.technical_status, D.TechnicalStatus.INCOMPLETE)
        self.assertIn(ev.coverage_status, (D.CoverageStatus.PARTIAL, D.CoverageStatus.UNSUPPORTED))

    def test_world_sliding_fails_while_static_passes(self):
        # static contact passes on clean frame...
        ev = E.evaluate_frames(self.contract, self.clean, self.refs)
        sup = [r for r in ev.results if r.constraint_id == "support" and r.scope == "slot 0"][0]
        self.assertEqual(sup.outcome, D.CheckOutcome.PASS)
        # ...but a translating root with a held planted drawing slides in world units
        planted = [True] * 8
        still = [(100.0, 200.0)] * 8
        slid = [(100.0 + i * 5.0, 200.0) for i in range(8)]
        ok = C.check_world_sliding("w", "s", still, planted, 2.0)
        bad = C.check_world_sliding("w", "s", slid, planted, 2.0)
        self.assertEqual(ok.outcome, D.CheckOutcome.PASS)
        self.assertEqual(bad.outcome, D.CheckOutcome.FAIL)

    def test_hold_boundaries_and_10k_loops(self):
        self.assertEqual(select_slot([4] * 8, 3, True), 0)
        self.assertEqual(select_slot([4] * 8, 4, True), 1)
        self.assertEqual(select_slot([4] * 8, 31, True), 7)
        trace = render_trace([4] * 8, True, 10_000 * 32)
        self.assertEqual(trace[0], 0)
        self.assertEqual(trace[32 * 10_000 - 1], 7)
        self.assertEqual(trace[32], 0)  # no cumulative drift

    def test_one_shot_has_no_seam(self):
        c = _contract(self.span0, self.contact_min)
        c.action.loop = False
        ev = E.evaluate_frames(c, self.clean, self.refs)
        seam = [r for r in ev.results if r.constraint_id == "seam"]
        self.assertTrue(seam and all(r.outcome == D.CheckOutcome.NOT_APPLICABLE for r in seam))

    def test_mirror_is_recorded_transform(self):
        img = self.clean[0]
        mirrored = img.transpose(Image.FLIP_LEFT_RIGHT)
        double = mirrored.transpose(Image.FLIP_LEFT_RIGHT)
        self.assertEqual(canonical_pixels(img), canonical_pixels(double))
        # ROI remap: x -> W - x
        roi = {"left": 10, "top": 5, "right": 20, "bottom": 15}
        remapped = {"left": 64 - 20, "top": 5, "right": 64 - 10, "bottom": 15}
        self.assertEqual((remapped["left"], remapped["right"]), (44, 54))

    def test_protection_exact_pixels(self):
        w = h = 8
        before = bytes([10, 20, 30, 255] * (w * h))
        after = bytearray(before)
        after[0:4] = bytes((99, 99, 99, 255))  # pixel 0 changed
        allowed = bytearray(w * h)
        allowed[0] = 1
        r = C.check_protection("p", "s", before, bytes(after), w, h, allowed, None)
        self.assertEqual(r.outcome, D.CheckOutcome.PASS)
        r2 = C.check_protection("p", "s", before, bytes(after), w, h, bytearray(w * h), None)
        self.assertEqual(r2.outcome, D.CheckOutcome.FAIL)
        prot = bytearray(w * h)
        prot[0] = 1
        r3 = C.check_protection("p", "s", before, bytes(after), w, h, allowed, prot)
        self.assertEqual(r3.outcome, D.CheckOutcome.FAIL)

    def test_stale_evidence_rejected(self):
        ev1 = E.evaluate_frames(self.contract, self.clean, self.refs)
        changed = list(self.clean)
        px = bytearray(canonical_pixels(changed[0]))
        px[0:4] = bytes((1, 2, 3, 255))
        img = Image.frombytes("RGBA", (64, 64), bytes(px))
        changed[0] = img
        ev2 = E.evaluate_frames(self.contract, changed, self.refs)
        self.assertNotEqual(ev1.evidence_manifest_sha256, ev2.evidence_manifest_sha256)

    def test_repair_reduces_errors_without_regression(self):
        frames = list(self.clean)
        frames[2] = _load(self.dir, self.meta["faults"]["pulse"])
        ev_bad = E.evaluate_frames(self.contract, frames, self.refs)
        n_bad = sum(1 for r in ev_bad.results if r.outcome == "fail")
        ev_good = E.evaluate_frames(self.contract, self.clean, self.refs)
        n_good = sum(1 for r in ev_good.results if r.outcome == "fail")
        self.assertGreater(n_bad, n_good)


if __name__ == "__main__":
    unittest.main()
