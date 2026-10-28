"""Second-remediation gates S5: durable correction publication + current decisions.

Crash, concurrency, and stale-state behavior are observed at the service
boundary; the replayed envelope must equal the initial one field for field.
"""
import json
import tempfile
import unittest
from pathlib import Path

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.services import clips, contracts, masks
from framebound.v2.services import corrections as C
from framebound.v2.services import eligibility as EL
from framebound.v2.services import packets, review_state
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError, InvalidInput

import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent))
from test_v2_r4_repair import _seed, _open_issue, _claim, _mask, _submit  # noqa: E402

REV = Actor(type="reviewer", id="human-1")
ORCH = Actor(type="orchestrator", id="spark-1")


class TestDurablePublication(unittest.TestCase):
    def test_crash_after_registration_retries_to_one_result(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            # crash after registration: child rows exist, zero attempts
            clips.register_candidate(td, "rev-base", "rev-crash", {3: "f3"},
                                     recipe="repair:bounded-patch")
            con = S.connect(td)
            try:
                n_rev = con.execute("SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"]
                n_att = con.execute("SELECT COUNT(*) AS n FROM attempts").fetchone()["n"]
            finally:
                con.close()
            self.assertEqual(n_rev, 2)
            self.assertEqual(n_att, 0)
            # identical retry converges instead of conflicting on frame rows
            out = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                          "rev-crash", {3: "f3"}, "k-crash")
            self.assertTrue(out["ok"], out)
            con = S.connect(td)
            try:
                n_rev2 = con.execute("SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"]
                n_att2 = con.execute("SELECT COUNT(*) AS n FROM attempts").fetchone()["n"]
            finally:
                con.close()
            self.assertEqual(n_rev2, 2)
            self.assertEqual(n_att2, 1)

    def test_successful_replay_preserves_packet_and_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            first = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                            "rev-replay", {3: "f3"}, "k-replay")
            self.assertTrue(first["ok"])
            second = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                             "rev-replay", {3: "f3"}, "k-replay")
            self.assertTrue(second.get("deduped"))
            self.assertEqual(second["packet"]["artifacts"][0]["id"],
                             first["packet"]["artifacts"][0]["id"])
            self.assertEqual(second["evaluation_id"], first["evaluation_id"])
            # same envelope field types, not a reduced projection
            self.assertIsInstance(second["evaluation"], dict)
            self.assertIn("technical_status", second["evaluation"])
            self.assertIn("artifacts", second["evaluation"])
            self.assertIsInstance(second["packet"], dict)
            self.assertIn("operation_id", second["packet"])

    def test_stale_version_submit_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            con = S.connect(td)
            try:
                before = con.execute("SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"]
            finally:
                con.close()
            with self.assertRaises(Exception):
                _submit(td, task_id, cl["claim_token"], 1, base_ev,
                        "rev-stale", {3: "f3"}, "k-stale")
            con = S.connect(td)
            try:
                after = con.execute("SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"]
            finally:
                con.close()
            self.assertEqual(before, after)

    def test_different_payload_same_key_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            out = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                          "rev-dup", {3: "f3"}, "k-dup")
            self.assertTrue(out["ok"])
            with self.assertRaises(S.ConflictError):
                _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                        "rev-dup-other", {3: "f3"}, "k-dup")


class TestCurrentDecisions(unittest.TestCase):
    def _approved_packet(self, td: str, rev: str = "rev-base"):
        ev = clips.evaluate(td, rev)
        ev_id = ev.artifacts[0]["id"]
        pkt = packets.create_packet(td, f"pkt-{rev}", rev, ev_id, "review")
        return ev_id, pkt.artifacts[0]["id"]

    def test_pending_candidate_blocks_release_until_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            out = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                          "rev-pend", {3: "f3"}, "k-pend")
            self.assertTrue(out["ok"])
            # reviewer approves the candidate through its comparison packet
            packets.record_decision(td, REV, {"action": "approve",
                                              "clip_revision_id": "rev-pend",
                                              "packet_id": "pkt-rev-pend"})
            blocked = EL.release_eligibility(td, "rev-pend")
            self.assertFalse(blocked["eligible"], blocked)
            self.assertTrue(any("unresolved" in r for r in blocked["reasons"]))
            # resolving the issue against the published candidate releases it
            done = C.resolve_issue(td, REV, issue, "rev-pend",
                                   packet_id="pkt-rev-pend")
            self.assertTrue(done["ok"])
            free = EL.release_eligibility(td, "rev-pend")
            self.assertTrue(free["eligible"], free["reasons"])

    def test_approve_reject_approve_reduces_to_latest(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            clips.create_revision(td, "contract-R4", "rev-ara",
                                  [f"f{i}" for i in range(8)],
                                  [f"p{i}" for i in range(8)])
            ev_id, pkt_id = self._approved_packet(td, "rev-ara")
            packets.record_decision(td, REV, {"action": "approve",
                                              "clip_revision_id": "rev-ara",
                                              "packet_id": pkt_id})
            self.assertTrue(EL.release_eligibility(td, "rev-ara")["eligible"])
            packets.record_decision(td, REV, {"action": "reject",
                                              "clip_revision_id": "rev-ara",
                                              "packet_id": pkt_id})
            mid = EL.release_eligibility(td, "rev-ara")
            self.assertFalse(mid["eligible"])
            self.assertEqual(review_state.current_state(td, "rev-ara")["acceptance"],
                             "rejected")
            packets.record_decision(td, REV, {"action": "approve",
                                              "clip_revision_id": "rev-ara",
                                              "packet_id": pkt_id})
            self.assertEqual(review_state.current_state(td, "rev-ara")["acceptance"],
                             "approved")
            final = EL.release_eligibility(td, "rev-ara")
            self.assertTrue(final["eligible"], final["reasons"])

    def test_unrelated_same_contract_revision_cannot_resolve(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                    "rev-cand", {3: "f3"}, "k-cand")
            # an unrelated same-contract revision with its own packet
            clips.create_revision(td, "contract-R4", "rev-stranger",
                                  ["f0", "f1", "f2", "f4", "f4", "f5", "f6", "f7"],
                                  [f"p{i}" for i in range(8)])
            ev = clips.evaluate(td, "rev-stranger")
            pkt = packets.create_packet(td, "pkt-stranger", "rev-stranger",
                                        ev.artifacts[0]["id"], "compare")
            with self.assertRaises(InvalidInput) as ctx:
                C.resolve_issue(td, REV, issue, "rev-stranger",
                                packet_id=pkt.artifacts[0]["id"])
            self.assertIn("not a candidate", str(ctx.exception))

    def test_packetless_and_stale_resolution_refused(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                    "rev-res", {3: "f3"}, "k-res")
            with self.assertRaises(InvalidInput) as ctx:
                C.resolve_issue(td, REV, issue, "rev-res")
            self.assertIn("packet", str(ctx.exception).lower())
            # a stale packet (superseded evaluation) cannot resolve either:
            # new world-trace context supersedes the evaluation the packet binds
            clips.record_world_trace(td, "rev-res",
                                     [[1.0, 2.0]] * 32, [True] * 32)
            clips.evaluate(td, "rev-res")
            with self.assertRaises(InvalidInput) as ctx2:
                C.resolve_issue(td, REV, issue, "rev-res",
                                packet_id="pkt-rev-res")
            self.assertIn("stale", str(ctx2.exception).lower())

    def test_orchestrator_cannot_resolve(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                    "rev-or", {3: "f3"}, "k-or")
            with self.assertRaises(AuthorizationError):
                C.resolve_issue(td, ORCH, issue, "rev-or",
                                packet_id="pkt-rev-or")


if __name__ == "__main__":
    unittest.main()
