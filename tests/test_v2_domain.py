"""WP1 gate: valid examples, invalid inputs, stale-write, hashing, restart, migration dry-run."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.migration import dry_run
from framebound.v2.schemas import valid_character_example, valid_contract_example


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class DomainSchemas(unittest.TestCase):
    def test_valid_contract_example(self):
        c = D.ClipContractRevision.model_validate(valid_contract_example())
        self.assertEqual(c.timing.total_ticks(), 32)
        self.assertEqual(len(c.phase_schedule), 8)

    def test_valid_character_example(self):
        ch = D.CharacterRevision.model_validate(valid_character_example())
        self.assertEqual(ch.canvas.width, 256)

    def test_negative_fixtures_rejected(self):
        neg = Path("examples/v2-negative")
        self.assertTrue(len(list(neg.glob("*.json"))) >= 7)
        for p in neg.glob("*.json"):
            with self.assertRaises(Exception, msg=p.name):
                D.ClipContractRevision.model_validate_json(p.read_text())

    def test_nonfinite_and_unknown_rejected(self):
        bad = json.loads(json.dumps(valid_contract_example()))
        bad["timing"]["ticks_per_second"] = float("inf")
        with self.assertRaises(Exception):
            D.ClipContractRevision.model_validate(bad)
        bad2 = json.loads(json.dumps(valid_contract_example()))
        bad2["unexpected_key"] = 1
        with self.assertRaises(Exception):
            D.ClipContractRevision.model_validate(bad2)

    def test_hold_slot_math_boundaries(self):
        t = D.Timing(ticks_per_second=60, holds=[4, 4, 4, 4, 4, 4, 4, 4])
        self.assertEqual(t.slot_at_tick(0, True), 0)
        self.assertEqual(t.slot_at_tick(3, True), 0)
        self.assertEqual(t.slot_at_tick(4, True), 1)
        self.assertEqual(t.slot_at_tick(31, True), 7)
        self.assertEqual(t.slot_at_tick(32, True), 0)  # loop wrap
        self.assertEqual(t.slot_at_tick(100, False), 7)  # one-shot clamps

    def test_unmeasured_requires_reason(self):
        with self.assertRaises(Exception):
            D.CheckResult(constraint_id="c", scope="s", outcome="unmeasured", reason="short")
        ok = D.CheckResult(constraint_id="c", scope="frame fi-01", outcome="unmeasured",
                           reason="required feature occluded; needs reviewed annotation")
        self.assertEqual(ok.outcome, D.CheckOutcome.UNMEASURED)


class DurableStorage(unittest.TestCase):
    def test_insert_get_update_stale_frozen(self):
        with tempfile.TemporaryDirectory() as td:
            con = S.connect(td)
            proj = D.Project(id="proj-demo", name="Demo", owner="entrant", rights_policy="original-only")
            S.insert(con, proj)
            data, ver = S.get(con, "projects", "proj-demo")
            self.assertEqual(ver, 1)
            proj2 = D.Project(id="proj-demo", name="Demo2", owner="entrant", rights_policy="original-only")
            nv = S.update_mutable(con, "projects", proj2, expected_version=1)
            self.assertEqual(nv, 2)
            with self.assertRaises(S.StaleRevisionError):
                S.update_mutable(con, "projects", proj2, expected_version=1)
            # frozen tables refuse updates
            c = D.ClipContractRevision.model_validate(valid_contract_example())
            S.insert(con, c)
            with self.assertRaises(S.FrozenRevisionError):
                S.update_mutable(con, "contract_revisions", c, expected_version=1)
            with self.assertRaises(S.ConflictError):
                S.insert(con, c)
            con.close()

    def test_asset_hashing_and_blob_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            raw = b"\x89PNG-fake-bytes"
            digest = S.store_blob(td, raw)
            self.assertEqual(digest, _h(raw))
            self.assertTrue(S.blob_path(td, digest).is_file())
            # second store is idempotent
            self.assertEqual(S.store_blob(td, raw), digest)
            asset = D.Asset(id="a-01", byte_sha256=digest, mime="image/png",
                            source_kind="procedural", rights="original", eligible_roles=["identity"])
            con = S.connect(td)
            S.insert(con, asset)
            con.close()

    def test_restart_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            con = S.connect(td)
            S.insert(con, D.Project(id="p1", name="N", owner="o", rights_policy="r"))
            S.insert(con, D.ClipContractRevision.model_validate(valid_contract_example()))
            con.close()
            con2 = S.connect(td)  # reopen after "restart"
            self.assertEqual(S.count(con2, "projects"), 1)
            self.assertEqual(S.count(con2, "contract_revisions"), 1)
            data, _ = S.get(con2, "contract_revisions", "contract-run-01")
            self.assertEqual(data["id"], "contract-run-01")
            con2.close()

    def test_job_idempotency(self):
        with tempfile.TemporaryDirectory() as td:
            con = S.connect(td)
            j = D.Job(id="job-1", kind="generation", idempotency_key="idem-123", payload_sha256="0" * 64)
            _, created = S.create_job_idempotent(con, j)
            self.assertTrue(created)
            j2 = D.Job(id="job-2", kind="generation", idempotency_key="idem-123", payload_sha256="0" * 64)
            orig, created2 = S.create_job_idempotent(con, j2)
            self.assertFalse(created2)
            self.assertEqual(orig.id, "job-1")  # no duplicated paid generation
            con.close()


class MigrationDryRun(unittest.TestCase):
    def test_reports_without_mutating(self):
        import subprocess
        before = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
        rep = dry_run("/tmp/fb-wp0-baseline")
        self.assertFalse(rep["mutated"])
        self.assertTrue(len(rep["importable_media"]) >= 8)
        self.assertEqual(rep["missing_references"], [])
        self.assertTrue(any("rights" in r for r in rep["unresolved_rights"]))
        after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)  # untouched originals


if __name__ == "__main__":
    unittest.main()
