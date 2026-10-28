"""R6 regressions: comparison timing, deterministic media, restart-safe state."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from framebound.v2.api.app import create_app
from framebound.v2.checks import fixtures as F
from framebound.v2.services import assets, clips, contracts, packets
from framebound.v2.services.authz import Actor

REV = Actor(type="reviewer", id="human-1")


def _contract(cid: str, holds: list[int]) -> dict:
    return {
        "schema_version": "2.0", "id": cid, "character_revision_id": "char-6",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": holds},
        "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"} for i in range(len(holds))],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
    }


def _seed(td: str) -> dict:
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        assets.import_asset(td, str(src / rel), f"f{i}", source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][0]), "a-id", source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][1]), "a-st", source_kind="procedural")
    contracts.propose_contract(td, _contract("c-8", [4] * 8))
    clips.create_revision(td, "c-8", "rev-a", [f"f{i}" for i in range(8)],
                          [f"p{i}" for i in range(8)])
    eva = clips.evaluate(td, "rev-a")
    packets.create_packet(td, "pkt-a", "rev-a", eva.artifacts[0]["id"], "review")
    return {"ev": eva.artifacts[0]["id"]}


class DeskMedia(unittest.TestCase):
    def test_compare_same_contract_equal_timing(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            c = TestClient(create_app(td))
            r = c.get("/api/compare", params={"base": "rev-a", "other": "rev-a"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertTrue(body["timing_equal"])
            self.assertIn("frame index equality", body["timing_note"])
            self.assertEqual(len(body["base"]["frames"]), 8)
            self.assertTrue(all(f["asset_url"].endswith(f["asset_id"]) for f in body["base"]["frames"]))

    def test_compare_retimed_contract_maps_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            contracts.propose_contract(td, _contract("c-4", [4] * 4))
            clips.create_revision(td, "c-4", "rev-short", [f"f{i}" for i in range(4)],
                                  [f"p{i}" for i in range(4)])
            clips.evaluate(td, "rev-short")
            c = TestClient(create_app(td))
            r = c.get("/api/compare", params={"base": "rev-a", "other": "rev-short"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertFalse(r.json()["timing_equal"])
            self.assertIn("RETIMED", r.json()["timing_note"])
            # different action/view is not comparable
            bad = dict(_contract("c-x", [4] * 8))
            bad["action"]["name"] = "jump"
            bad["phase_schedule"] = [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"} for i in range(8)]
            contracts.propose_contract(td, bad)
            clips.create_revision(td, "c-x", "rev-x", [f"f{i}" for i in range(8)],
                                  [f"p{i}" for i in range(8)])
            clips.evaluate(td, "rev-x")
            r2 = c.get("/api/compare", params={"base": "rev-a", "other": "rev-x"})
            self.assertEqual(r2.status_code, 422)

    def test_contact_sheet_deterministic_across_calls_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            c = TestClient(create_app(td))
            a = c.get("/api/packet/pkt-a/contact-sheet")
            self.assertEqual(a.status_code, 200)
            h1 = hashlib.sha256(a.content).hexdigest()
            self.assertEqual(a.headers["x-revision-id"], "rev-a")
            # brand-new app instance over the same project dir
            c2 = TestClient(create_app(td))
            b = c2.get("/api/packet/pkt-a/contact-sheet")
            self.assertEqual(hashlib.sha256(b.content).hexdigest(), h1)
            img = Image.open(io.BytesIO(b.content))
            self.assertEqual(img.size, (4 * 64, 2 * 64))

    def test_preview_deterministic_or_clear_501(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            c = TestClient(create_app(td))
            r = c.post("/api/packet/pkt-a/preview")
            if shutil.which("ffmpeg") is None:
                self.assertEqual(r.status_code, 501)
                return
            self.assertEqual(r.status_code, 201, r.text)
            body = r.json()
            self.assertEqual(body["frames"], 32)
            self.assertIn("ffmpeg", body["ffmpeg_command"])
            v1 = c.get("/api/previews/pkt-a.mp4")
            self.assertEqual(v1.status_code, 200)
            h1 = hashlib.sha256(v1.content).hexdigest()
            self.assertEqual(h1, body["content_sha256"])
            r2 = c.post("/api/packet/pkt-a/preview")
            self.assertEqual(r2.status_code, 201)
            v2 = c.get("/api/previews/pkt-a.mp4")
            self.assertEqual(hashlib.sha256(v2.content).hexdigest(), h1)

    def test_activity_cursor_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            c = TestClient(create_app(td))
            packets.record_review_event(td, REV, {"action": "approve",
                                                  "clip_revision_id": "rev-a",
                                                  "packet_id": "pkt-a"})
            a1 = c.get("/api/activity")
            self.assertTrue(a1.json()["events"])
            cursor = a1.json()["cursor"]
            # new process, same project: full history replays from the DB
            c2 = TestClient(create_app(td))
            full = c2.get("/api/activity")
            self.assertEqual(len(full.json()["events"]), len(a1.json()["events"]))
            since = c2.get("/api/activity", params={"since": cursor})
            self.assertEqual(since.json()["events"], [])
            self.assertEqual(since.json()["cursor"], cursor)


if __name__ == "__main__":
    unittest.main()
