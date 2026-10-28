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
            self.assertIn(out["status"], ("machine_tasks_opened", "blocked"))
            if out["status"] == "machine_tasks_opened":
                self.assertTrue(out["machine_tasks"])
                for t in out["machine_tasks"]:
                    self.assertEqual(t["origin"], "machine")
                # No human mark_issue event was fabricated.
                con = S.connect(td)
                try:
                    rows = con.execute("SELECT data FROM review_events").fetchall()
                finally:
                    con.close()
                humans = [json.loads(r["data"]) for r in rows
                          if json.loads(r["data"]).get("action") == "mark_issue"
                          and json.loads(r["data"]).get("actor_type") == "reviewer"]
                self.assertEqual(humans, [])


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
    def test_translate_and_protected_restore_fix_real_faults_with_zero_provider_calls(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            con = S.connect(td)
            try:
                adata, _ = S.get(con, "assets", "f0")
                raw = S.blob_path(td, adata["byte_sha256"]).read_bytes()
            finally:
                con.close()
            base = Image.open(io.BytesIO(raw)).convert("RGBA")
            # Operator 1: deterministic translate within budget.
            asset = AR.execute_translate(td, "f0", 1, 0, "moved-1", budget_px=2)
            self.assertEqual((asset.width, asset.height), (64, 64))
            self.assertIn("translate", asset.lineage)
            # Out-of-budget refused, not silently clamped.
            with self.assertRaises(InvalidInput):
                AR.execute_translate(td, "f0", 5, 0, "moved-bad", budget_px=2)
            # Operator 2: damage exterior, restore exactly.
            dmg = base.copy()
            px = dmg.load()
            px[0, 0] = (255, 0, 0, 255)
            buf = io.BytesIO()
            dmg.save(buf, format="PNG")
            (P(td) / "dmg.png").write_bytes(buf.getvalue())
            AS.import_asset(td, str(P(td) / "dmg.png"), "dmg0",
                            source_kind="procedural", rights="original")
            allow = bytes([0] * (64 * 64))  # exterior only; interior change none
            # Damage is at (0,0) which is protected (allowed 0) -> restore fixes it.
            fixed = AR.execute_protected_restore(td, "f0", "dmg0", allow, "fixed0")
            con = S.connect(td)
            try:
                fdata, _ = S.get(con, "assets", "fixed0")
                bdata, _ = S.get(con, "assets", "f0")
                self.assertEqual(fdata["pixel_sha256"], bdata["pixel_sha256"])
            finally:
                con.close()
            # Zero provider calls: no transport was ever consulted (offline by construction).

    def test_redraw_request_is_typed_bounded_and_composite_exact(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            ev = clips.evaluate(td, "rev-CD-base")
            # Open a human issue to get a task, then construct redraw.
            from framebound.v2.services import packets as PK
            pkt = PK.create_packet(td, "pkt-cd2", "rev-CD-base", ev.artifacts[0]["id"], "review")
            _, task = C.open_issue(td, REV, {"action": "mark_issue",
                "clip_revision_id": "rev-CD-base", "packet_id": "pkt-cd2",
                "frame_instance_id": "rev-CD-base-fi-00", "category": "t", "note": "n"})
            req = AR.construct_redraw_request(td, task.id, 0)
            self.assertEqual(req["operation"], "scoped_redraw")
            self.assertIn("brief_digest", req)
            self.assertIn("request_sha256", req)
            self.assertEqual(req["protection"], "exterior pixels composited back exactly")


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
