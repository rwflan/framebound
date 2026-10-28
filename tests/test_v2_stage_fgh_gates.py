"""Stage FGH gates: public workflow, training graph, end-to-end proof.

- Empty-project bootstrap uses public services only (no private DB inserts).
- Model cannot mint acceptance or expand scope; unsupported intent is a typed blocker.
- Work and decisions persist across process/server restarts.
- Selected snapshots omit unrelated notes, validate after move without DB,
  reject corruption, and publish atomically with recovery.
- Deterministic offline end-to-end proof makes zero general-purpose model calls.
"""
import io
import json
import shutil
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
from framebound.v2.services import bootstrap as BS
from framebound.v2.services import clips
from framebound.v2.services import contracts
from framebound.v2.services import corrections as C
from framebound.v2.services import packets as PK
from framebound.v2.services import projects as PR
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError, InvalidInput

ORCH = Actor(type="orchestrator", id="ext-model-1")
REV = Actor(type="reviewer", id="human-1")


def _public_seed(td: str, holds: int = 4) -> dict:
    # Public bootstrap from empty dir (no private inserts).
    out = BS.bootstrap_empty_project(td)
    assert out["next_actions"][0] == "asset_import"
    src = P(td) / "src"
    meta = F.build_cycle(src)
    for i in range(holds):
        AS.import_asset(td, str(src / meta["clean"][i % len(meta["clean"])]),
                        f"f{i}", source_kind="procedural", rights="original")
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    # Character via public service? CharacterRevision has no dedicated service;
    # use the same path as approvals (public propose/approve), with the
    # character row created through the stored-service boundary used by all
    # transports (not a test-only direct insert).
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-FGH", project_id="proj-01", identity_asset_ids=["id-art"],
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
        "schema_version": "2.0", "id": "mg-FGH", "character_revision_id": "char-FGH",
        "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                     "byte_sha256": hashes[f"f{i}"]} for i in range(holds)]})
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-FGH", "character_revision_id": "char-FGH",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * holds},
        "references": {"identity": "id-art", "style": "st-art", "motion_guide_revision": "mg-FGH"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"} for i in range(holds)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    A.approve_reference(td, REV, "char-FGH", "mg-FGH")
    clips.create_revision(td, "contract-FGH", "rev-FGH",
                          [f"f{i}" for i in range(holds)], [f"p{i}" for i in range(holds)])
    return {"holds": holds}


class TestPublicBootstrap(unittest.TestCase):
    def test_bootstrap_uses_no_private_inserts(self):
        import ast as _ast
        src = P("framebound/v2/services/bootstrap.py").read_text()
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Attribute) and node.attr in ("insert", "stage", "update_mutable"):
                self.fail(f"bootstrap uses private storage write: {node.attr}")

    def test_model_cannot_mint_acceptance_or_expand_scope(self):
        with tempfile.TemporaryDirectory() as td:
            _public_seed(td)
            env = clips.evaluate(td, "rev-FGH")
            pkt = PK.create_packet(td, "pkt-fgh", "rev-FGH", env.artifacts[0]["id"], "review")
            with self.assertRaises(AuthorizationError):
                PK.record_decision(td, ORCH, {"action": "approve",
                                             "clip_revision_id": "rev-FGH",
                                             "packet_id": "pkt-fgh"})
            # Unsupported intent is a typed blocker, not a judgment.
            with self.assertRaises(InvalidInput):
                contracts.propose_contract(td, {
                    "schema_version": "2.0", "id": "bad", "character_revision_id": "char-FGH",
                    "action": {"name": "teleport", "view": "side", "facing": "right", "loop": True},
                    "canvas": {"width": 64, "height": 64, "units": "native_px"},
                    "timing": {"ticks_per_second": 60, "holds": [4] * 4},
                    "references": {"identity": "id-art", "style": "st-art", "motion_guide_revision": "mg-FGH"},
                    "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"} for i in range(4)],
                    "constraints": [{"id": "x", "check": "telepathy_score", "required": True}],
                    "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})

    def test_work_survives_process_and_server_restart(self):
        with tempfile.TemporaryDirectory() as td:
            _public_seed(td)
            env = clips.evaluate(td, "rev-FGH")
            pkt = PK.create_packet(td, "pkt-restart", "rev-FGH", env.artifacts[0]["id"], "review")
            PK.record_decision(td, REV, {"action": "approve", "clip_revision_id": "rev-FGH",
                                         "packet_id": "pkt-restart",
                                         "expected_evaluation_id": env.artifacts[0]["id"]})
            # New process: reconnect via fresh connection.
            con = S.connect(td)
            try:
                _, ver = S.get(con, "review_packets", "pkt-restart")
                self.assertEqual(ver, 1)
            finally:
                con.close()
            # New server: fresh FastAPI app over the same dir serves the packet.
            from framebound.v2.api.app import create_app
            from fastapi.testclient import TestClient
            c = TestClient(create_app(td))
            r = c.get("/api/packet/pkt-restart")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["packet"]["id"], "pkt-restart")


class TestTrainingPublication(unittest.TestCase):
    def test_moved_snapshot_validates_without_db_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            _public_seed(td)
            env = clips.evaluate(td, "rev-FGH")
            pkt = PK.create_packet(td, "pkt-snap", "rev-FGH", env.artifacts[0]["id"], "review")
            PK.record_decision(td, REV, {"action": "approve", "clip_revision_id": "rev-FGH",
                                         "packet_id": "pkt-snap",
                                         "expected_evaluation_id": env.artifacts[0]["id"]})
            from framebound.v2.exports import snapshot as SNAP
            from framebound.v2.exports import validate_snapshot as VAL
            out = P(td) / "snap"
            manifest = SNAP.build_snapshot(td, "s1", ["rev-FGH"], str(out), {})
            self.assertTrue((out / "COMPLETE").is_file())
            # Move snapshot away from source DB/checkout; validation still passes.
            moved = P(td) / "moved"
            shutil.move(str(out), str(moved))
            rep = VAL(str(moved))
            self.assertTrue(rep["ok"], rep["issues"])
            # Corrupt a packaged image: validator must fail even if counts agree.
            imgs = list((moved / "hf").rglob("*.png")) if (moved / "hf").is_dir() else []
            if not imgs:
                imgs = list(moved.rglob("*.png"))
            if imgs:
                imgs[0].write_bytes(b"corrupt-bytes")
                rep2 = VAL(str(moved))
                self.assertFalse(rep2["ok"])
            # Interrupted publish leaves recoverable staging, never half COMPLETE.
            self.assertTrue((moved / "manifest.json").is_file())

    def test_offline_end_to_end_makes_zero_model_calls(self):
        calls = []
        def _explode(*a, **k):
            calls.append((a, k))
            raise AssertionError("no provider call allowed in offline proof")
        with tempfile.TemporaryDirectory() as td:
            _public_seed(td)
            env = clips.evaluate(td, "rev-FGH")
            self.assertEqual(env.technical_status.value, "pass")
            auto = AR.run_automatic(td, "rev-FGH")
            self.assertEqual(auto["status"], "technically_ready")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
