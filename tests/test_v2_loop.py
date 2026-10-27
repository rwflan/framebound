"""WP3 gate: real MCP handshake, references reach the model, bounded repair, authz split."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.briefs import compile_brief
from framebound.v2.orchestration import BoundedLoop
from framebound.v2.providers import sam, spark
from framebound.v2.providers import image as img_provider
from framebound.v2.services import authz, packets, repair
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError, InvalidInput


def _contract_dict(holds=2):
    return {
        "schema_version": "2.0", "id": "contract-loop-01", "character_revision_id": "char-01",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * holds},
        "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-01"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                            for i in range(holds)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
    }


def _assets():
    mk = lambda aid: D.Asset(id=aid, byte_sha256="ab" * 32, pixel_sha256="cd" * 32,
                             mime="image/png", width=64, height=64,
                             source_kind="original", rights="original", eligible_roles=["identity"])
    return {"a-id": mk("a-id"), "a-st": mk("a-st")}


class AuthzSplit(unittest.TestCase):
    def test_orchestrator_cannot_write_review_decisions(self):
        model = Actor(type="orchestrator", id="spark-session-1")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(AuthorizationError):
                packets.record_review_event(td, model, {"id": "e1", "action": "approve_art",
                                                        "clip_revision_id": "r1"})
            with self.assertRaises(AuthorizationError):
                packets.record_review_event(td, model, {"id": "e2", "action": "resolve_issue",
                                                        "clip_revision_id": "r1"})
        # reviewer session works once the revision exists
        with tempfile.TemporaryDirectory() as td:
            con = S.connect(td)
            rev = D.ClipRevision(id="r1", contract_revision_id="c1", frame_instance_ids=["f1"])
            S.insert(con, rev)
            con.close()
            revw = Actor(type="reviewer", id="human-1")
            out = packets.record_review_event(td, revw, {"id": "e3", "action": "approve",
                                                         "clip_revision_id": "r1"})
            self.assertTrue(out.ok)


class BriefAuthority(unittest.TestCase):
    def test_brief_carries_reference_hashes(self):
        c = D.ClipContractRevision.model_validate(_contract_dict())
        b = compile_brief(c, 0, _assets(), {"a-id": {"approved": True}, "a-st": {"approved": True}},
                          {"pose-0": "guide:pose-0", "pose-1": "guide:pose-1"})
        roles = {i["role"] for i in b.bundle["inputs"]}
        self.assertIn("approved_identity", roles)
        self.assertIn("approved_style", roles)
        self.assertIn("phase_authority", roles)
        self.assertEqual(b.bundle["conditioning_sha256"], b.conditioning_sha256)

    def test_sole_reference_rejected(self):
        c = D.ClipContractRevision.model_validate(_contract_dict())
        assets = {"a-id": _assets()["a-id"]}
        with self.assertRaises(InvalidInput):
            compile_brief(c, 0, assets, {"a-id": {"approved": True}}, {"pose-0": "g", "pose-1": "g"})

    def test_rejected_candidate_forbidden(self):
        c = D.ClipContractRevision.model_validate(_contract_dict())
        assets = _assets()
        assets["a-st"] = D.Asset(id="a-st", byte_sha256="ab" * 32, mime="image/png",
                                 source_kind="generated", rights="original", eligible_roles=["rejected"])
        with self.assertRaises(InvalidInput):
            compile_brief(c, 0, assets, {"a-id": {"approved": True}, "a-st": {"approved": True, "rejected": True}},
                          {"pose-0": "g", "pose-1": "g"})


class ProviderHonesty(unittest.TestCase):
    def test_offline_image_submit_records_request_fabricates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            brief = {"instruction": "draw", "conditioning_sha256": "00" * 32}
            refs = [{"role": "approved_identity", "asset_id": "a-id", "byte_sha256": "ab" * 32,
                     "bytes_b64": "iVBORw0KGgo="},
                    {"role": "approved_style", "asset_id": "a-st", "byte_sha256": "ab" * 32,
                     "bytes_b64": "iVBORw0KGgo="}]
            res = img_provider.submit(brief, refs, td, "idem-1")
            self.assertEqual(res["mode"], "not_configured")
            self.assertFalse(res["sent"])
            self.assertNotIn("image_b64", json.dumps(res))

    def test_references_required_not_paths(self):
        with self.assertRaises(InvalidInput):
            img_provider.build_request({"instruction": "x"}, [])
        # role-labeled pixels are what reach the model
        req = img_provider.build_request({"instruction": "x"}, [
            {"role": "approved_identity", "asset_id": "a", "byte_sha256": "ab" * 32, "bytes_b64": "AAA"},
            {"role": "approved_style", "asset_id": "b", "byte_sha256": "ab" * 32, "bytes_b64": "BBB"}])
        roles = [c.get("role") for c in req["input"][1]["content"] if isinstance(c, dict) and "role" in c]
        self.assertIn("approved_identity", roles)

    def test_sam_decode_outcomes_explicit(self):
        self.assertEqual(sam.decode_mask({}, 8, 8)["outcome"], "no_match")
        self.assertEqual(sam.decode_mask({"mask_b64": "!!!notbase64!!!"}, 8, 8)["outcome"], "corrupt")
        import base64
        self.assertEqual(sam.decode_mask(
            {"mask_b64": base64.b64encode(bytes(64)).decode()}, 8, 8)["outcome"], "empty")
        self.assertEqual(sam.decode_mask(
            {"mask_b64": base64.b64encode(bytes([255]) * 64).decode()}, 8, 8)["outcome"], "full")
        odd = sam.decode_mask({"mask_b64": base64.b64encode(bytes([1] * 10)).decode()}, 8, 8)
        self.assertEqual(odd["outcome"], "corrupt")
        fb = sam.alpha_fallback(10, 8, 8)
        self.assertEqual(fb["outcome"], "offline-alpha")
        self.assertIn("NOT a SAM mask", fb["reason"])

    def test_spark_offline_is_advisory(self):
        with tempfile.TemporaryDirectory() as td:
            res = spark.submit_critique("contract", ["phase"], [{"slot": 0, "asset_id": "a"}], td)
            # ^ signature: (contract_summary, fault_codes, frame_refs, project_dir)
            self.assertEqual(res["mode"], "not_configured")


class BoundedRepair(unittest.TestCase):
    def _evals(self):
        mk = lambda fails: D.Evaluation(
            id=f"e-{len(fails)}", clip_revision_id="r",
            evidence_manifest_sha256="ff" * 32, analyzer_version="v", dependency_lock_id="d",
            results=[D.CheckResult(constraint_id=c, scope="s", outcome="fail" if c in fails else "pass",
                                   reason="calibrated test fixture with explicit reason")
                     for c in ("support", "torso_span")],
            technical_status=D.TechnicalStatus.FAIL if fails else D.TechnicalStatus.PASS,
            coverage_status=D.CoverageStatus.COMPLETE)
        return mk({"support", "torso_span"}), mk(set())

    def test_budget_stops_at_three(self):
        base, _ = self._evals()
        for i in range(3):
            plan = repair.plan(base, ["support"], "mask-1", [], attempt_count=i)
            self.assertNotIn("needs_attention", plan)
        plan = repair.plan(base, ["support"], "mask-1", [], attempt_count=3)
        self.assertTrue(plan["needs_attention"])

    def test_regression_rejected(self):
        base = D.Evaluation(
            id="e-b", clip_revision_id="r", evidence_manifest_sha256="ff" * 32,
            analyzer_version="v", dependency_lock_id="d",
            results=[D.CheckResult(constraint_id="support", scope="s", outcome="fail", reason="support missing, explicit"),
                     D.CheckResult(constraint_id="torso_span", scope="s", outcome="pass", reason="span within bound")],
            technical_status=D.TechnicalStatus.FAIL, coverage_status=D.CoverageStatus.COMPLETE)
        cand = D.Evaluation(
            id="e-c", clip_revision_id="r2", evidence_manifest_sha256="ee" * 32,
            analyzer_version="v", dependency_lock_id="d",
            results=[D.CheckResult(constraint_id="support", scope="s", outcome="pass", reason="support restored"),
                     D.CheckResult(constraint_id="torso_span", scope="s", outcome="fail", reason="span regressed")],
            technical_status=D.TechnicalStatus.FAIL, coverage_status=D.CoverageStatus.COMPLETE)
        out = repair.evaluate_selection(base, cand, ["support"])
        self.assertFalse(out["selected"])
        self.assertIn("regression", out["reason"])

    def test_subjective_path_needs_human(self):
        clean = D.Evaluation(
            id="e-clean", clip_revision_id="r", evidence_manifest_sha256="ff" * 32,
            analyzer_version="v", dependency_lock_id="d",
            results=[D.CheckResult(constraint_id="support", scope="s", outcome="pass", reason="support present")],
            technical_status=D.TechnicalStatus.PASS, coverage_status=D.CoverageStatus.COMPLETE)
        out = repair.evaluate_selection(clean, clean, [], subjective=True)
        self.assertTrue(out["selected"])
        self.assertTrue(out["awaiting_human_comparison"])

    def test_no_progress_signature_stops(self):
        base, good = self._evals()
        sig = repair.no_progress_signature(["support"], ["hash1"], {})
        out = repair.evaluate_selection(base, good, ["support"], candidate_hashes=["hash1"],
                                        prior_signatures=[sig])
        self.assertTrue(out.get("needs_attention"))


class LoopController(unittest.TestCase):
    def test_stops_at_review_and_budget(self):
        loop = BoundedLoop()
        self.assertEqual(loop.next_step("awaiting_review", ["support"])["action"], "stop")
        for _ in range(3):
            self.assertEqual(loop.next_step("repairing", ["support"])["action"], "attempt")
        self.assertEqual(loop.next_step("repairing", ["support"])["action"], "needs_attention")
        self.assertEqual(loop.observe_result("sig-new")["action"], "continue")
        self.assertEqual(loop.observe_result("sig-new")["action"], "needs_attention")


class RealMCPHandshake(unittest.TestCase):
    def test_stdio_handshake_lists_and_calls_tools(self):
        async def go():
            import sys as _sys
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp.client.session import ClientSession
            with tempfile.TemporaryDirectory() as td:
                params = StdioServerParameters(command=_sys.executable,
                                               args=["-m", "framebound", "v2-mcp", "--project", td])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        names = {t.name for t in tools.tools}
                        self.assertIn("clip_evaluate", names)
                        self.assertIn("brief_compile", names)
                        res = await session.call_tool("doctor", {})
                        text = res.content[0].text if res.content else ""
                        self.assertIn("2.0", text)
                        res2 = await session.call_tool("project_get", {})
                        self.assertIn("summary", (res2.content[0].text if res2.content else ""))
            return True
        self.assertTrue(asyncio.run(go()))


if __name__ == "__main__":
    unittest.main()
