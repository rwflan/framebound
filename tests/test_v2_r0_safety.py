"""R0 regressions: safe outputs, reliable verification, install coherence, offline neutrality.

Each test hits the public boundary where the audited defect occurred; none
asserts a value the implementation filled in for itself.
"""
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _sentinel_tree(out: Path) -> bytes:
    out.mkdir(parents=True, exist_ok=True)
    keep = out / "KEEP-ME.txt"
    keep.write_bytes(b"user data sentinel\n")
    (out / "nested").mkdir(exist_ok=True)
    return keep.read_bytes()


class TestSafeOutputs(unittest.TestCase):
    def test_wp6_refuses_nonempty_output_without_modification(self):
        from framebound.v2.demo_wp6 import run_wp6
        from framebound.v2.safe_output import OutputExistsError
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "existing"
            before = _sentinel_tree(out)
            with self.assertRaises(OutputExistsError):
                run_wp6(out)
            self.assertEqual((out / "KEEP-ME.txt").read_bytes(), before)
            self.assertFalse((out / "project").exists())

    def test_v2_demo_refuses_nonempty_output_without_modification(self):
        from framebound.v2.demo import run_demo
        from framebound.v2.safe_output import OutputExistsError
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "existing"
            before = _sentinel_tree(out)
            with self.assertRaises(OutputExistsError):
                run_demo(out)
            self.assertEqual((out / "KEEP-ME.txt").read_bytes(), before)

    def test_v1_demo_refuses_nonempty_output_without_modification(self):
        from framebound.demo import build_demo
        from framebound.v2.safe_output import OutputExistsError
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "existing"
            before = _sentinel_tree(out)
            with self.assertRaises(OutputExistsError):
                build_demo(out)
            self.assertEqual((out / "KEEP-ME.txt").read_bytes(), before)

    def test_snapshot_refuses_nonempty_output_without_modification(self):
        from framebound.v2.devseed import build_minimal_project
        from framebound.v2.exports import build_snapshot
        from framebound.v2.safe_output import OutputExistsError
        with tempfile.TemporaryDirectory() as td:
            build_minimal_project(Path(td) / "proj")
            out = Path(td) / "snap"
            before = _sentinel_tree(out)
            with self.assertRaises((OutputExistsError, ValueError)):
                build_snapshot(str(Path(td) / "proj"), "s", ["clip-devseed-bad"], str(out), {})
            self.assertEqual((out / "KEEP-ME.txt").read_bytes(), before)

    def test_snapshot_refuses_output_equal_to_project(self):
        from framebound.v2.devseed import build_minimal_project
        from framebound.v2.exports import build_snapshot
        from framebound.v2.safe_output import UnsafeOutputError
        with tempfile.TemporaryDirectory() as td:
            build_minimal_project(Path(td) / "proj")
            with self.assertRaises(UnsafeOutputError):
                build_snapshot(str(Path(td) / "proj"), "s", ["clip-devseed-bad"],
                               str(Path(td) / "proj"), {})
            # the project itself still verifies after the refused export
            from framebound.v2.verify import run_verify
            vrep = run_verify(str(Path(td) / "proj"))
            self.assertTrue(vrep["ok"], vrep["issues"])

    def test_snapshot_refuses_output_holding_project_data(self):
        from framebound.v2.devseed import build_minimal_project
        from framebound.v2.exports import build_snapshot
        from framebound.v2.safe_output import UnsafeOutputError
        with tempfile.TemporaryDirectory() as td:
            build_minimal_project(Path(td) / "proj")
            impostor = Path(td) / "impostor"
            (impostor / "blobs").mkdir(parents=True)
            with self.assertRaises(UnsafeOutputError):
                build_snapshot(str(Path(td) / "proj"), "s", ["clip-devseed-bad"],
                               str(impostor), {})

    def test_replace_mode_requires_marker_and_preserves_backup(self):
        from framebound.v2.safe_output import OutputExistsError, UnsafeOutputError, prepare_output_dir
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "owned"
            _sentinel_tree(out)
            # unmarked dir: even replace=True must refuse, sentinel intact
            with self.assertRaises((UnsafeOutputError, OutputExistsError)):
                prepare_output_dir(out, replace=True, tool="t")
            self.assertTrue((out / "KEEP-ME.txt").is_file())
            # framework-owned dir: replace moves previous contents to a backup
            owned = Path(td) / "owned2"
            prepare_output_dir(owned, tool="t")
            (owned / "result.txt").write_text("v1")
            prepare_output_dir(owned, replace=True, tool="t")
            backups = list(Path(td).glob("owned2.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "result.txt").read_text(), "v1")
            self.assertFalse((owned / "result.txt").exists())


@unittest.skipIf(os.environ.get("FRAMEBOUND_VERIFY_ACTIVE") == "1",
                    "nested verify-local run: self-hosting tests skip to terminate")
class TestVerifyPropagation(unittest.TestCase):
    def _run_verify_with_failing_python(self, fail_match: str) -> subprocess.CompletedProcess:
        bindir = Path(tempfile.mkdtemp(prefix="fb-fakebin-"))
        try:
            real = sys.executable
            shim = bindir / "python"
            shim.write_text(
                "#!/bin/sh\n"
                f'FAIL_MATCH="{fail_match}"\n'
                f'REAL_PYTHON="{real}"\n'
                'for a in "$@"; do case "$a" in *"$FAIL_MATCH"*) exit 37;; esac; done\n'
                'exec "$REAL_PYTHON" "$@"\n'
            )
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            env = dict(os.environ)
            env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
            return subprocess.run(
                ["sh", "scripts/verify-local"], cwd=str(REPO), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600,
            )
        finally:
            shutil.rmtree(bindir, ignore_errors=True)

    def test_verify_fails_when_unittest_fails(self):
        proc = self._run_verify_with_failing_python("unittest")
        self.assertNotEqual(proc.returncode, 0, proc.stdout[-2000:])
        self.assertNotIn("ALL LOCAL CHECKS PASSED", proc.stdout)

    def test_verify_fails_when_pytest_fails(self):
        proc = self._run_verify_with_failing_python("pytest")
        self.assertNotEqual(proc.returncode, 0, proc.stdout[-2000:])
        self.assertNotIn("ALL LOCAL CHECKS PASSED", proc.stdout)

    def test_verify_script_has_no_masked_runner_pipelines(self):
        src = (REPO / "scripts" / "verify-local").read_text()
        for line in src.splitlines():
            s = line.strip()
            if s.startswith("#") or not s:
                continue
            if ("unittest" in s or "pytest" in s) and " | " in s:
                self.fail(f"runner output piped (exit masked): {s!r}")


class TestLockCoherence(unittest.TestCase):
    def test_lock_satisfies_declared_extras(self):
        from packaging.requirements import Requirement
        from packaging.version import Version
        import tomllib
        with open(REPO / "pyproject.toml", "rb") as fh:
            py = tomllib.load(fh)
        reqs = list(py["project"]["dependencies"])
        for extra in ("test", "export-validation"):
            reqs += py["project"]["optional-dependencies"][extra]
        pins: dict[str, str] = {}
        for line in (REPO / "requirements.lock").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("framebound @"):
                continue
            name, _, ver = line.partition("==")
            pins[name.lower().replace("-", "_")] = ver
        self.assertIn("datasets", pins)
        for r in reqs:
            req = Requirement(r)
            key = req.name.lower().replace("-", "_")
            self.assertIn(key, pins, f"locked pin missing for declared requirement {r}")
            if req.specifier:
                self.assertTrue(
                    Version(pins[key]) in req.specifier,
                    f"lock pin {key}=={pins[key]} violates declared {r}",
                )


class TestOfflineNeutrality(unittest.TestCase):
    def test_offline_paths_make_no_network_calls_with_keys_set(self):
        # Block DNS resolution and connection setup: any real HTTP/API egress
        # (httpx/requests/urllib) must resolve/connect first. Raw socket
        # *creation* stays allowed (ssl/asyncio import machinery needs it).
        import unittest.mock as mock

        def blocked(*a, **k):
            raise AssertionError("offline path attempted network egress")

        with tempfile.TemporaryDirectory() as td:
            env = {"MODEL_API_KEY": "bogus", "META_API_KEY": "bogus"}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                with mock.patch.object(socket, "create_connection", blocked), \
                        mock.patch.object(socket, "getaddrinfo", blocked):
                    from framebound.v2.demo import run_demo
                    from framebound.v2.demo_wp6 import run_wp6
                    from framebound.v2.devseed import build_minimal_project
                    from framebound.v2.exports import build_snapshot, validate_snapshot
                    from framebound.v2.verify import run_verify
                    run_demo(str(Path(td) / "d2"))
                    run_wp6(str(Path(td) / "d6"))
                    build_minimal_project(str(Path(td) / "proj"))
                    man = build_snapshot(str(Path(td) / "proj"), "s",
                                         ["clip-devseed-bad"], str(Path(td) / "snap"), {})
                    self.assertIn("snapshot", man)
                    rep = validate_snapshot(str(Path(td) / "snap"))
                    self.assertTrue(rep["ok"], rep["issues"])
                    vrep = run_verify(str(Path(td) / "d6" / "project"))
                    self.assertTrue(vrep["ok"], vrep["issues"])
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
