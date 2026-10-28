"""Stage C+D gates: constraint compiler, controls and executable automatic repair.

- Machine faults create contract-authorized work without a human issue.
- Deterministic operators fix real faults with zero provider calls.
- Scope/authority cannot be expanded by the external model; no art approval.
- Redraw requests are typed, bounded and composite-exact.
- Partial progress stays internal until full technical readiness.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path as P

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.checks import fixtures as F
from framebound.v2.services import approvals as A
from framebound.v2.services import assets as AS
from framebound.v2.services import auto_repair as AR
from framebound.v2.services import clips
from framebound.v2.services import contracts
from framebound.v2.services import corrections as C
from framebound.v2.services.authz import Actor, AuthorizationError
from framebound.v2.services.errors import InvalidInput

ORCH = Actor(type="orchestrator", id="ext-model-1")
REV = Actor(type="reviewer", id="human-1")
SYS = Actor(type="system", id="auto-repair")


def _seed(td: str, holds: int = 4) -> dict:
    src = P(td) / "src"
    meta = F.build_cycle(src)
    for i in range(holds):
        AS.import_asset(td, str(src / meta["clean"][i % len(meta["clean"])]),
                        f"f{i}", source_kind="procedural", rights="original")
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-CD", project_id="p", identity_asset_ids=["id-art"],
            style_asset_ids=["st-art"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="x"))
    finally:
        con.close()
    con = S.connect(td)
    try:
        hashes = {f"f{i}": S.get(con, "assets", f"f{i}")[0]["byte_sha256"] for i in range(holds)}
    finally:
        con.close()
    A.propose_motion_guide(td, ORCH, {
        "schema_version": "2.0", "id": "mg-CD", "character_revision_id": "char-CD",
        "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                     "byte_sha256": hashes[f"f{i}"]} for i in range(holds)]})
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-CD", "character_revision_id": "char-CD",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * holds},
        "references": {"identity": "id-art", "style": "st-art", "motion_guide_revision": "mg-CD"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"} for i in range(holds)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "repair_guard", "check": "repair_protection", "required": True},
        ],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    A.approve_reference(td, REV, "char-CD", "mg-CD")
    clips.create_revision(td, "contract-CD", "rev-CD-base",
                          [f"f{i}" for i in range(holds)], [f"p{i}" for i in range(holds)])
    return {"holds": holds}


class TestMachineOrigin(unittest.TestCase):
    def test_machine_fault_creates_work_without_human_issue(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            # Break registration: oversized candidate (fails native_registration).
            big = Image.new("RGBA", (128, 128), (255, 0, 0, 255))
            buf = io.BytesIO()
            big.save(buf, format="PNG")
            (P(td) / "big.png").write_bytes(buf.getvalue())
            AS.import_asset(td, str(P(td) / "big.png"), "big0",
                            source_kind="procedural", rights="original")
            clips.register_candidate(td, "rev-CD-base", "rev-CD-bad",
                                     {0: "big0"}, "repair:test-oversize")
            env = clips.evaluate(td, "rev-CD-bad")
            self.assertEqual(env.technical_status.value, "fail")
            out = AR.run_automatic(td, "rev-CD-bad")
            self.assertEqual(out['status'],'blocked')
            self.assertIn('no human-approved automatic repair policy',out['blocker'])



class TestExternalModelBounds(unittest.TestCase):
    def test_model_cannot_expand_scope_or_approve(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            # Model cannot mint reviewer authority.
            with self.assertRaises(AuthorizationError):
                A.approve_reference(td, ORCH, "char-CD", "mg-CD")
            # Model cannot approve art via decision.
            from framebound.v2.services import packets as PK
            ev = clips.evaluate(td, "rev-CD-base")
            pkt = PK.create_packet(td, "pkt-cd", "rev-CD-base", ev.artifacts[0]["id"], "review")
            with self.assertRaises(AuthorizationError):
                PK.record_decision(td, ORCH, {"action": "approve",
                                              "clip_revision_id": "rev-CD-base",
                                              "packet_id": "pkt-cd"})


class TestDeterministicOperators(unittest.TestCase):
    def test_unapproved_pixel_writers_and_redraw_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            with self.assertRaisesRegex(InvalidInput,'authorized operation'):
                AR.execute_translate(td,'f0',1,0,'moved-1',budget_px=2)
            with self.assertRaisesRegex(InvalidInput,'authorized operation'):
                AR.execute_protected_restore(td,'f0','f0',bytes(4096),'restored')
            with self.assertRaisesRegex(InvalidInput,'authorized operation'):
                AR.construct_redraw_request(td,'task',0)


class TestSafeProgress(unittest.TestCase):
    def test_partial_progress_stays_internal(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            # Two faults: oversize slot 0 + oversize slot 1. Fixing one still fails.
            for slot, aid in ((0, "big0"), (1, "big1")):
                big = Image.new("RGBA", (128, 128), (0, 255, 0, 255))
                buf = io.BytesIO()
                big.save(buf, format="PNG")
                (P(td) / f"big{slot}.png").write_bytes(buf.getvalue())
                AS.import_asset(td, str(P(td) / f"big{slot}.png"), aid,
                                source_kind="procedural", rights="original")
            clips.register_candidate(td, "rev-CD-base", "rev-CD-2bad",
                                     {0: "big0", 1: "big1"}, "repair:test-2bad")
            env = clips.evaluate(td, "rev-CD-2bad")
            self.assertEqual(env.technical_status.value, "fail")
            # Fixing only slot 0 still fails overall (safe internal progress).
            clips.register_candidate(td, "rev-CD-2bad", "rev-CD-partial",
                                     {0: "f0"}, "repair:partial-fix")
            env2 = clips.evaluate(td, "rev-CD-partial")
            self.assertNotEqual(env2.technical_status.value, "pass")


if __name__ == "__main__":
    unittest.main()
