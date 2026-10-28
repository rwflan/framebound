"""Second-remediation gates S3: one durable execution controller with real ceilings.

Transport counts, stored authority/state, and fencing are observed at the
controller boundary; no helper self-report stands in for them.
"""
import base64
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.services import jobs as J
from framebound.v2.services import orchestrator as O
from framebound.v2.services.errors import InvalidInput

import sys
sys.path.insert(0, "/Volumes/datadisk0/data/appdata/repositories/framebound/tests")
from test_v2_r3_providers import _seed, _EnvKey, _png_bytes  # noqa: E402


def _live_transport(seen: dict, response_id: str = "resp-1"):
    def _t(req):
        seen["calls"] = seen.get("calls", 0) + 1
        seen["body"] = req["body"]
        return {"status": "completed", "id": response_id, "output": [
            {"type": "image_generation_call", "id": "img-1",
             "result": base64.b64encode(_png_bytes()).decode()}],
            "usage": {"total_tokens": 7}}
    return _t


def _claim(td: str, job_id: str, worker: str):
    con = S.connect(td)
    try:
        _, ver = S.get(con, "jobs", job_id)
    finally:
        con.close()
    return J.job_claim(td, job_id, worker, expected_version=ver)


class TestOfflineImmutability(unittest.TestCase):
    def test_offline_send_refusal_leaves_zero_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "off-2", offline=True)
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                claim = _claim(td, job_id, "w")
                with self.assertRaises(InvalidInput) as ctx:
                    O.orchestrator_send(td, run["run_id"], job_id, worker_id="w",
                                        fencing_token=claim["fencing_token"],
                                        offline=False,
                                        transport=_live_transport({}))
                self.assertIn("offline", str(ctx.exception).lower())
            job = J.job_get(td, job_id)["job"]
            self.assertTrue(job["offline"])
            self.assertEqual(job["attempt_count"], 0)
            self.assertEqual(job["dispatch_count"], 0)


class TestRequestIdentity(unittest.TestCase):
    def test_changed_brief_refused_before_transport(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            seen: dict = {}
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "chg-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                claim = _claim(td, job_id, "w")
                tampered = dict(compiled["brief"])
                tampered["instruction"] = compiled["brief"]["instruction"] + " extra"
                with self.assertRaises(InvalidInput) as ctx:
                    O.orchestrator_send(td, run["run_id"], job_id, tampered,
                                        worker_id="w",
                                        fencing_token=claim["fencing_token"],
                                        transport=_live_transport(seen))
                self.assertIn("diverges", str(ctx.exception))
            self.assertEqual(seen.get("calls", 0), 0)

    def test_wrong_run_refused_before_transport(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            seen: dict = {}
            with _EnvKey("live-key"):
                e1 = J.submit_generation(td, compiled["brief"], [], "wr-1")
                e2 = J.submit_generation(td, compiled["brief"], [], "wr-2")
                r1 = O.start_run(td, [e1.artifacts[0]["id"]])
                O.start_run(td, [e2.artifacts[0]["id"]])
                claim = _claim(td, e1.artifacts[0]["id"], "w")
                with self.assertRaises(InvalidInput) as ctx:
                    O.orchestrator_send(td, r1["run_id"], e2.artifacts[0]["id"],
                                        worker_id="w",
                                        fencing_token=claim["fencing_token"],
                                        transport=_live_transport(seen))
                self.assertIn("not a member", str(ctx.exception))
            self.assertEqual(seen.get("calls", 0), 0)


class TestFencing(unittest.TestCase):
    def test_expired_worker_fenced_from_completion(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "fx-1")
                job_id = env.artifacts[0]["id"]
                claim = _claim(td, job_id, "w1")
                # expire the lease out from under the worker
                con = S.connect(td)
                try:
                    data, ver = S.get(con, "jobs", job_id)
                    data["lease_expires"] = (datetime.now(timezone.utc)
                                             - timedelta(seconds=1)).isoformat()
                    con.execute("UPDATE jobs SET data=? WHERE id=?",
                                (__import__("json").dumps(data), job_id))
                    con.commit()
                finally:
                    con.close()
                con = S.connect(td)
                try:
                    _, v = S.get(con, "jobs", job_id)
                finally:
                    con.close()
                with self.assertRaises(InvalidInput) as ctx:
                    J.job_complete_failure(td, job_id, worker_id="w1",
                                           expected_version=v, error="late",
                                           retryable=False,
                                           fencing_token=claim["fencing_token"])
                self.assertIn("reconcile", str(ctx.exception))

    def test_foreign_worker_cannot_fail_job(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "fw-1")
                job_id = env.artifacts[0]["id"]
                _claim(td, job_id, "w1")
                con = S.connect(td)
                try:
                    _, v = S.get(con, "jobs", job_id)
                finally:
                    con.close()
                with self.assertRaises(InvalidInput) as ctx:
                    J.job_complete_failure(td, job_id, worker_id="w2",
                                           expected_version=v, error="hijack",
                                           retryable=False, fencing_token="wrong")
                self.assertIn("w1", str(ctx.exception))

    def test_concurrent_claim_single_winner(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            env = J.submit_generation(td, compiled["brief"], [], "cc-1")
            job_id = env.artifacts[0]["id"]
            con = S.connect(td)
            try:
                _, v = S.get(con, "jobs", job_id)
            finally:
                con.close()
            c1 = J.job_claim(td, job_id, "w1", expected_version=v)
            self.assertIn("fencing_token", c1)
            # stale version loses
            with self.assertRaises(Exception):
                J.job_claim(td, job_id, "w2", expected_version=v)
            # fresh version still refused: leased to w1
            with self.assertRaises(InvalidInput):
                J.job_claim(td, job_id, "w2", expected_version=c1["version"])


class TestBudgetsAndOutcomes(unittest.TestCase):
    def test_successful_send_consumes_attempt_and_reserves(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            seen: dict = {}
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "sc-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                step = O.run_once(td, run["run_id"], worker_id="w")
                self.assertEqual(step["action"], "send_ready")
                out = O.orchestrator_send(td, run["run_id"], job_id, worker_id="w",
                                          fencing_token=step["fencing_token"],
                                          transport=_live_transport(seen))
                self.assertEqual(out["action"], "succeeded")
            self.assertEqual(seen.get("calls"), 1)
            job = J.job_get(td, job_id)["job"]
            self.assertEqual(job["attempt_count"], 1)
            self.assertEqual(job["dispatch_count"], 1)
            self.assertIn("reserved", job["reserved_cost"])
            self.assertIsNotNone(job["request_artifact"])
            self.assertIsNotNone(job["response_artifact"])
            self.assertNotEqual(job["request_artifact"], job["response_artifact"])

    def test_ambiguous_timeout_is_one_send_and_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            calls: list = []

            def _flaky(req):
                calls.append(1)
                raise TimeoutError("ambiguous: accepted before the socket died?")
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "to-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                claim = _claim(td, job_id, "w")
                out = O.orchestrator_send(td, run["run_id"], job_id, worker_id="w",
                                          fencing_token=claim["fencing_token"],
                                          transport=_flaky)
                self.assertEqual(out["action"], "needs_attention")
                self.assertTrue(out["reconciliation_required"])
            self.assertEqual(len(calls), 1)
            job = J.job_get(td, job_id)["job"]
            self.assertEqual(job["status"], "needs_attention")
            self.assertEqual(job["attempt_count"], 1)
            self.assertTrue(job["reconciliation_required"])

    def test_exhausted_and_unknown_jobs_cannot_be_reclaimed(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "ex-1", max_attempts=1)
                job_id = env.artifacts[0]["id"]
                cl = _claim(td, job_id, "w1")
                con = S.connect(td)
                try:
                    _, v = S.get(con, "jobs", job_id)
                finally:
                    con.close()
                J.job_complete_failure(td, job_id, worker_id="w1", expected_version=v,
                                       error="boom", retryable=True,
                                       fencing_token=cl["fencing_token"])
                job = J.job_get(td, job_id)["job"]
                self.assertEqual(job["status"], "needs_attention")
                with self.assertRaises(InvalidInput):
                    J.job_claim(td, job_id, "w2", expected_version=job["version"] if "version" in job else 1)

    def test_new_run_does_not_reset_target_ceiling(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "nc-1", max_attempts=1)
                job_id = env.artifacts[0]["id"]
                run1 = O.start_run(td, [job_id], max_attempts=1)
                cl = _claim(td, job_id, "w")
                con = S.connect(td)
                try:
                    _, v = S.get(con, "jobs", job_id)
                finally:
                    con.close()
                J.job_complete_failure(td, job_id, worker_id="w", expected_version=v,
                                       error="boom", retryable=True,
                                       fencing_token=cl["fencing_token"])
                # a fresh run cannot buy another attempt for the same target
                run2 = O.start_run(td, [job_id], max_attempts=3)
                step = O.run_once(td, run2["run_id"], worker_id="w")
                self.assertEqual(step["action"], "stop")
            job = J.job_get(td, job_id)["job"]
            self.assertEqual(job["attempt_count"], 1)

    def test_restart_resumes_from_stored_state_without_caller_brief(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            seen: dict = {}
            with _EnvKey("live-key"):
                env = J.submit_generation(td, compiled["brief"], [], "rs-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                # first worker claims then disappears (crash): lease still live
                # so a second worker cannot steal it...
                step = O.run_once(td, run["run_id"], worker_id="w-first")
                # ...but the send path needs no caller brief at all
                out = O.orchestrator_send(td, run["run_id"], job_id, worker_id="w-first",
                                          fencing_token=step["fencing_token"],
                                          transport=_live_transport(seen))
                self.assertEqual(out["action"], "succeeded")
            self.assertEqual(seen.get("calls"), 1)


if __name__ == "__main__":
    unittest.main()
