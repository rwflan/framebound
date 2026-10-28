"""Second-remediation gates S4: real provider loops + four-capability runner.

Strict documented fakes drive the adapters; every assertion observes the
parsed outcome, the transport count, or the stored bundle — never the fake's
own labels.
"""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import storage as S
from framebound.v2.providers import image as IMG
from framebound.v2.providers import sam as SAM
from framebound.v2.providers import spark as SPARK
from framebound.v2.providers import wire as W
from framebound.v2.services.errors import InvalidInput, ResponseInvalid

import sys
sys.path.insert(0, "/Volumes/datadisk0/data/appdata/repositories/framebound/tests")
from test_v2_r3_providers import _seed, _EnvKey, _png_bytes  # noqa: E402


def _b64_png(color=(10, 200, 30, 255)) -> str:
    return base64.b64encode(_png_bytes(color=color)).decode()


def _frame_blobs():
    tiny = base64.b64encode(bytes(64)).decode()
    return [{"slot": 0, "asset_id": "a", "mime": "image/png", "bytes_b64": tiny}]


class TestSparkLoop(unittest.TestCase):
    def test_completed_text_without_calls_is_valid(self):
        with tempfile.TemporaryDirectory() as td, _EnvKey("k"):
            calls = []

            def fake(req):
                calls.append(req)
                return {"status": "completed", "id": "resp-text",
                        "output": [{"type": "message",
                                    "content": [{"type": "output_text",
                                                 "text": "steady critique: hold the pose"}]}]}
            out = SPARK.submit_critique("contract", [], _frame_blobs(), td,
                                        transport=fake)
            self.assertTrue(out["sent"])
            self.assertEqual(out["calls"], [])
            self.assertIn("steady critique", out["text"])
            self.assertEqual(len(calls), 1)
            self.assertIn("prose advisory", out["critique"]["diagnostic"])

    def test_tool_outputs_are_sent_and_final_answer_validated(self):
        with tempfile.TemporaryDirectory() as td, _EnvKey("k"):
            seen = []

            def fake(req):
                seen.append(req)
                if len(seen) == 1:
                    return {"status": "completed", "id": "resp-1", "output": [
                        {"type": "function_call", "call_id": "call-1",
                         "name": "get_deterministic_findings",
                         "arguments": json.dumps({"revision_id": "r1"})}]}

                body = req["body"]
                self.assertEqual(body.get("previous_response_id"), "resp-1")
                kinds = [i.get("type") for i in body.get("input", [])]
                self.assertIn("function_call_output", kinds)
                out = next(i for i in body["input"]
                           if i.get("type") == "function_call_output")
                self.assertEqual(out["call_id"], "call-1")
                return {"status": "completed", "id": "resp-2", "output": [
                    {"type": "message", "content": [
                        {"type": "output_text",
                         "text": json.dumps({"findings": [
                             {"frame": 3, "note": "drift visible",
                              "uncertainty": 0.2,
                              "evidence_refs": ["eval:abc"]}],
                             "summary": "one drift"})}]}]}
            out = SPARK.submit_critique(
                "contract", [], _frame_blobs(), td, transport=fake, max_turns=3,
                handlers={"get_deterministic_findings": lambda revision_id: {"ok": True}})
            self.assertEqual(len(seen), 2)
            self.assertFalse(out["halted_on_turn_budget"])
            self.assertEqual(len(out["turns"]), 2)
            self.assertEqual(out["critique"]["findings"][0]["frame"], 3)
            self.assertEqual(out["critique"]["findings"][0]["uncertainty"], 0.2)

    def test_turn_limit_and_incomplete_response_are_explicit(self):
        with tempfile.TemporaryDirectory() as td, _EnvKey("k"):
            def stubborn(req):
                return {"status": "completed", "id": "resp-1", "output": [
                    {"type": "function_call", "call_id": "c1",
                     "name": "get_deterministic_findings",
                     "arguments": json.dumps({"revision_id": "r1"})}]}
            out = SPARK.submit_critique("contract", [], _frame_blobs(), td,
                                        transport=stubborn, max_turns=1,
                                        handlers={"get_deterministic_findings":
                                                  lambda revision_id: {}})
            self.assertTrue(out["halted_on_turn_budget"])
            self.assertEqual(out["text"], "")
            with self.assertRaises(ResponseInvalid):
                SPARK.submit_critique(
                    "contract", [], _frame_blobs(), td,
                    transport=lambda req: {"status": "incomplete", "id": "x",
                                           "output": []})

    def test_duplicate_call_ids_refused(self):
        with tempfile.TemporaryDirectory() as td, _EnvKey("k"):
            def dupe(req):
                return {"status": "completed", "id": "r", "output": [
                    {"type": "function_call", "call_id": "c",
                     "name": "get_reference_metadata",
                     "arguments": json.dumps({"asset_id": "a"})},
                    {"type": "function_call", "call_id": "c",
                     "name": "get_reference_metadata",
                     "arguments": json.dumps({"asset_id": "a"})}]}
            with self.assertRaises(InvalidInput):
                SPARK.submit_critique(
                    "contract", [], _frame_blobs(), td, transport=dupe,
                    handlers={"get_reference_metadata": lambda asset_id: {}})


class TestSamOutcomes(unittest.TestCase):
    def test_failed_response_is_not_no_match(self):
        with tempfile.TemporaryDirectory() as td, _EnvKey("k"):
            def failed(req):
                return {"status": "failed", "id": "s-1", "output": [],
                        "error": {"message": "model blew up"}}
            out = SAM.submit(_b64_png(), "glasses", td, transport=failed,
                             source_width=64, source_height=64)
            self.assertEqual(out["outcome"], "failed")
            self.assertNotEqual(out["outcome"], "no_match")

    def test_truncated_response_is_not_no_match(self):
        self.assertEqual(
            SAM.parse_output_text("", source_width=8, source_height=8,
                                  status="incomplete")["outcome"], "failed")

    def test_full_frame_is_full_not_mask(self):
        raster = bytes([1] * 64)  # 8x8 all foreground
        import base64 as _b64
        payload = _b64.b85encode(bytes(
            int("".join(str(b) for b in raster[i:i + 8]), 2)
            for i in range(0, 64, 8))).decode()
        line = f"<0f>0<|box;x1=0;y1=0;x2=8;y2=8;w=8;h=8|><|mask;x=0;y=0;data=8,8,~{payload}|>"
        out = SAM.parse_output_text(line, source_width=8, source_height=8,
                                    status="completed")
        self.assertEqual(out["outcome"], "full")

    def test_source_dims_required(self):
        with tempfile.TemporaryDirectory() as td, _EnvKey("k"):
            with self.assertRaises(InvalidInput):
                SAM.submit(_b64_png(), "glasses", td, transport=lambda r: {})


class TestOriginAndRunner(unittest.TestCase):
    def test_simulated_output_cannot_be_labeled_live(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            from framebound.v2.services import jobs as J
            resolved = J._resolve_references(td, compiled["brief"], [])
            with _EnvKey("k"):
                res = IMG.submit(compiled["brief"], resolved, td, "org-1",
                                 transport=lambda req: {
                                     "status": "completed", "id": "r",
                                     "output": [{"type": "image_generation_call",
                                                 "id": "i",
                                                 "result": _b64_png()}]})
            self.assertTrue(res["sent"])
            self.assertEqual(res["origin"], "simulated-transport")
            self.assertNotEqual(res["origin"], "live")

    def test_recorded_run_binds_four_capabilities_with_ids(self):
        with tempfile.TemporaryDirectory() as td:
            from test_v2_demo import RecordedRun
            rr = RecordedRun()
            rr._approved_project(td)
            import os as _os
            _os.environ["MODEL_API_KEY"] = "simulated-key"
            try:
                raw = S.blob_path(
                    td, S.get(S.connect(td), "assets", "f0")[0]["byte_sha256"]).read_bytes()
                png_b64 = base64.b64encode(raw).decode()
                seen = []

                def fake(req):
                    seen.append(req["body"].get("model"))
                    return {"status": "completed", "id": "resp-sim",
                            "output": [{"type": "image_generation_call", "id": "img-1",
                                        "result": png_b64}],
                            "usage": {"total_tokens": 1}}
                from framebound.v2 import recorded_run as RR
                out = RR.run_recorded(td, str(Path(td) / "bundle.json"),
                                      contract_id="c-RR", slot=0,
                                      baseline_revision_id="rev-rr-base",
                                      new_revision_id="rev-rr-4cap",
                                      offline=False, transport=fake,
                                      idempotency_key="rr-4cap-1")
            finally:
                del _os.environ["MODEL_API_KEY"]
            caps = {c["capability"] for c in out["capabilities"]}
            self.assertEqual(caps, {"spark-critique", "image-generation",
                                    "image-edit", "sam-segmentation"})
            # every capability carries its own request/response identity and
            # artifacts that resolve in the blob store
            for cap in out["capabilities"]:
                self.assertTrue(cap["request_artifact"], cap["capability"])
                self.assertTrue(
                    S.blob_path(td, cap["request_artifact"]).is_file())
                if cap["status"] == "recorded" and cap.get("response_artifact"):
                    self.assertTrue(
                        S.blob_path(td, cap["response_artifact"]).is_file())
            models = [m for m in seen]
            self.assertIn("muse-spark-1.3", models)
            self.assertIn("muse-image-1.0", models)
            self.assertIn("sam-3.1", models)

    def test_crash_after_bytes_resumes_without_new_request(self):
        with tempfile.TemporaryDirectory() as td:
            from test_v2_demo import RecordedRun
            rr = RecordedRun()
            rr._approved_project(td)
            import os as _os
            _os.environ["MODEL_API_KEY"] = "simulated-key"
            try:
                raw = S.blob_path(
                    td, S.get(S.connect(td), "assets", "f0")[0]["byte_sha256"]).read_bytes()
                png_b64 = base64.b64encode(raw).decode()
                calls = []

                def fake(req):
                    calls.append(1)
                    return {"status": "completed", "id": "resp-sim",
                            "output": [{"type": "image_generation_call", "id": "img-1",
                                        "result": png_b64}],
                            "usage": {"total_tokens": 1}}
                from framebound.v2 import recorded_run as RR
                from framebound.v2.services import briefs as B
                compiled = B.compile_reference_brief(td, "c-RR", 0)
                first = RR._controller_send(td, compiled["brief"], "crash-1",
                                            transport=fake)
                n_calls = len(calls)
                # crash: paid bytes received, but the asset row/import is lost
                con = S.connect(td)
                try:
                    con.execute("DELETE FROM assets WHERE id=?",
                                (first["output_asset_id"],))
                    con.commit()
                finally:
                    con.close()
                second = RR._controller_send(td, compiled["brief"], "crash-1",
                                             transport=fake)
                self.assertEqual(len(calls), n_calls)
                self.assertTrue(second["reused"])
                self.assertEqual(second["output_bytes"], first["output_bytes"])
            finally:
                del _os.environ["MODEL_API_KEY"]

    def test_idempotent_rerun_returns_same_bundle_without_respend(self):
        with tempfile.TemporaryDirectory() as td:
            from test_v2_demo import RecordedRun
            rr = RecordedRun()
            rr._approved_project(td)
            import os as _os
            _os.environ["MODEL_API_KEY"] = "simulated-key"
            try:
                raw = S.blob_path(
                    td, S.get(S.connect(td), "assets", "f0")[0]["byte_sha256"]).read_bytes()
                png_b64 = base64.b64encode(raw).decode()
                calls = []

                def fake(req):
                    calls.append(1)
                    return {"status": "completed", "id": "resp-sim",
                            "output": [{"type": "image_generation_call", "id": "img-1",
                                        "result": png_b64}],
                            "usage": {"total_tokens": 1}}
                from framebound.v2 import recorded_run as RR
                out1 = RR.run_recorded(td, str(Path(td) / "b.json"),
                                       contract_id="c-RR", slot=0,
                                       baseline_revision_id="rev-rr-base",
                                       new_revision_id="rev-rr-idem",
                                       offline=False, transport=fake,
                                       idempotency_key="rr-idem-1")
                spent = len(calls)
                out2 = RR.run_recorded(td, str(Path(td) / "b.json"),
                                       contract_id="c-RR", slot=0,
                                       baseline_revision_id="rev-rr-base",
                                       new_revision_id="rev-rr-idem",
                                       offline=False, transport=fake,
                                       idempotency_key="rr-idem-1")
                self.assertEqual(out1, out2)
                self.assertEqual(len(calls), spent)
            finally:
                del _os.environ["MODEL_API_KEY"]


if __name__ == "__main__":
    unittest.main()
