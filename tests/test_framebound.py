import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framebound.audit import audit, preflight
from framebound.brief import compile_brief, validate_brief
from framebound.dataset import export_dataset
from framebound.demo import build_demo, FAULTS
from framebound.pngcodec import read_png, write_png
from framebound.repair import evaluate, plan


class DemoProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.out, cls.clean, cls.faulty = build_demo(Path(cls.tmp) / "demo")
        cls.contract = str(cls.out / "contract.json")

    def test_png_roundtrip(self):
        w, h, data = read_png(self.out / "master.png")
        p = Path(self.tmp) / "roundtrip.png"
        write_png(p, w, h, data)
        self.assertEqual(read_png(p), (w, h, data))

    def test_clean_cycle_passes(self):
        report = audit(self.contract, frame_files=self.clean)
        self.assertEqual(report["technical_status"], "pass", report["errors"])
        self.assertEqual(report["visual_acceptance"], "open")
        self.assertFalse(report["automatic_art_approval"])

    def test_each_injected_fault_is_named(self):
        report = audit(self.contract)
        codes = {e["code"] for e in report["errors"]}
        for fault in FAULTS:
            self.assertIn(fault["code"], codes, f"missing {fault['code']}: {codes}")

    def test_wrong_canvas_fails_registration(self):
        from framebound.checks import check_clip
        from framebound.audit import load_contract
        contract = load_contract(self.contract)
        frames = [(10, 10, bytes(10 * 10 * 4))] * 8
        issues, _ = check_clip(contract, frames)
        self.assertIn("candidate_registration", {i["code"] for i in issues})

    def test_brief_binds_master_and_phase(self):
        path, brief = compile_brief(self.contract, 2, Path(self.tmp) / "brief")
        roles = {i["role"] for i in brief["inputs"]}
        self.assertIn("approved_master", roles)
        self.assertIn("phase_reference", roles)
        self.assertFalse(brief["per_pose_fit"])

    def test_brief_rejects_sole_reference(self):
        from framebound.audit import load_contract
        contract = load_contract(self.contract)
        bad = {"inputs": [{"role": "x", "file": "master.png", "sha256": "0"}],
               "phase_reference_sha256": "x"}
        with self.assertRaises(ValueError):
            validate_brief(contract, bad, self.out)

    def test_repair_plan_covers_errors(self):
        report = audit(self.contract)
        rp = Path(self.tmp) / "report.json"
        rp.write_text(json.dumps(report))
        result = plan(rp, Path(self.tmp) / "plan.json")
        self.assertEqual(len(result["tasks"]), len(report["errors"]))
        self.assertFalse(result["automatic_art_approval"])

    def test_bounded_repair_is_selected(self):
        manifest = Path(self.tmp) / "candidates.json"
        manifest.write_text(json.dumps(
            {"candidates": [{"slot": f["slot"], "file": self.clean[f["slot"]]} for f in FAULTS]}))
        decision = evaluate(self.contract, manifest, Path(self.tmp) / "decision.json")
        self.assertTrue(decision["selected_for_review"], decision)
        self.assertFalse(decision["runtime_writes"])

    def test_repair_outside_region_is_rejected(self):
        # Candidate for slot 2 that also paints a corner outside its region.
        from framebound.pngcodec import read_png as rp_, write_png as wp_
        w, h, data = rp_(self.out / self.clean[2])
        data = bytearray(data)
        data[0:4] = bytes((255, 0, 0, 255))
        p = Path(self.tmp) / "sneaky.png"
        wp_(p, w, h, bytes(data))
        rel = str(p.relative_to(self.out)) if p.is_relative_to(self.out) else None
        cand = Path(self.out) / "sneaky.png"
        wp_(cand, w, h, bytes(data))
        manifest = Path(self.tmp) / "sneaky.json"
        manifest.write_text(json.dumps({"candidates": [{"slot": 2, "file": "sneaky.png"}]}))
        decision = evaluate(self.contract, manifest, Path(self.tmp) / "sneaky-decision.json")
        self.assertFalse(decision["selected_for_review"])
        self.assertTrue(decision["protection_errors"])

    def test_dataset_export_is_valid(self):
        result = export_dataset(self.contract, Path(self.tmp) / "dataset")
        self.assertEqual(result["images"], 8)
        coco = json.loads((Path(self.tmp) / "dataset" / "coco" / "annotations.json").read_text())
        self.assertEqual(len(coco["images"]), 8)
        self.assertTrue(coco["annotations"])
        prefs = (Path(self.tmp) / "dataset" / "preferences.jsonl").read_text().strip().splitlines()
        self.assertTrue(prefs)
        for line in prefs:
            row = json.loads(line)
            self.assertIn("chosen", row); self.assertIn("rejected", row)

    def test_preflight_never_promotes(self):
        manifest = Path(self.tmp) / "pf.json"
        manifest.write_text(json.dumps({"candidates": [{"slot": 2, "file": self.clean[2]}]}))
        report = preflight(self.contract, manifest)
        self.assertEqual(report["evaluation_mode"], "candidate-preflight")
        # Other faulty slots still fail; preflight changed nothing on disk.
        self.assertEqual(report["technical_status"], "fail")


class CliAndServers(unittest.TestCase):
    def test_demo_command(self):
        proc = subprocess.run([sys.executable, "-m", "framebound", "demo",
                               "--out", str(Path(tempfile.mkdtemp()) / "d")],
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["clean_technical_status"], "pass")
        self.assertTrue(summary["repair_selected_for_review"])

    def test_mcp_tools_list(self):
        proc = subprocess.run([sys.executable, "-m", "framebound", "mcp"],
                              input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1])
        resp = json.loads(proc.stdout.strip().splitlines()[0])
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("check_clip", names)
        self.assertIn("export_dataset", names)


if __name__ == "__main__":
    unittest.main()
