"""WP4 gate: persisted correction round-trip across API restart; reviewer-only writes."""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from framebound.v2.api.app import create_app
from framebound.v2.checks import fixtures as F
from framebound.v2.services import assets, clips, contracts, packets

MOD = {"X-Actor-Id": "spark-1"}  # orchestrator: no session token, never a reviewer


def _reviewer_headers(client) -> dict:
    """Localhost pairing ceremony: pair a reviewer id, exchange the code for a session."""
    pr = client.post("/api/reviewer/pair", json={"reviewer_id": "human-1"})
    assert pr.status_code == 201, pr.text
    op = client.post("/api/reviewer/open", json={"pairing_code": pr.json()["pairing_code"]})
    assert op.status_code == 201, op.text
    # single-use: the same code cannot mint a second session
    dup = client.post("/api/reviewer/open", json={"pairing_code": pr.json()["pairing_code"]})
    assert dup.status_code in (401, 403), dup.text
    return {"X-Session-Token": op.json()["session_token"]}


def _contract(aid_extra=""):
    return {
        "schema_version": "2.0", "id": "contract-desk-01", "character_revision_id": "char-01",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-01"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"} for i in range(8)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
    }


class DeskJourney(unittest.TestCase):
    def _build(self, td: str) -> dict:
        src = Path(td) / "src"
        meta = F.build_cycle(src)
        for i, rel in enumerate(meta["clean"]):
            assets.import_asset(td, str(src / rel), f"f-clean-{i}", source_kind="procedural")
        assets.import_asset(td, str(src / meta["clean"][0]), "a-id", source_kind="procedural")
        assets.import_asset(td, str(src / meta["clean"][1]), "a-st", source_kind="procedural")
        contracts.propose_contract(td, _contract())
        aids = [f"f-clean-{i}" for i in range(8)]
        clips.create_revision(td, "contract-desk-01", "clip-bad-01", aids, [f"p{i}" for i in range(8)])
        # introduce one faulty slot via a second revision
        assets.import_asset(td, str(src / meta["faults"]["phase"]), "f-wrong", source_kind="procedural")
        faulty = [f"f-clean-{i}" for i in range(8)]
        faulty[3] = "f-wrong"
        clips.create_revision(td, "contract-desk-01", "clip-bad-02", faulty, [f"p{i}" for i in range(8)])
        ev = clips.evaluate(td, "clip-bad-02")
        ev_id = ev.artifacts[0]["id"]
        pkt = packets.create_packet(td, "pkt-01", "clip-bad-02", ev_id, "review faulty run")
        return {"ev_id": ev_id, "meta": meta, "src": src}

    def test_full_round_trip_with_restart(self):
        with tempfile.TemporaryDirectory() as td:
            info = self._build(td)
            c1 = TestClient(create_app(td))
            REV = _reviewer_headers(c1)
            # reviewer marks an ROI issue over frames 3-5
            r = c1.post("/api/issues", json={
                "clip_revision_id": "clip-bad-02", "packet_id": "pkt-01",
                "frame_range": [3, 5], "roi": {"left": 8, "top": 8, "right": 56, "bottom": 60},
                "note": "torso pulse across 3-5", "category": "torso-pulse"}, headers=REV)
            self.assertEqual(r.status_code, 201, r.text)
            task_id = r.json()["task_id"]
            # model queue is machine-readable
            q = c1.get("/api/corrections", headers=MOD)
            self.assertIn(task_id, json.dumps(q.json()))
            scope = json.loads(next(t for t in q.json()["open"] if t["id"] == task_id)["scope"])
            self.assertEqual(scope["category"], "torso-pulse")
            self.assertEqual(scope["frame_range"], [3, 5])
            self.assertEqual(scope["roi"], {"left": 8, "top": 8, "right": 56, "bottom": 60})
            # model tools cannot write decisions
            d = c1.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-bad-02",
                                                "packet_id": "pkt-01", "expected_revision_id": "clip-bad-02"},
                        headers=MOD)
            self.assertEqual(d.status_code, 403)
            # stale browser approval is refused
            d2 = c1.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-bad-02",
                                                 "packet_id": "pkt-01", "expected_revision_id": "clip-stale"},
                         headers=REV)
            self.assertEqual(d2.status_code, 409)

            # ---- restart: brand-new app instance over the same project dir ----
            c2 = TestClient(create_app(td))
            pkt = c2.get("/api/packet/pkt-01")
            self.assertEqual(pkt.status_code, 200)
            self.assertIn("clip-bad-02", json.dumps(pkt.json()))
            q2 = c2.get("/api/corrections", headers=MOD)
            self.assertIn(task_id, json.dumps(q2.json()))
            # media survives restart, byte-identical
            a1 = c1.get("/api/asset/f-clean-0")
            a2 = c2.get("/api/asset/f-clean-0")
            self.assertEqual(a1.content, a2.content)
            self.assertTrue(len(a1.content) > 100)

            # tool client claims the task, submits a passing replacement
            cl = c2.post(f"/api/corrections/{task_id}/claim",
                         json={"expected_version": 1}, headers=MOD)
            self.assertEqual(cl.status_code, 200, cl.text)
            self.assertEqual(cl.json()["holder"], "spark-1")
            sub = c2.post(f"/api/corrections/{task_id}/submit",
                          json={"slot_assets": {"3": "f-clean-3"}, "recipe": "repair:restore-phase-guide",
                                "new_revision_id": "clip-fix-01"}, headers=MOD)
            self.assertEqual(sub.status_code, 201, sub.text)
            sj = sub.json()
            self.assertEqual(sj["evaluation"]["technical_status"], "pass")
            # before/after comparison packet exists at identical timing
            self.assertEqual(sj["packet"]["revision_id"], "clip-fix-01")
            # a mismatched packet cannot approve this revision: pkt-01 addresses clip-bad-02
            d3x = c2.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-fix-01",
                                                  "packet_id": "pkt-01", "expected_revision_id": "clip-fix-01"},
                          headers=REV)
            self.assertEqual(d3x.status_code, 422)
            # approval against the packet the submit created succeeds
            d3 = c2.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-fix-01",
                                                 "packet_id": "pkt-clip-fix-01",
                                                 "expected_revision_id": "clip-fix-01"},
                         headers=REV)
            self.assertEqual(d3.status_code, 201)
            issue_event = r.json()["event"]["operation_id"].replace("op-event-", "")
            rs = c2.post(f"/api/issues/{issue_event}/resolve",
                         json={"replacement_revision_id": "clip-fix-01",
                               "packet_id": "pkt-clip-fix-01",
                               "note": "pulse gone at same timing"}, headers=REV)
            self.assertEqual(rs.status_code, 200, rs.text)
            q4 = c2.get("/api/corrections", headers=MOD)
            self.assertNotIn(task_id, json.dumps(q4.json()))

    def test_subjective_correction_with_clean_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            info = self._build(td)
            c = TestClient(create_app(td))
            REV = _reviewer_headers(c)
            ev = clips.evaluate(td, "clip-bad-01")
            self.assertEqual(ev.technical_status.value, "pass")
            pkt = packets.create_packet(td, "pkt-clean", "clip-bad-01", ev.artifacts[0]["id"], "subjective pass")
            r = c.post("/api/issues", json={
                "clip_revision_id": "clip-bad-01", "packet_id": "pkt-clean", "frame_range": [3, 5],
                "note": "acting feels weak, no technical error", "category": "acting"}, headers=REV)
            self.assertEqual(r.status_code, 201)


if __name__ == "__main__":
    unittest.main()
