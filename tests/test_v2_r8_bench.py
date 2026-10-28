"""R8: the public-service benchmark runs and reports honestly."""
import json
import tempfile
import unittest
from pathlib import Path

from framebound.v2 import bench_eval


class BenchEval(unittest.TestCase):
    def test_public_service_benchmark_shape(self):
        rep = bench_eval.run_bench_eval(warm_runs=3, cold_runs=1)
        self.assertEqual(rep["service"], "services.clips.evaluate (public, persisted, complete required context)")
        self.assertEqual(rep["workload"]["frames"], 8)
        self.assertEqual(rep["workload"]["resolution"], [64, 64])
        self.assertEqual(rep["technical_status"], "pass")
        for key in ("cold_ms", "warm_ms", "incremental_changed_frame_ms"):
            self.assertGreater(rep[key]["p50"], 0)
            self.assertGreaterEqual(rep[key]["p95"], rep[key]["p50"])
        self.assertIn("whole-revision", rep["incremental_changed_frame_ms"]["invalidation"])
        self.assertIn("hardware", rep)
        self.assertIn("checks_included", rep["workload"])

    def test_benchmark_cli_writes_report(self):
        import subprocess
        import sys
        out = str(Path(tempfile.mkdtemp()) / "bench.json")
        r = subprocess.run([sys.executable, "-m", "framebound", "benchmark-eval",
                            "--warm-runs", "2", "--cold-runs", "1", "--report", out],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        rep = json.loads(Path(out).read_text())
        self.assertEqual(rep["technical_status"], "pass")


if __name__ == "__main__":
    unittest.main()
