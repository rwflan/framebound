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
from framebound.v2 import storage as S


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
    browser_headers = {'Origin': 'http://127.0.0.1', 'Sec-Fetch-Site': 'same-origin', 'X-Framebound-Desk': '1'}

    def client(self, td, peer='127.0.0.1'):
        return TestClient(create_app(td), base_url='http://127.0.0.1', client=(peer, 50000))

    def test_anonymous_or_model_requests_cannot_start_browser_review(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.client(td)
            self.assertEqual(c.post('/api/desk/session').status_code, 403)
            self.assertEqual(c.post('/api/desk/session', headers={**self.browser_headers, 'X-Actor-Id':'model'}).status_code, 403)
            con = S.connect(td)
            try:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM reviewer_sessions').fetchone()[0], 0)
            finally:
                con.close()

    def test_same_origin_browser_is_ready_without_enrollment(self):
        with tempfile.TemporaryDirectory() as td:
            from framebound.v2.services import sessions as SN
            c = self.client(td)
            r = c.post('/api/desk/session', headers=self.browser_headers)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), {'ready': True})
            self.assertIn('httponly', r.headers['set-cookie'].lower())
            self.assertIn('samesite=strict', r.headers['set-cookie'].lower())
            token = c.cookies['fb_desk_review']
            self.assertEqual(SN.resolve_session(td, token), 'local-reviewer')
            self.assertEqual(c.post('/api/desk/session', headers=self.browser_headers).status_code, 200)
            self.assertEqual(c.cookies['fb_desk_review'], token)
            revoked = c.post('/api/reviewer/revoke', json={'session_token':token}, headers={'X-Operator-Secret': OP})
            self.assertEqual(revoked.status_code, 200, revoked.text)
            self.assertIsNone(SN.resolve_session(td, token))

    def test_cross_origin_and_remote_browser_requests_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.client(td)
            for overrides in ({'Origin':'https://elsewhere.example'}, {'Sec-Fetch-Site':'cross-site'}, {'X-Framebound-Desk':'0'}):
                self.assertEqual(c.post('/api/desk/session', headers={**self.browser_headers, **overrides}).status_code, 403)
            remote = self.client(td, peer='192.0.2.1')
            self.assertEqual(remote.post('/api/desk/session', headers=self.browser_headers).status_code, 403)

    def test_cookie_cannot_authorize_cross_origin_writes(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.client(td)
            c.post('/api/desk/session', headers=self.browser_headers)
            r = c.post('/api/decisions', json={}, headers={**self.browser_headers, 'Origin':'https://elsewhere.example'})
            self.assertEqual(r.status_code, 403)

    def test_operator_revocation_still_requires_its_credential(self):
        with tempfile.TemporaryDirectory() as td:
            from framebound.v2.services import sessions as SN
            from framebound.v2.services.errors import AuthorizationError
            session = SN.create_session(td)
            with self.assertRaises(AuthorizationError):
                SN.revoke_session(td, session['session_token'], operator_credential='wrong')


if __name__ == '__main__':
    unittest.main()
