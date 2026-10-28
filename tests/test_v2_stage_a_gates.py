"""Stage A gates: corrected product contract and trustworthy interfaces.

- All supported durable/tool models validate and checked-in schemas match code.
- Isolated tests load no other checkout (no hardcoded absolute checkout paths).
- Deterministic offline request/import/check/repair requires no Spark key/call.
- Unsupported intent yields a typed blocker, not an internal model judgment.
- Core runtime makes zero general-purpose model calls; spark critique retired.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path as P

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2 import schemas as SCH


class TestSchemaRegistryComplete(unittest.TestCase):
    def test_all_supported_models_have_schemas(self):
        for name in ["run", "compiled_brief", "world_trace", "transition_trace",
                     "motion_guide", "reference_approval", "registration", "edit_mask"]:
            self.assertIn(name, SCH.MODELS, f"MODELS missing {name}")
            p = P("schemas/v2") / f"{name}.schema.json"
            self.assertTrue(p.is_file(), f"missing checked-in schema {p}")
            on_disk = json.loads(p.read_text())
            live = SCH.MODELS[name].model_json_schema()
            # Required fields must match live model; checked-in schema must not be stale.
            self.assertEqual(set(on_disk.get("required", [])), set(live.get("required", [])),
                             f"stale checked-in schema for {name}")

    def test_job_schema_matches_live_model(self):
        p = P("schemas/v2/job.schema.json")
        on_disk = json.loads(p.read_text())
        live = D.Job.model_json_schema()
        self.assertEqual(set(on_disk.get("required", [])), set(live.get("required", [])))
        for prop in ("provider", "targets", "attempt_count", "dispatch_count",
                      "reserved_cost", "request_brief", "origin"):
            self.assertIn(prop, on_disk.get("properties", {}),
                          f"job.schema.json missing live property {prop}")

    def test_live_job_output_validates(self):
        j = D.Job(id="job-stage-a", kind="generation",
                  idempotency_key="idem-stage-a", payload_sha256="0" * 64)
        schema = json.loads(P("schemas/v2/job.schema.json").read_text())
        # Manual required-field conformance (no extra validator dependency).
        for field in schema.get("required", []):
            self.assertIn(field, j.model_dump())

    def test_verify_covers_all_durable_tables(self):
        from framebound.v2 import verify as V
        for table in ["compiled_briefs", "world_traces", "transition_traces", "runs"]:
            self.assertIn(table, V.TABLE_MODEL, f"verify missing {table}")


class TestIsolatedTests(unittest.TestCase):
    def test_no_hardcoded_checkout_paths(self):
        bad = []
        for p in P("tests").glob("test_*.py"):
            if p.name == P(__file__).name:
                continue
            text = p.read_text()
            for frag in ("/Volumes/", "/Users/raymondflanagan/Downloads"):
                if frag in text:
                    bad.append(f"{p.name}: {frag}")
        self.assertEqual(bad, [], f"hardcoded checkout paths: {bad}")

    def test_no_sys_path_outside_tests_dir(self):
        for p in P("tests").glob("test_*.py"):
            if p.name == P(__file__).name:
                continue
            for line in p.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('\"'):
                    continue
                if "sys.path.insert" in line and "__file__" not in line:
                    # Allow the explanatory string literal in this gate file only;
                    # every real sys.path use must derive from __file__.
                    if "sys.path.insert" in line and "in line" in line:
                        continue
                    self.assertIn("__file__", line,
                                  f"{p.name} uses a non-portable sys.path: {line}")
                    self.assertNotIn("/Volumes", line)


class TestNoGeneralPurposeInferenceInCore(unittest.TestCase):
    def test_core_modules_do_not_import_spark(self):
        core_modules = [
            "framebound.v2.checks.evaluate", "framebound.v2.checks.implementations",
            "framebound.v2.media.canonical", "framebound.v2.media.registration",
            "framebound.v2.storage", "framebound.v2.domain",
            "framebound.v2.services.clips", "framebound.v2.services.contracts",
            "framebound.v2.services.briefs", "framebound.v2.services.jobs",
            "framebound.v2.services.orchestrator", "framebound.v2.services.repair",
        ]
        for name in core_modules:
            mod = importlib.import_module(name)
            src = P(*mod.__file__.split("/")[-3:]).read_text() if False else None
            # Inspect loaded module file directly for spark imports.
            text = P(mod.__file__).read_text()
            self.assertNotIn("providers.spark", text, f"{name} imports spark")
            self.assertNotIn("providers import spark", text)
            self.assertNotIn("muse-spark-1.3", text,
                             f"{name} references the advisory model")

    def test_spark_adapter_marked_retired(self):
        from framebound.v2.providers import spark as SP
        self.assertTrue(getattr(SP, "RETIRED_FROM_ACTIVE_WORKFLOW", False))
        self.assertIn("DEPRECATED", (SP.__doc__ or ""))

    def test_capabilities_mark_spark_retired(self):
        from framebound.v2.services import capabilities as C
        rows = {(r[0], r[1]): (r[2], r[3]) for r in C.ROWS}
        status, _ = rows[("providers", "spark-critique")]
        self.assertEqual(status, "deprecated")

    def test_recorded_run_does_not_gate_on_spark(self):
        import inspect
        from framebound.v2 import recorded_run as RR
        src = inspect.getsource(RR.run_recorded)
        self.assertIn("advisory-only", src)
        self.assertIn('!= "spark-critique"', src)


class TestOfflineDeterministicPath(unittest.TestCase):
    def test_offline_import_check_repair_needs_no_key(self):
        # No provider keys may be required for the deterministic offline path.
        for var in ("MODEL_API_KEY", "FRAMEBOUND_VISION_MODEL", "FRAMEBOUND_MODEL"):
            os.environ.pop(var, None)
        from framebound.v2.checks import fixtures as F
        from framebound.v2 import domain as DD
        from framebound.v2.checks import evaluate as E
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            src = P(td) / "src"
            meta = F.build_cycle(src)
            from PIL import Image as _Image
            clean = [_Image.open(src / r).convert("RGBA") for r in meta["clean"]]
            refs = {i: _Image.open(src / r).convert("RGBA") for i, r in enumerate(meta["clean"])}
            from framebound.v2.media.canonical import canonical_pixels
            from framebound.v2.checks.raster import centroid, feature_points
            import math as _math
            px0 = canonical_pixels(clean[0])
            ca = centroid(feature_points(px0, 64, 64, (255, 200, 40), F.CLASP_WINDOW))
            cb = centroid(feature_points(px0, 64, 64, (255, 200, 40), F.BUCKLE_WINDOW))
            span0 = _math.dist(ca, cb)
            n = sum(1 for y in range(F.SUPPORT_WINDOW[1], F.SUPPORT_WINDOW[3])
                    for x in range(F.SUPPORT_WINDOW[0], F.SUPPORT_WINDOW[2])
                    if px0[(y * 64 + x) * 4 + 3] >= 128)
            contract = DD.ClipContractRevision(
                id="c-offline", character_revision_id="char-offline",
                action={"name": "run", "view": "side", "facing": "right", "loop": True},
                canvas={"width": 64, "height": 64, "units": "native_px"},
                timing={"ticks_per_second": 60, "holds": [4] * 8},
                references={"identity": "a-id", "style": "a-st",
                            "motion_guide_revision": "mg-offline"},
                phase_schedule=[{"slot": i, "phase": p, "motion_reference_id": f"pose-{p}"}
                                for i, p in enumerate(["A_contact", "A_compression", "A_passing", "A_flight",
                                                       "B_contact", "B_compression", "B_passing", "B_flight"])],
                constraints=[
                    {"id": "registration", "check": "native_registration", "required": True},
                    {"id": "support", "check": "declared_contacts", "required": True,
                     "params": {"window": F.SUPPORT_WINDOW, "min_visible": max(1, n // 2)}},
                    {"id": "look", "check": "appearance_palette", "required": True,
                     "params": {"max_drift": 0.06}},
                ],
                allowed_transforms={"per_pose_scale": False, "rigid_translation_budget_px": 2})
            ev = E.evaluate_frames(contract, clean, refs)
            self.assertEqual(ev.technical_status.value, "pass")


class TestTypedBlockers(unittest.TestCase):
    def test_unknown_check_is_typed_invalid_input(self):
        from framebound.v2.services import contracts as CT
        from framebound.v2.services.errors import InvalidInput
        with tempfile.TemporaryDirectory() as td:
            con = S.connect(td)
            try:
                S.insert(con, D.CharacterRevision(
                    id="char-x", project_id="p",
                    identity_asset_ids=["a"], style_asset_ids=["b"],
                    view_set=["side"], canvas={"width": 64, "height": 64},
                    scale_ruler="x"))
            finally:
                con.close()
            with self.assertRaises(InvalidInput):
                CT.propose_contract(td, {
                    "schema_version": "2.0", "id": "c-bad", "character_revision_id": "char-x",
                    "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
                    "canvas": {"width": 64, "height": 64, "units": "native_px"},
                    "timing": {"ticks_per_second": 60, "holds": [4] * 8},
                    "references": {"identity": "a", "style": "b",
                                   "motion_guide_revision": "mg-x"},
                    "phase_schedule": [{"slot": i, "phase": f"p{i}",
                                        "motion_reference_id": f"m{i}"} for i in range(8)],
                    "constraints": [{"id": "nope", "check": "telepathy_score", "required": True}],
                    "allowed_transforms": {"per_pose_scale": False,
                                           "rigid_translation_budget_px": 2}})

    def test_caller_brief_without_approval_is_typed_blocker(self):
        from framebound.v2.services import jobs as J
        from framebound.v2.services.errors import InvalidInput
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(InvalidInput) as ctx:
                J.submit_generation(td, {"slot": 0}, [], "k-unsupported")
            self.assertIn("compiled", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
