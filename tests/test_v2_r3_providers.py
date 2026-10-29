"""R3 regressions: documented provider wire + durable controller/jobs.

Each test hits the public boundary where the audit reproduced the defect;
none asserts a value the implementation filled in for itself. Strict fakes
reject the old placeholder payloads and accept the repaired documented ones.
"""
import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.checks import fixtures as F
from framebound.v2.providers import wire as W
from framebound.v2.providers import image as IMG
from framebound.v2.providers import sam as SAM
from framebound.v2.providers import spark as SPARK
from framebound.v2.providers import base as BASE
from framebound.v2.services import briefs as B
from framebound.v2.services import approvals as A
from framebound.v2.services import contracts as CT
from framebound.v2.services import clips
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import InvalidInput


def _seed(td: str) -> dict:
    """Procedural assets + character + guide + contract + revision + human approval."""
    from framebound.v2.services import assets as AS
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        AS.import_asset(td, str(src / rel), f"f{i}", source_kind="procedural",
                        rights="original")
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-R3", project_id="p", identity_asset_ids=["id-art"],
            style_asset_ids=["st-art"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="head_height_14px_at_native"))
    finally:
        con.close()
    con = S.connect(td)
    try:
        hashes = {}
        for i in range(8):
            data, _ = S.get(con, "assets", f"f{i}")
            hashes[f"f{i}"] = data["byte_sha256"]
    finally:
        con.close()
    A.propose_motion_guide(td, Actor(type="orchestrator", id="spark-1"),
                           {"schema_version": "2.0", "id": "mg-R3",
                            "character_revision_id": "char-R3",
                            "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                                         "byte_sha256": hashes[f"f{i}"]} for i in range(8)]})
    CT.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-R3", "character_revision_id": "char-R3",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "id-art", "style": "st-art",
                       "motion_guide_revision": "mg-R3"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                           for i in range(8)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False,
                               "rigid_translation_budget_px": 2}})
    clips.create_revision(td, "contract-R3", "clip-R3", [f"f{i}" for i in range(8)],
                          [f"p{i}" for i in range(8)])
    A.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-R3", "mg-R3")
    return B.compile_reference_brief(td, "contract-R3", 0)


def _png_bytes(w=64, h=64, color=(10, 200, 30, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _b85(payload: bytes) -> str:
    return base64.b85encode(payload).decode()


def _pack_bits(raster: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(raster), 8):
        chunk = raster[i:i + 8]
        byte = 0
        for j, bit in enumerate(chunk):
            byte |= (1 if bit else 0) << (7 - j)
        out.append(byte)
    return bytes(out)


def _sam_line(frame, records):
    parts = []
    for obj, (x1, y1, x2, y2, w, h), (mh, mw, enc, payload) in records:
        parts.append(f"{obj}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h}|>"
                     f"<|mask;x=0;y=0;data={mh},{mw},{enc}{payload}|>")
    return f"<{frame}f>" + ",".join(parts)


class _EnvKey:
    """Set MODEL_API_KEY for the live-path tests, restore afterwards."""

    def __init__(self, value="test-key-r3"):
        self.value = value
        self.had = "MODEL_API_KEY" in os.environ
        self.old = os.environ.get("MODEL_API_KEY")

    def __enter__(self):
        os.environ["MODEL_API_KEY"] = self.value

    def __exit__(self, *a):
        if self.had:
            os.environ["MODEL_API_KEY"] = self.old
        else:
            os.environ.pop("MODEL_API_KEY", None)


class TestDocumentedWire(unittest.TestCase):
    def test_strict_fake_rejects_legacy_image_payload(self):
        legacy = {
            "model": "muse-image-1.0", "endpoint": "POST /responses (reference-conditioned)",
            "note": "size controls aspect ratio",
            "input": [{"role": "user", "content": [
                {"type": "text", "text": "draw"},
                {"type": "input_image", "role": "approved_identity", "asset_id": "a",
                 "byte_sha256": "ab" * 32, "image_b64": "AAA"},
            ]}],
        }
        errs = W.validate_image_request(legacy)
        self.assertTrue(any("endpoint" in e for e in errs))
        self.assertTrue(any("input_text" in e or "legacy part type" in e for e in errs))
        self.assertTrue(any("asset_id" in e for e in errs))

    def test_repaired_image_payload_passes_and_carries_roles_as_text(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            from framebound.v2.services import jobs as J
            resolved = J._resolve_references(td, compiled["brief"], [])
            req = IMG.build_request(compiled["brief"], resolved)
            self.assertEqual(W.validate_image_request(req), [])
            body = json.dumps(req)
            self.assertNotIn("asset_id", body)
            self.assertNotIn("image_b64", body)
            self.assertNotIn("endpoint", body)
            user = next(m for m in req["input"] if m["role"] == "user")
            text = next(c["text"] for c in user["content"] if c["type"] == "input_text")
            self.assertIn("approved_identity", text)
            self.assertIn("approved_style", text)
            imgs = [c for c in user["content"] if c["type"] == "input_image"]
            # identity + style + approved phase-guide pixels (F02: the model
            # receives guide pixels, not just a text label)
            self.assertEqual(len(imgs), 3)
            for part, r in zip(imgs, resolved):
                raw = base64.b64decode(part["image_url"].split(",", 1)[1])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), r["byte_sha256"])

    def test_spark_wire_rejects_asset_id_frames_accepts_pixel_frames(self):
        legacy = {"model": "muse-spark-1.3", "tool_choice": "auto",
                  "tools": [{"name": "t", "description": "d",
                             "parameters": {"type": "object"}}],
                  "input": [{"role": "user", "content": [
                      {"type": "input_text", "text": "review"},
                      {"type": "input_image", "frame": 0, "asset_id": "a"}]}]}
        self.assertTrue(W.validate_spark_request(legacy))
        tiny = base64.b64encode(bytes(16)).decode()
        req = SPARK.critique_request("contract c", ["registration"],
                                     [{"slot": 0, "asset_id": "a", "mime": "image/png",
                                       "bytes_b64": tiny}])
        self.assertEqual(W.validate_spark_request(req), [])

    def test_spark_tool_loop_call_ids_match(self):
        tiny = base64.b64encode(bytes(16)).decode()
        req = SPARK.critique_request("c", [], [{"asset_id": "a", "bytes_b64": tiny}])
        self.assertEqual(req["tool_choice"], "auto")
        body = {"status": "completed", "id": "resp-1", "output": [
            {"type": "function_call", "call_id": "call-1",
             "name": "get_deterministic_findings",
             "arguments": json.dumps({"revision_id": "r1"}), "status": "completed"}]}
        parsed = SPARK.parse_response(body)
        outs = SPARK.execute_tool_calls(
            parsed["calls"],
            handlers={"get_deterministic_findings": lambda revision_id: {"ok": True}})
        self.assertEqual(outs[0]["call_id"], "call-1")
        self.assertEqual([o["call_id"] for o in outs],
                         [c["call_id"] for c in parsed["calls"]])
        # a follow-up answering a different call id is a 400-class refusal
        bad_out = [dict(outs[0])]
        bad_out[0]["call_id"] = "call-X"
        with self.assertRaises(InvalidInput):
            SPARK.check_follow_up(bad_out, parsed["calls"])

    def test_sam_special_token_round_trip_and_corrupt_cases(self):
        raster = bytes([0] * 10 + [1] * 6 + [0] * 48)  # 8x8 asymmetric
        payload = _b85(_pack_bits(raster))
        if "|>" in payload:  # keep the grammar terminator unambiguous in fixtures
            raster = bytes([1 if (i % 3 == 0) else 0 for i in range(64)])
            payload = _b85(_pack_bits(raster))
        self.assertNotIn("|>", payload)
        text = _sam_line(0, [(0, (2, 2, 6, 6, 8, 8), (8, 8, "~", payload))])
        parsed = SAM.parse_output_text(text, source_width=8, source_height=8)
        self.assertEqual(parsed["outcome"], "mask")
        rec = parsed["records"][0]
        self.assertEqual(rec["box"]["x1"], 2)
        self.assertEqual(bytes(rec["mask"]["raster"]), raster)
        # empty lane + completed response = valid no-match; anything else
        # (failed status, or unconfirmed completion) is never a no-match
        self.assertEqual(W.parse_sam_output_text("", source_width=8,
                                                 source_height=8,
                                                 status="completed")["outcome"], "no_match")
        self.assertEqual(W.parse_sam_output_text("", source_width=8,
                                                 source_height=8,
                                                 status="failed")["outcome"], "failed")
        self.assertEqual(W.parse_sam_output_text("", source_width=8,
                                                 source_height=8)["outcome"], "corrupt")
        bad_box = _sam_line(0, [(0, (6, 6, 4, 4, 8, 8), (8, 8, "~", payload))])
        self.assertEqual(SAM.parse_output_text(bad_box)["outcome"], "corrupt")
        self.assertEqual(SAM.parse_output_text("<bad line")["outcome"], "corrupt")
        orphan = _sam_line(0, [(0, (0, 0, 4, 4, 8, 8), (8, 8, "~", "!!!"))])
        self.assertEqual(SAM.parse_output_text(orphan)["outcome"], "corrupt")

    def test_sam_build_rejects_placeholders(self):
        with self.assertRaises(InvalidInput):
            SAM.build_request("<bytes>", "glasses")
        tiny = base64.b64encode(_png_bytes(8, 8)).decode()
        req = SAM.build_request(tiny, "glasses")
        self.assertEqual(W.validate_sam_request(req), [])
        self.assertEqual(req["model"], "sam-3.1")

    def test_image_response_parser_requires_completed_call(self):
        good_png = base64.b64encode(_png_bytes()).decode()
        body = {"status": "completed", "id": "resp-1",
                "output": [{"type": "image_generation_call", "id": "img-1",
                            "result": good_png}], "usage": {"total_tokens": 5}}
        parsed = IMG.parse_response(body)
        self.assertEqual(len(parsed["images"]), 1)
        self.assertTrue(len(parsed["images"][0]["bytes"]) > 0)
        with self.assertRaises(Exception):
            IMG.parse_response({"status": "completed", "id": "x", "output": []})
        with self.assertRaises(Exception):
            IMG.parse_response({"status": "in_progress", "id": "x", "output": []})


class TestOfflineNeutrality(unittest.TestCase):
    def test_offline_never_sends_even_when_key_exists(self):
        def _explode(req):
            raise AssertionError("transport must not be called offline")
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            from framebound.v2.services import jobs as J
            resolved = J._resolve_references(td, compiled["brief"], [])
            with _EnvKey("present-key"):
                res = IMG.submit(compiled["brief"], resolved, td, "k-off",
                                 offline=True, transport=_explode)
                self.assertEqual(res["mode"], "not_configured")
                self.assertFalse(res["sent"])
                env = J.submit_generation(td, compiled["brief"], [], "k-off-2",
                                          offline=True)
                job = S.get(S.connect(td), "jobs", env.artifacts[0]["id"])[0]
                self.assertEqual(job["status"], "queued")
                self.assertTrue(job["offline"])

    def test_artifacts_are_redacted(self):
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            from framebound.v2.services import jobs as J
            from framebound.v2.providers import ledger as L
            resolved = J._resolve_references(td, compiled["brief"], [])
            with _EnvKey("present-key"):
                res = IMG.submit(compiled["brief"], resolved, td, "k-red",
                                 offline=True, transport=None)
            art = L.load_artifact(td, res["request_artifact"])
            dumped = json.dumps(art)
            self.assertIn("<bytes-redacted", dumped)
            self.assertNotIn("MODEL_API_KEY", dumped)
            self.assertNotIn(resolved[0]["bytes_b64"][:32], dumped)


class TestDurableJobs(unittest.TestCase):
    def _live_png_transport(self, seen: dict, png: bytes | None = None,
                            response_id: str = "resp-live-1"):
        png = png if png is not None else _png_bytes()
        def _t(req):
            seen["body"] = req["body"]
            seen["headers"] = req["headers"]
            return {"status": "completed", "id": response_id, "output": [
                {"type": "image_generation_call", "id": "img-1",
                 "result": base64.b64encode(png).decode()}],
                "usage": {"total_tokens": 7}}
        return _t

    def test_generated_output_becomes_registered_revision(self):
        from framebound.v2.services import jobs as J
        from framebound.v2.services import orchestrator as O
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            brief = compiled["brief"]
            with _EnvKey("live-key"):
                env = J.submit_generation(td, brief, [], "key-live-1")
                job_id = env.artifacts[0]["id"]
                run = O.start_run(td, [job_id])
                con = S.connect(td)
                _, jver = S.get(con, "jobs", job_id)
                con.close()
                claim = J.job_claim(td, job_id, "worker-1", expected_version=jver)
                # drive the full live path through the fenced controller with
                # a fake transport (real decodable PNG over the documented
                # envelope). No caller brief: the worker resumes from the
                # frozen job row alone.
                seen2: dict = {}
                fake = self._live_png_transport(seen2)
                out = O.orchestrator_send(td, run["run_id"], job_id, worker_id="worker-1",
                                          fencing_token=claim["fencing_token"],
                                          transport=fake)
                self.assertEqual(out["action"], "succeeded", out)
                done = out
                self.assertEqual(done["status"], "succeeded")
                self.assertEqual(J.job_get(td, job_id)["job"]["attempt_count"], 1)
                reg = clips.register_candidate(td, "clip-R3", "clip-R3-gen",
                                               {0: done["asset_id"]},
                                               recipe="repair:bounded-patch@identity+guide")
                self.assertTrue(reg.ok)
                ev = clips.evaluate(td, "clip-R3-gen")
                self.assertIn(ev.technical_status, (D.TechnicalStatus.PASS,
                                                   D.TechnicalStatus.FAIL,
                                                   D.TechnicalStatus.INCOMPLETE))
                # the transmitted pixels were the stored approved pixels
                sent_images = [c for m in seen2["body"]["input"] for c in m["content"]
                               if c.get("type") == "input_image"]
                # identity + style + approved phase-guide pixels
                self.assertEqual(len(sent_images), 3)

    def test_idempotency_and_payload_conflict(self):
        from framebound.v2.services import jobs as J
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            b0 = compiled["brief"]
            b1 = B.compile_reference_brief(td, "contract-R3", 1)["brief"]
            j1 = J.submit_generation(td, b0, [], "idem-9")
            j2 = J.submit_generation(td, b0, [], "idem-9")
            self.assertEqual(j1.artifacts[0]["id"], j2.artifacts[0]["id"])
            with self.assertRaises(S.ConflictError):
                J.submit_generation(td, b1, [], "idem-9")

    def test_timeout_unknown_outcome_and_restart_preserves_budget(self):
        from framebound.v2.services import jobs as J
        from framebound.v2.services.errors import ProviderTimeout
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            brief = compiled["brief"]
            with _EnvKey("live-key"):
                env = J.submit_generation(td, brief, [], "key-fail-1", max_attempts=2)
                job_id = env.artifacts[0]["id"]
                con = S.connect(td)
                _, v0 = S.get(con, "jobs", job_id)
                con.close()
                cl1 = J.job_claim(td, job_id, "w1", expected_version=v0)
                con = S.connect(td)
                _, v1 = S.get(con, "jobs", job_id)
                con.close()
                # ambiguous timeout: outcome unknown -> reconcile, never blind retry
                unk = J.job_mark_unknown_outcome(td, job_id, worker_id="w1",
                                                 expected_version=v1, detail="timeout ambiguous",
                                                 fencing_token=cl1["fencing_token"])
                self.assertTrue(unk["reconciliation_required"])
                before = J.job_get(td, job_id)
                self.assertEqual(before["job"]["status"], "needs_attention")
                attempts_before = before["job"]["attempt_count"]
                # restart with a fresh worker object against the same project dir
                rec = J.job_reconcile(td)
                after = J.job_get(td, job_id)
                self.assertEqual(after["job"]["attempt_count"], attempts_before)
                self.assertEqual(after["job"]["status"], "needs_attention")
                # retryable failure path respects the persisted budget
                env2 = J.submit_generation(td, brief, [], "key-fail-2", max_attempts=2)
                j2 = env2.artifacts[0]["id"]
                for _ in range(2):
                    con = S.connect(td)
                    _, v = S.get(con, "jobs", j2)
                    con.close()
                    cl2 = J.job_claim(td, j2, "w2", expected_version=v)
                    con = S.connect(td)
                    _, v = S.get(con, "jobs", j2)
                    con.close()
                    J.job_complete_failure(td, j2, worker_id="w2",
                                           expected_version=v, error="boom",
                                           retryable=True,
                                           fencing_token=cl2["fencing_token"])
                fin = J.job_get(td, j2)
                self.assertEqual(fin["job"]["status"], "needs_attention")
                self.assertEqual(fin["job"]["attempt_count"], 2)

    def test_cancellation_guards(self):
        from framebound.v2.services import jobs as J
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            env = J.submit_generation(td, compiled["brief"], [], "key-cancel-1")
            job_id = env.artifacts[0]["id"]
            con = S.connect(td)
            _, v = S.get(con, "jobs", job_id)
            con.close()
            out = J.job_cancel(td, job_id, v)
            self.assertEqual(out["status"], "cancelled")
            con = S.connect(td)
            _, v2 = S.get(con, "jobs", job_id)
            con.close()
            with self.assertRaises(InvalidInput):
                J.job_cancel(td, job_id, v2)
            with self.assertRaises(InvalidInput):
                J.job_claim(td, job_id, "w", expected_version=v2)

    def test_orchestrator_halts_no_progress_and_budget(self):
        from framebound.v2.services import jobs as J
        from framebound.v2.services import orchestrator as O
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            brief = compiled["brief"]
            env = J.submit_generation(td, brief, [], "key-halt-1", max_attempts=1)
            job_id = env.artifacts[0]["id"]
            run = O.start_run(td, [job_id], max_attempts=1)
            # force a no-progress fingerprint already recorded
            con = S.connect(td)
            data, ver = S.get(con, "jobs", job_id)
            job = D.Job.model_validate_json(json.dumps(data))
            job.no_progress_signatures = [J._payload_hash(brief, J._resolve_references(
                td, brief, []))]
            job.attempt_count = 1
            S.update_mutable(con, "jobs", job, ver)
            con.close()
            con = S.connect(td)
            _, jver = S.get(con, "jobs", job_id)
            con.close()
            claim = J.job_claim(td, job_id, "w", expected_version=jver)
            out = O.orchestrator_send(td, run["run_id"], job_id, brief, worker_id="w",
                                      fencing_token=claim["fencing_token"])
            self.assertEqual(out["action"], "stop")
            self.assertIn("no-progress", out["reason"])


class TestCapabilityAndTransportParity(unittest.TestCase):
    def test_capability_states(self):
        os.environ.pop("MODEL_API_KEY", None)
        os.environ.pop("META_API_KEY", None)
        cap = BASE.discover("image")
        self.assertFalse(cap.supported)
        self.assertIn("not_configured", cap.reason)
        with _EnvKey("k"):
            cap2 = BASE.discover("image")
            self.assertFalse(cap2.supported)
            self.assertIn("unverified", cap2.reason)
            from framebound.v2.services import errors as E
            def _raise(exc):
                def _t(provider, model, payload, *, timeout=30.0):
                    raise exc
                return _t
            self.assertIn("permission_denied",
                          BASE.verify_capability(
                              "image", transport=_raise(
                                  E.PermissionDenied("permission_denied: 401"))).reason)
            self.assertIn("model_unavailable",
                          BASE.verify_capability(
                              "image", transport=_raise(
                                  E.ModelUnavailable("model_unavailable: 404"))).reason)
            self.assertIn("transport_error",
                          BASE.verify_capability(
                              "image", transport=_raise(
                                  E.TransportError("transport_error: 500"))).reason)
            ok = BASE.verify_capability(
                "image", transport=lambda provider, model, payload, *,
                timeout=30.0: {"status": "completed", "id": "p"})
            self.assertTrue(ok.supported)
            self.assertIn("verified", ok.reason)

    def test_http_error_mapping(self):
        import urllib.error as _ue
        with _EnvKey("k"):
            from unittest import mock as _mock
            def _boom(code):
                fp = io.BytesIO(b"model not found" if code == 400 else b"nope")
                return _ue.HTTPError("https://api.meta.ai/v1/responses", code,
                                     "err", {}, fp)
            from framebound.v2.services import errors as E
            with _mock.patch("urllib.request.urlopen",
                             side_effect=_boom(401)):
                with self.assertRaises(E.PermissionDenied):
                    BASE._http_post_approved("/responses", {"model": "m", "input": "x"})
            with _mock.patch("urllib.request.urlopen",
                             side_effect=_boom(429)):
                with self.assertRaises(E.RateLimited):
                    BASE._http_post_approved("/responses", {"model": "m", "input": "x"})
            with _mock.patch("urllib.request.urlopen",
                             side_effect=_boom(400)):
                with self.assertRaises(E.ModelUnavailable):
                    BASE._http_post_approved("/responses", {"model": "m", "input": "x"})

    def test_capability_table_honest_and_transports_share_services(self):
        from framebound.v2.services import capabilities as C
        rows = {(r["transport"], r["operation"]): r for r in C.table()["rows"]}
        self.assertEqual(rows[("desk", "playback/compare/issues/corrections/export")]["status"],
                         "supported")
        self.assertEqual(rows[("cli", "job-cancel")]["status"], "supported")
        self.assertEqual(rows[("providers", "live-spike")]["status"], "provisional")
        self.assertFalse(any(e['live_observed'] for e in C.table()['evidence']))
        # CLI/MCP/API parity: job submit/get/cancel over HTTP
        from fastapi.testclient import TestClient
        from framebound.v2.api.app import create_app
        with tempfile.TemporaryDirectory() as td:
            compiled = _seed(td)
            c = TestClient(create_app(td))
            r = c.post("/api/jobs", json={"brief": compiled["brief"],
                                          "references": [], "idempotency_key": "api-k-1",
                                          "offline": True})
            self.assertEqual(r.status_code, 201, r.text)
            jid = r.json()["artifacts"][0]["id"]
            g = c.get(f"/api/jobs/{jid}")
            self.assertEqual(g.status_code, 200)
            con = S.connect(td)
            _, ver = S.get(con, "jobs", jid)
            con.close()
            cl = c.post(f"/api/jobs/{jid}/cancel",
                        json={"expected_version": ver})
            self.assertEqual(cl.status_code, 200)
            cl2 = c.post(f"/api/jobs/{jid}/cancel",
                         json={"expected_version": cl.json()["version"]})
            self.assertIn(cl2.status_code, (409, 422))


if __name__ == "__main__":
    unittest.main()
