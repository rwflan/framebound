"""Second-remediation gates S0/S1: portable install identity + human authority.

Each test observes public behavior, not implementation labels.
"""
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("FRAMEBOUND_OPERATOR_SECRET", "test-operator-secret")
OP = os.environ["FRAMEBOUND_OPERATOR_SECRET"]

from framebound.v2.api.app import create_app  # noqa: E402


class TestPortableBaseline(unittest.TestCase):
    def test_lock_has_no_machine_specific_self_url(self):
        lock = Path(__file__).resolve().parents[1] / "requirements.lock"
        pins = [l for l in lock.read_text().splitlines()
                if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(any(l.startswith("aiohttp==") for l in pins))
        self.assertFalse(any("file://" in l or l.startswith("framebound @") for l in pins),
                         "lock must not pin a machine-specific self URL")

    def test_packaged_lock_matches_root_lock(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual((root / "requirements.lock").read_bytes(),
                         (root / "framebound" / "requirements.lock").read_bytes(),
                         "packaged lock resource must match the root lock")

    def test_packaged_lock_digest_is_non_null(self):
        from framebound.v2.checks import evaluate as EV
        ident = EV.lock_identity()
        self.assertIsNotNone(ident["digest"])
        self.assertEqual(len(ident["digest"]), 64)

    def test_build_identity_endpoint_serves_lock_and_desk(self):
        with tempfile.TemporaryDirectory() as td:
            c = TestClient(create_app(td))
            r = c.get("/api/build-identity")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIsNotNone(body["lock"]["digest"])
            # source checkout has web/dist; installed wheels carry framebound/desk
            self.assertTrue(body["desk_build_present"])

    def test_benchmark_variant_changes_actual_pixels(self):
        from framebound.v2 import bench_eval as BE
        rep = BE.run_bench_eval(warm_runs=2, cold_runs=1)
        self.assertIn("warm_ms", rep)
        self.assertNotIn("provenance_coverage", str(rep["workload"]["checks_included"]))


class TestReviewerAuthority(unittest.TestCase):
    def test_anonymous_pair_is_refused_and_mints_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            c = TestClient(create_app(td))
            r = c.post("/api/reviewer/pair", json={"reviewer_id": "mallory"})
            self.assertEqual(r.status_code, 403)
            # no code was minted: open with a garbage code also fails
            o = c.post("/api/reviewer/open", json={"pairing_code": "deadbeef"})
            self.assertIn(o.status_code, (403, 422))

    def test_model_grant_header_cannot_pair(self):
        with tempfile.TemporaryDirectory() as td:
            c = TestClient(create_app(td))
            r = c.post("/api/reviewer/pair", json={"reviewer_id": "mallory"},
                       headers={"X-Actor-Id": "spark-1"})
            self.assertEqual(r.status_code, 403)

    def test_operator_pair_open_revoke_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            c = TestClient(create_app(td))
            pr = c.post("/api/reviewer/pair", json={"reviewer_id": "human-1"},
                        headers={"X-Operator-Secret": OP})
            self.assertEqual(pr.status_code, 201)
            code = pr.json()["pairing_code"]
            op = c.post("/api/reviewer/open", json={"pairing_code": code})
            self.assertEqual(op.status_code, 201)
            token = op.json()["session_token"]
            # single-use: redeeming the same code again fails
            dup = c.post("/api/reviewer/open", json={"pairing_code": code})
            self.assertIn(dup.status_code, (401, 403, 422))
            # live token authorizes; revoked token does not
            from framebound.v2.services import sessions as SN
            self.assertEqual(SN.resolve_session(td, token), "human-1")
            rv = c.post("/api/reviewer/revoke", json={"session_token": token},
                        headers={"X-Operator-Secret": OP})
            self.assertEqual(rv.status_code, 200)
            self.assertTrue(rv.json()["revoked"])
            self.assertIsNone(SN.resolve_session(td, token))

    def test_wrong_operator_secret_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            c = TestClient(create_app(td))
            r = c.post("/api/reviewer/pair", json={"reviewer_id": "human-1"},
                       headers={"X-Operator-Secret": "wrong-secret"})
            self.assertEqual(r.status_code, 403)

    def test_cli_pair_needs_operator_secret(self):
        with tempfile.TemporaryDirectory() as td:
            from framebound.v2.services import sessions as SN
            from framebound.v2.services.errors import AuthorizationError
            with self.assertRaises(AuthorizationError):
                SN.pair_reviewer(td, "human-1")
            with self.assertRaises(AuthorizationError):
                SN.pair_reviewer(td, "human-1", operator_credential="wrong")
            ok = SN.pair_reviewer(td, "human-1", operator_credential=OP)
            self.assertIn("pairing_code", ok)


if __name__ == "__main__":
    unittest.main()
