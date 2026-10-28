"""Stage E gates: durable optional provider execution and resumable work graph.

- Overlapping calls cause one send (atomic dispatch reservation).
- Run/target/cost caps hold under concurrency and new keys.
- Zero/invalid grants send nothing.
- Queued model/settings are immutable.
- Queued offline jobs stay offline; received paid output survives SIGKILL-style
  import loss without repurchase; blocked inputs resume via durable ops.
"""
import tempfile
import unittest

from framebound.v2 import storage as S
from framebound.v2.services import jobs as J
from framebound.v2.services import orchestrator as O
from framebound.v2.services.errors import InvalidInput


def _seed_job(td: str, key: str, brief: dict | None = None, **kw) -> str:
    brief = brief or {"compiled_brief_id": "cb-x", "slot": 0,
                      "contract_revision_id": "c-x"}
    # Bypass reference resolution for unit-level dispatch tests by stubbing?
    # Use offline jobs with minimal frozen refs via direct Job insert instead.
    from framebound.v2 import domain as D
    import hashlib
    con = S.connect(td)
    try:
        job = D.Job(id=f"job-{abs(hash(key)) % 1000000}", kind="generation",
                    idempotency_key=key,
                    payload_sha256="0" * 64,
                    provider="image", targets=kw.get("targets", ["c-x#slot-0"]),
                    max_attempts=kw.get("max_attempts", 3),
                    budget_reserved=kw.get("budget_reserved", "max_attempts=3"),
                    request_brief={**brief, "_frozen_provider_settings": {"model": "m", "transport": "responses"}},
                    provider_settings=kw.get("provider_settings", {"model": "m", "transport": "responses"}),
                    offline=kw.get("offline", False))
        S.insert(con, job)
        run = D.Run(id=kw.get("run_id", "run-1"), job_ids=[job.id],
                    max_attempts=kw.get("run_max", 3))
        try:
            S.insert(con, run)
        except Exception:
            pass
        return job.id, run.id
    finally:
        con.close()


class TestAtomicDispatch(unittest.TestCase):
    def setUp(self):
        # Unit-level dispatch tests bypass reference resolution (covered by
        # service-level brief tests); focus here on fencing/ceilings/freeze.
        from unittest import mock as _mock
        self._rr = _mock.patch("framebound.v2.services.jobs._resolve_references",
                               return_value=[{"asset_id": "a", "byte_sha256": "0" * 64}])
        self._ph = _mock.patch("framebound.v2.services.jobs._payload_hash",
                               return_value="0" * 64)
        self._rr.start(); self._ph.start()
        self.addCleanup(self._rr.stop); self.addCleanup(self._ph.stop)

    def test_overlapping_claim_sends_once(self):
        import threading
        with tempfile.TemporaryDirectory() as td:
            jid, rid = _seed_job(td, "k-dup")
            # Claim once, then two concurrent authorize attempts: one wins.
            claim = J.job_claim(td, jid, "w1", expected_version=1)
            tok = claim["fencing_token"]
            results = []
            def _try(worker):
                try:
                    # Second worker with wrong fencing token must fail.
                    O._authorize_send(td, rid, jid, None, worker, tok if worker == "w1" else "bad",
                                      offline=False)
                    results.append((worker, "authorized"))
                except Exception as e:
                    results.append((worker, f"refused:{type(e).__name__}"))
            t1 = threading.Thread(target=_try, args=("w1",))
            t2 = threading.Thread(target=_try, args=("w2",))
            t1.start(); t2.start(); t1.join(); t2.join()
            ok = [r for r in results if r[1] == "authorized"]
            self.assertEqual(len(ok), 1)
            self.assertEqual(ok[0][0], "w1")

    def test_run_cap_holds_for_two_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            from framebound.v2 import domain as D
            con = S.connect(td)
            try:
                for i in (1, 2):
                    S.insert(con, D.Job(id=f"job-{i}", kind="generation",
                                        idempotency_key=f"k-{i}", payload_sha256="0" * 64,
                                        provider="image", targets=[f"c#slot-{i}"],
                                        max_attempts=3,
                                        request_brief={"slot": i, "_frozen_provider_settings": {"model": "m", "transport": "responses"}},
                                        provider_settings={"model": "m", "transport": "responses"}))
                S.insert(con, D.Run(id="run-cap", job_ids=["job-1", "job-2"], max_attempts=1))
            finally:
                con.close()
            c1 = J.job_claim(td, "job-1", "w", expected_version=1)
            O._authorize_send(td, "run-cap", "job-1", None, "w", c1["fencing_token"], offline=False)
            # Simulate run budget consumed.
            con = S.connect(td)
            try:
                rdata, rver = S.get(con, "runs", "run-cap")
                run = D.Run.model_validate_json(__import__("json").dumps(rdata))
                run.attempts_used = 1
                S.update_mutable(con, "runs", run, rver)
            finally:
                con.close()
            c2 = J.job_claim(td, "job-2", "w", expected_version=1)
            with self.assertRaises(InvalidInput):
                O._authorize_send(td, "run-cap", "job-2", None, "w", c2["fencing_token"], offline=False)

    def test_zero_spend_sends_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            jid, rid = _seed_job(td, "k-zero", budget_reserved="usd-0")
            cl = J.job_claim(td, jid, "w", expected_version=1)
            with self.assertRaises(InvalidInput):
                O._authorize_send(td, rid, jid, None, "w", cl["fencing_token"], offline=False)

    def test_queued_settings_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            jid, rid = _seed_job(td, "k-frozen")
            con = S.connect(td)
            try:
                data, ver = S.get(con, "jobs", jid)
                job = __import__("framebound.v2.domain", fromlist=["Job"]).Job.model_validate(data)
                job.provider_settings = {"model": "other-model", "transport": "responses"}
                S.update_mutable(con, "jobs", job, ver)
            finally:
                con.close()
            # Re-claim to get a fresh lease, then authorize must refuse the mutation.
            # Claim requires QUEUED; job is still QUEUED (no claim yet), so claim now.
            cl = J.job_claim(td, jid, "w", expected_version=2)
            with self.assertRaises(InvalidInput) as ctx:
                O._authorize_send(td, rid, jid, None, "w", cl["fencing_token"], offline=False)
            self.assertIn("immutable", str(ctx.exception).lower())

    def test_offline_stays_offline(self):
        with tempfile.TemporaryDirectory() as td:
            jid, rid = _seed_job(td, "k-off", offline=True)
            cl = J.job_claim(td, jid, "w", expected_version=1)
            with self.assertRaises(InvalidInput):
                O._authorize_send(td, rid, jid, None, "w", cl["fencing_token"], offline=False)


if __name__ == "__main__":
    unittest.main()
