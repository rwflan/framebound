"""R2 regressions: fail-closed evaluation, evidence closure, honest measurements.

Each test reproduces an audit probe at the public boundary: missing authority or
inputs must block, never pass; evidence must bind the actual pixels and code.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.checks import evaluate as E
from framebound.v2.checks import fixtures as F
from framebound.v2.services import clips, contracts
from framebound.v2.services.errors import InvalidInput


def _contract(extra=(), holds=8) -> dict:
    cons = [{"id": "registration", "check": "native_registration", "required": True}]
    cons += list(extra)
    return {
        "schema_version": "2.0", "id": "contract-R2", "character_revision_id": "char-01",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * holds},
        "references": {"identity": "a", "style": "b", "motion_guide_revision": "m"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"}
                           for i in range(holds)],
        "constraints": cons,
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}}


def _seed_frames(td: str, holds: int = 8):
    from framebound.v2.services import assets as AS
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    aids = []
    for i in range(holds):
        name = f"f{i}"
        AS.import_asset(td, str(src / meta["clean"][i % len(meta["clean"])]), name,
                        source_kind="procedural", rights="original")
        aids.append(name)
    return aids, meta


class TestFailClosedMatrix(unittest.TestCase):
    def test_required_unknown_check_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(InvalidInput):
                contracts.propose_contract(td, _contract(
                    [{"id": "weird", "check": "invented", "required": True}]))
            # CLI agrees: unknown checks never enter a stored contract
            from framebound.v2 import cli_commands as CC
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(_contract([{"id": "weird", "check": "invented", "required": True}]),
                          fh)
                path = fh.name
            with self.assertRaises(InvalidInput):
                CC.dispatch(SimpleNamespace(cmd="contract-propose", contract=path, project=td))

    def test_required_check_missing_inputs_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract([
                {"id": "slide", "check": "world_sliding", "required": True,
                 "params": {"tol": 2.0}}]))
            clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
            env = clips.evaluate(td, "clip-R2")
            self.assertEqual(env.technical_status, D.TechnicalStatus.INCOMPLETE)
            codes = {i["code"] for i in env.issues}
            self.assertIn("slide", codes)
            # the missing trace is named, not silent
            reasons = " ".join(i["reason"] for i in env.issues if i["code"] == "slide")
            self.assertIn("trace", reasons)

    def test_expected_scope_matrix_cannot_drop_a_frame(self):
        with tempfile.TemporaryDirectory() as td:
            aids, meta = _seed_frames(td)
            contracts.propose_contract(td, _contract())
            contract = D.ClipContractRevision.model_validate(_contract())
            from PIL import Image as _I
            imgs = [_I.open(Path(td) / "src" / m).convert("RGBA") for m in meta["clean"]]
            # one frame for an eight-frame contract: the evaluator refuses, not passes
            with self.assertRaises(InvalidInput):
                E.evaluate_frames(contract, imgs[:1], {})
            # service boundary refuses the truncated revision too
            with self.assertRaises(InvalidInput):
                clips.create_revision(td, "contract-R2", "clip-short", aids[:1], ["p0"])

    def test_silhouette_without_reference_is_unmeasured_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract(
                [{"id": "area", "check": "silhouette_area", "required": True,
                  "params": {"max_fraction": 0.18}}]))
            clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
            env = clips.evaluate(td, "clip-R2")
            self.assertEqual(env.technical_status, D.TechnicalStatus.INCOMPLETE)
            self.assertTrue(any(i["code"] == "area" for i in env.issues))

    def test_retimed_clip_fails_cadence(self):
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract(
                [{"id": "cad", "check": "locked_cadence", "required": True}]))
            contract = D.ClipContractRevision.model_validate(_contract(
                [{"id": "cad", "check": "locked_cadence", "required": True}]))
            from PIL import Image as _I
            frames = [_I.open(Path(td) / "src" / m).convert("RGBA")
                      for m in F.build_cycle(Path(td) / "src")["clean"]]
            ev = E.evaluate_frames(contract, frames, {}, context={"presented_holds": [4] * 7 + [6],
                                                                  "byte_hashes_complete": True})
            cad = [r for r in ev.results if r.constraint_id == "cad"]
            self.assertTrue(cad and all(r.outcome == D.CheckOutcome.FAIL for r in cad))
            self.assertEqual(ev.technical_status, D.TechnicalStatus.FAIL)


class TestEvidenceClosure(unittest.TestCase):
    def _evaluated(self, td: str, ref_kind: str = "clean"):
        from framebound.v2.media.canonical import canonical_pixels
        aids, meta = _seed_frames(td)
        contracts.propose_contract(td, _contract(
            [{"id": "area", "check": "silhouette_area", "required": True,
              "params": {"max_fraction": 0.18}}]))
        clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
        contract = D.ClipContractRevision.model_validate(_contract(
            [{"id": "area", "check": "silhouette_area", "required": True,
              "params": {"max_fraction": 0.18}}]))
        from PIL import Image as _I
        frames = [_I.open(Path(td) / "src" / m).convert("RGBA") for m in meta["clean"]]
        if ref_kind == "clean":
            refs = {i: _I.open(Path(td) / "src" / m).convert("RGBA") for i, m in enumerate(meta["clean"])}
        else:
            refs = {}
            for i, m in enumerate(meta["clean"]):
                img = _I.open(Path(td) / "src" / m).convert("RGBA")
                px = bytearray(canonical_pixels(img))
                for j in range(3, len(px), 4):
                    px[j] = 255
                refs[i] = _I.frombytes("RGBA", img.size, bytes(px))
        return contract, frames, refs

    def test_changed_reference_pixels_change_evidence_and_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            contract, frames, clean_refs = self._evaluated(td, "clean")
        with tempfile.TemporaryDirectory() as td2:
            _, _, opaque_refs = self._evaluated(td2, "opaque")
            ev_clean = E.evaluate_frames(contract, frames, clean_refs,
                                         context={"byte_hashes_complete": True})
            ev_opaque = E.evaluate_frames(contract, frames, opaque_refs,
                                          context={"byte_hashes_complete": True})
            self.assertEqual(ev_clean.technical_status, D.TechnicalStatus.PASS)
            self.assertEqual(ev_opaque.technical_status, D.TechnicalStatus.FAIL)
            self.assertNotEqual(ev_clean.evidence_manifest_sha256,
                                ev_opaque.evidence_manifest_sha256)
            self.assertNotEqual(ev_clean.id, ev_opaque.id)

    def test_repeat_evaluation_returns_same_revision_bound_record(self):
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract())
            clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
            e1 = clips.evaluate(td, "clip-R2")
            e2 = clips.evaluate(td, "clip-R2")
            id1 = e1.artifacts[0]["id"]
            id2 = e2.artifacts[0]["id"]
            self.assertEqual(id1, id2)
            con = S.connect(td)
            try:
                n = con.execute("SELECT COUNT(*) AS n FROM evaluations").fetchone()["n"]
                self.assertEqual(n, 1)
                # the canonical manifest is stored under its own hash
                import json as _j
                row = con.execute("SELECT data FROM evaluations").fetchone()
                sha = _j.loads(row["data"])["evidence_manifest_sha256"]
                self.assertTrue(S.blob_path(td, sha).is_file())
            finally:
                con.close()

    def test_tampered_blob_and_missing_manifest_are_stale(self):
        from framebound.v2.verify import run_verify
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract())
            clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
            clips.evaluate(td, "clip-R2")
            ok = run_verify(td)
            self.assertTrue(ok["ok"], ok["issues"])
            # corrupt a stored blob: verify must flag the hash drift
            con = S.connect(td)
            try:
                row = con.execute("SELECT data FROM assets LIMIT 1").fetchone()
                a = json.loads(row["data"])
            finally:
                con.close()
            blob = S.blob_path(td, a["byte_sha256"])
            raw = blob.read_bytes()
            blob.write_bytes(b"\x00" + raw[1:])
            bad = run_verify(td)
            self.assertFalse(bad["ok"])
            self.assertTrue(any("blob bytes" in i for i in bad["issues"]), bad["issues"])
            # verifying a nonexistent path reports, never materializes a project
            ghost = str(Path(td) / "no-such-project")
            rep = run_verify(ghost)
            self.assertFalse(rep["ok"])
            self.assertFalse(Path(ghost).exists())


class TestHonestMeasurements(unittest.TestCase):
    def test_stance_drift_is_measured_across_the_whole_contact_interval(self):
        from framebound.v2.checks.implementations import check_world_sliding
        # 1 unit per tick for 100 ticks: steps look fine, stance drifts 99 units
        pos = [(float(i), 0.0) for i in range(100)]
        planted = [True] * 100
        r = check_world_sliding("w", "s", pos, planted, 2.0)
        self.assertEqual(r.outcome, D.CheckOutcome.FAIL)
        self.assertGreaterEqual(r.observed_value, 99.0)
        # replanting resets the anchor: two short stances pass
        pos2 = [(float(i % 2), 0.0) for i in range(100)]
        planted2 = [True, True] + [False, False] * 49
        planted2 = (planted2 * 3)[:100]
        r2 = check_world_sliding("w", "s", pos2, planted2, 2.0)
        self.assertEqual(r2.outcome, D.CheckOutcome.PASS)

    def test_loop_pulse_and_wrong_adjacent_phase_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract([
                {"id": "pulse", "check": "local_pulse", "required": True,
                 "params": {"max_delta": 0.01}},
                {"id": "phase", "check": "phase_correspondence", "required": True,
                 "params": {"region": [8, 8, 56, 60], "grid": [6, 6],
                            "alt_slots": [0, 1, 2, 3, 4, 5, 6, 7]}}]))
            clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
            contract = D.ClipContractRevision.model_validate(_contract([
                {"id": "pulse", "check": "local_pulse", "required": True,
                 "params": {"max_delta": 0.01}},
                {"id": "phase", "check": "phase_correspondence", "required": True,
                 "params": {"region": [8, 8, 56, 60], "grid": [6, 6],
                            "alt_slots": [0, 1, 2, 3, 4, 5, 6, 7]}}]))
            from PIL import Image as _I
            frames = [_I.open(Path(td) / "src" / m).convert("RGBA")
                      for m in F.build_cycle(Path(td) / "src")["clean"]]
            refs = {i: f for i, f in enumerate(frames)}
            ev = E.evaluate_frames(contract, frames, refs,
                                   context={"byte_hashes_complete": True})
            # adjacent alternatives are NOT excluded by default anymore
            scopes = {(r.constraint_id, r.scope) for r in ev.results if r.constraint_id == "phase"}
            self.assertTrue(any(s == ("phase", "slot 0") for s in scopes))
            # loop seam pulse item exists for the looped contract
            seam = [r for r in ev.results if r.scope == "slots 7->0 seam"]
            self.assertEqual(len(seam), 1)

    def test_ambiguous_feature_blobs_are_unmeasured(self):
        from framebound.v2.checks.implementations import check_span
        import numpy as np
        w = h = 32
        px = bytearray(w * h * 4)
        gold = (255, 200, 40)
        for x, y in [(5, 5), (6, 5), (25, 25), (26, 25)]:
            i = (y * w + x) * 4
            px[i:i + 4] = bytes([*gold, 255])
        r = check_span("sp", "slot 0", bytes(px), w, h, gold, gold,
                       [0, 0, 32, 32], [0, 0, 32, 32], 10.0, 5.0)
        self.assertEqual(r.outcome, D.CheckOutcome.UNMEASURED)
        self.assertIn("distinct blobs", r.reason)


class TestTransportParity(unittest.TestCase):
    def test_cli_mcp_service_evaluate_same_fixture_identically(self):
        import asyncio
        with tempfile.TemporaryDirectory() as td:
            aids, _ = _seed_frames(td)
            contracts.propose_contract(td, _contract())
            clips.create_revision(td, "contract-R2", "clip-R2", aids, [f"p{i}" for i in range(8)])
            svc = clips.evaluate(td, "clip-R2")
            from framebound.v2 import cli_commands as CC
            cli = CC.dispatch(SimpleNamespace(cmd="clip-evaluate", revision_id="clip-R2",
                                              project=td))

            async def mcp():
                import sys as _sys
                from mcp.client.stdio import StdioServerParameters, stdio_client
                from mcp.client.session import ClientSession
                params = StdioServerParameters(command=_sys.executable,
                                               args=["-m", "framebound", "v2-mcp", "--project", td])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        return await session.call_tool("clip_evaluate",
                                                       {"revision_id": "clip-R2"})
            res = asyncio.run(mcp())
            self.assertFalse(getattr(res, "is_error", False), res.content)
            import json as _j
            mcp_env = _j.loads(res.content[0].text)
            self.assertEqual(svc.artifacts[0]["id"], cli["artifacts"][0]["id"])
            self.assertEqual(svc.artifacts[0]["id"], mcp_env["artifacts"][0]["id"])
            self.assertEqual(svc.technical_status, cli["technical_status"])
            self.assertEqual(svc.technical_status, mcp_env["technical_status"])


if __name__ == "__main__":
    unittest.main()
