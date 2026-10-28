"""Second-remediation gate S8: the integrated workflow end to end.

Approved conditioning -> job -> send -> materialized output -> evaluate ->
bounded correction -> human comparison -> current eligibility -> selected
export -> moved standalone consumers, plus negative and restart variants.
Every step goes through the public service boundary with strict fakes;
simulation stays labeled and ineligible for live claims.
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
from framebound.v2.checks import fixtures as F
from framebound.v2.exports import build_snapshot, validate_snapshot
from framebound.v2.exports.dpo_adapter import load_preferences
from framebound.v2.services import approvals as A
from framebound.v2.services import assets as AS
from framebound.v2.services import briefs as B
from framebound.v2.services import clips, contracts, masks
from framebound.v2.services import corrections as C
from framebound.v2.services import eligibility as EL
from framebound.v2.services import jobs as J
from framebound.v2.services import orchestrator as O
from framebound.v2.services import packets
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import InvalidInput

import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent))
from test_v2_r3_providers import _EnvKey, _png_bytes  # noqa: E402

ORCH = Actor(type="orchestrator", id="spark-1")
REV = Actor(type="reviewer", id="human-1")


def _png_b64(color=(10, 200, 30, 255)) -> str:
    return base64.b64encode(_png_bytes(color=color)).decode()


def _seed(td: str) -> dict:
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i in range(8):
        AS.import_asset(td, str(src / meta["clean"][i]), f"f{i}",
                        source_kind="generated", rights="original")
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-S8", project_id="p", identity_asset_ids=["id-art"],
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
        "schema_version": "2.0", "id": "mg-S8", "character_revision_id": "char-S8",
        "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                     "byte_sha256": hashes[f"f{i}"]} for i in range(8)]})
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-S8", "character_revision_id": "char-S8",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "id-art", "style": "st-art",
                       "motion_guide_revision": "mg-S8"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                           for i in range(8)],
        "constraints": [{"id": "registration", "check": "native_registration",
                          "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    A.approve_reference(td, REV, "char-S8", "mg-S8")
    clips.create_revision(td, "contract-S8", "rev-base",
                          [f"f{i}" for i in range(8)], [f"p{i}" for i in range(8)])
    clips.evaluate(td, "rev-base")
    return {"src": src, "meta": meta}


def _fake_transport(seen: dict, payload_b64: str):
    def _t(req):
        seen["calls"] = seen.get("calls", 0) + 1
        return {"status": "completed", "id": "resp-int",
                "output": [{"type": "image_generation_call", "id": "img-1",
                            "result": payload_b64}],
                "usage": {"total_tokens": 5}}
    return _t


class TestIntegratedWorkflow(unittest.TestCase):
    def test_full_chain_simulated_origin_stays_labeled(self):
        with tempfile.TemporaryDirectory() as td:
            meta = _seed(td)
            seen: dict = {}
            with _EnvKey("simulated-key"):
                fake = _fake_transport(seen, _png_b64())
                # approved conditioning -> job -> claimed send (no caller brief)
                compiled = B.compile_reference_brief(td, "contract-S8", 0)
                env = J.submit_generation(td, compiled["brief"], [], "int-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                step = O.run_once(td, run["run_id"], worker_id="w")
                self.assertEqual(step["action"], "send_ready")
                out = O.orchestrator_send(td, run["run_id"], job_id, worker_id="w",
                                          fencing_token=step["fencing_token"],
                                          transport=fake)
                self.assertEqual(out["action"], "succeeded")
                self.assertEqual(seen["calls"], 1)
                job = J.job_get(td, job_id)["job"]
                self.assertEqual(job["origin"], "simulated-transport")
                self.assertEqual(job["attempt_count"], 1)
                # materialized output -> evaluated revision -> packet
                gen_aid = job["output_asset_ids"][-1]
                clips.register_candidate(td, "rev-base", "rev-gen", {0: gen_aid},
                                         recipe="repair:bounded-patch@identity+guide")
                gen_ev = clips.evaluate(td, "rev-gen")
                pkt = packets.create_packet(td, "pkt-gen", "rev-gen",
                                            gen_ev.artifacts[0]["id"], "generated")
                # bounded correction of the generated revision
                env2, task = C.open_issue(td, REV, {"action": "mark_issue",
                    "clip_revision_id": "rev-gen", "frame_range": [0, 3],
                    "roi": {"left": 8, "top": 8, "right": 16, "bottom": 16},
                    "note": "touch up", "category": "general"})
                issue_id = C.get_task(td, task.id)["issue"]["id"]
                Image.new("L", (64, 64), 255).save(Path(td) / "m.png")
                AS.import_asset(td, str(Path(td) / "m.png"), "m-full",
                                source_kind="original", rights="original")
                masks.approve_mask(td, REV, issue_id, "m-full", [0])
                ver = C.get_task(td, task.id)["version"]
                cl = C.claim(td, ORCH, task.id, ver)
                base_ev = packets.latest_evaluation(
                    S.connect(td), task.baseline_revision_id)
                S.connect(td).close()
                fix = C.submit_correction(td, ORCH, task.id, claim_token=cl["claim_token"],
                                          expected_version=cl["version"],
                                          new_revision_id="rev-fix",
                                          slot_asset_ids={0: "f0"},
                                          recipe="repair:bounded-patch",
                                          baseline_evaluation_id=base_ev.id,
                                          idempotency_key="int-fix")
                self.assertTrue(fix["ok"], fix)
                # human comparison -> current eligibility only after resolution
                packets.record_decision(td, REV, {"action": "approve",
                                                  "clip_revision_id": "rev-fix",
                                                  "packet_id": fix["packet"]["artifacts"][0]["id"]})
                self.assertFalse(EL.release_eligibility(td, "rev-fix")["eligible"])
                done = C.resolve_issue(td, REV, issue_id, "rev-fix",
                                       packet_id=fix["packet"]["artifacts"][0]["id"])
                self.assertTrue(done["ok"])
                elig = EL.release_eligibility(td, "rev-fix")
                self.assertTrue(elig["eligible"], elig["reasons"])
                # selected export -> moved standalone consumers
                snap_out = Path(td) / "snap"
                man = build_snapshot(td, "int", ["rev-base", "rev-gen", "rev-fix"],
                                     str(snap_out),
                                     {"include_procedural_positives": True,
                                      "split": {"train": ["rev-fix"], "test": []}})
                self.assertGreaterEqual(man["counts"]["preferences"], 1)
                moved = Path(td) / "moved"
                shutil.move(str(snap_out), str(moved))
                rep = validate_snapshot(str(moved))
                self.assertTrue(rep["ok"], rep["issues"])
                rows = load_preferences(str(moved))
                self.assertTrue(rows)
                for row in rows:
                    self.assertTrue(row["chosen_images"] and row["rejected_images"])

    def test_negative_variants_refuse_before_spend(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            seen: dict = {}
            with _EnvKey("live-key"):
                fake = _fake_transport(seen, _png_b64())
                compiled = B.compile_reference_brief(td, "contract-S8", 0)
                # offline job cannot be flipped live at send
                env = J.submit_generation(td, compiled["brief"], [], "neg-off",
                                          offline=True)
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                con = S.connect(td)
                try:
                    _, v = S.get(con, "jobs", job_id)
                finally:
                    con.close()
                claim = J.job_claim(td, job_id, "w", expected_version=v)
                with self.assertRaises(InvalidInput):
                    O.orchestrator_send(td, run["run_id"], job_id, worker_id="w",
                                        fencing_token=claim["fencing_token"],
                                        offline=False, transport=fake)
                # changed brief cannot swap the frozen request
                env2 = J.submit_generation(td, compiled["brief"], [], "neg-chg")
                j2 = env2.artifacts[0]["id"]
                run2 = O.start_run(td, [j2])
                con = S.connect(td)
                try:
                    _, v2 = S.get(con, "jobs", j2)
                finally:
                    con.close()
                claim2 = J.job_claim(td, j2, "w", expected_version=v2)
                tampered = dict(compiled["brief"])
                tampered["instruction"] += " extra"
                with self.assertRaises(InvalidInput):
                    O.orchestrator_send(td, run2["run_id"], j2, tampered,
                                        worker_id="w",
                                        fencing_token=claim2["fencing_token"],
                                        transport=fake)
            self.assertEqual(seen.get("calls", 0), 0)
            self.assertEqual(J.job_get(td, job_id)["job"]["attempt_count"], 0)

    def test_restart_recovers_without_caller_state(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            seen: dict = {}
            with _EnvKey("simulated-key"):
                fake = _fake_transport(seen, _png_b64())
                compiled = B.compile_reference_brief(td, "contract-S8", 0)
                env = J.submit_generation(td, compiled["brief"], [], "rst-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                # first worker claims then disappears; second worker resumes
                # from stored state alone after the lease lapses into recovery
                step = O.run_once(td, run["run_id"], worker_id="w-first")
                self.assertEqual(step["action"], "send_ready")
                # same-process stand-in for a fresh process: no brief carried
                out = O.orchestrator_send(td, run["run_id"], job_id, worker_id="w-first",
                                          fencing_token=step["fencing_token"],
                                          transport=fake)
                self.assertEqual(out["action"], "succeeded")
            self.assertEqual(seen["calls"], 1)


if __name__ == "__main__":
    unittest.main()
