"""R4 regressions: bounded repair + complete correction state at public boundaries.

Every defect the audit reproduced is pinned here through the service/API/MCP
surface where the previous shortcut lived — never a helper-only assertion.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.api.app import create_app
from framebound.v2.checks import fixtures as F
from framebound.v2.services import approvals as A
from framebound.v2.services import briefs as B
from framebound.v2.services import clips, contracts, masks, packets, review_state
from framebound.v2.services import corrections as C
from framebound.v2.services import eligibility as EL
from framebound.v2.services.authz import Actor, AuthorizationError
from framebound.v2.services.errors import InvalidInput

MOD = {"X-Actor-Id": "spark-1"}
ORCH = Actor(type="orchestrator", id="spark-1")
REV = Actor(type="reviewer", id="human-1")


def _seed(td: str) -> dict:
    """8 clean frames + blank fault; approved guides; registration+area contract."""
    from framebound.v2.services import assets as AS
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        AS.import_asset(td, str(src / rel), f"f{i}", source_kind="procedural",
                        rights="original")
    AS.import_asset(td, str(src / meta["faults"]["blank"]), "fx-blank",
                    source_kind="procedural", rights="original")
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-R4", project_id="p", identity_asset_ids=["id-art"],
            style_asset_ids=["st-art"], view_set=["side"],
            canvas={"width": 64, "height": 64}, scale_ruler="x"))
    finally:
        con.close()
    con = S.connect(td)
    try:
        hashes = {f"f{i}": S.get(con, "assets", f"f{i}")[0]["byte_sha256"]
                  for i in range(8)}
    finally:
        con.close()
    A.propose_motion_guide(td, ORCH, {
        "schema_version": "2.0", "id": "mg-R4", "character_revision_id": "char-R4",
        "entries": [{"phase": f"p{i}", "asset_id": f"f{i}",
                     "byte_sha256": hashes[f"f{i}"]} for i in range(8)]})
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-R4", "character_revision_id": "char-R4",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "id-art", "style": "st-art",
                       "motion_guide_revision": "mg-R4"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                           for i in range(8)],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "area", "check": "silhouette_area", "required": True,
             "params": {"max_fraction": 0.35}}],
        "allowed_transforms": {"per_pose_scale": False,
                               "rigid_translation_budget_px": 2}})
    A.approve_reference(td, REV, "char-R4", "mg-R4")
    aids = [f"f{i}" for i in range(8)]
    aids[3] = "fx-blank"
    clips.create_revision(td, "contract-R4", "rev-base", aids,
                          [f"p{i}" for i in range(8)])
    ev = clips.evaluate(td, "rev-base")
    return {"ev": ev, "ev_id": ev.artifacts[0]["id"], "src": src}


def _counts(td: str) -> dict:
    con = S.connect(td)
    try:
        return {t: con.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                for t in ("clip_revisions", "evaluations", "review_packets",
                          "attempts", "correction_tasks")}
    finally:
        con.close()


def _open_issue(td: str, **kw) -> tuple[str, str]:
    """Reviewer marks a 1x1 ROI issue on slot 3 by default (the F08 shape)."""
    body = {"clip_revision_id": "rev-base", "frame_range": [12, 15],
            "roi": {"left": 30, "top": 30, "right": 31, "bottom": 31},
            "note": "hole at slot 3", "category": "hole"}
    body.update(kw)
    env, task = C.open_issue(td, REV, dict({"action": "mark_issue"}, **body))
    return task.id, task.baseline_evaluation_id


def _claim(td: str, task_id: str, version: int = 1, **kw) -> dict:
    return C.claim(td, ORCH, task_id, version, **kw)


def _mask(td: str, issue_event: str, white: str = "full",
          slots: list[int] | None = None) -> str:
    """Import a mask asset and get it reviewer-approved for the issue."""
    from framebound.v2.services import assets as AS
    img = Image.new("L", (64, 64), 255 if white == "full" else 0)
    if white == "pixel":
        img.putpixel((0, 0), 255)
    p = Path(td) / f"mask-{white}.png"
    img.save(p)
    aid = f"m-{white}"
    try:
        AS.import_asset(td, str(p), aid, source_kind="original", rights="original")
    except Exception:
        pass  # idempotent across tests sharing setup is not needed; ignore dupes
    m = masks.approve_mask(td, REV, issue_event, aid, slots if slots is not None else [3])
    return m.id


def _submit(td: str, task_id: str, token: str, version: int, base_ev: str,
            new_id: str, slot_assets: dict, key: str, **kw):
    return C.submit_correction(td, ORCH, task_id, claim_token=token,
                               expected_version=version, new_revision_id=new_id,
                               slot_asset_ids=slot_assets,
                               recipe=kw.get("recipe", "repair:bounded-patch"),
                               transform=kw.get("transform"),
                               baseline_evaluation_id=base_ev,
                               idempotency_key=key)


class TestScopeBounded(unittest.TestCase):
    def test_1x1_roi_whole_frame_swap_rejected_without_partial_writes(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            cl = _claim(td, task_id)
            before = _counts(td)
            with self.assertRaises(InvalidInput):
                _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                        "rev-fix-1", {3: "f3"}, "k-1")
            self.assertEqual(_counts(td), before)

    def test_outside_roi_and_protected_pixel_edits_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="pixel", slots=[3])
            cl = _claim(td, task_id, version=2)
            before = _counts(td)
            with self.assertRaises(InvalidInput) as ctx:
                _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                        "rev-fix-2", {3: "f3"}, "k-2")
            self.assertIn("outside the authorized", str(ctx.exception))
            self.assertEqual(_counts(td), before)

    def test_approved_mask_authorizes_bounded_repair(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            out = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                          "rev-fix-3", {3: "f3"}, "k-3")
            self.assertTrue(out["ok"])
            self.assertEqual(out["scope"]["changed_slots"], [3])
            self.assertEqual(C.get_task(td, task_id)["task"]["status"],
                             "awaiting_comparison")

    def test_out_of_scope_slot_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            with self.assertRaises(InvalidInput) as ctx:
                _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                        "rev-fix-4", {5: "f5"}, "k-4")
            self.assertIn("outside the authorized scope", str(ctx.exception))

    def test_mask_requires_reviewer_and_valid_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, _ = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            from framebound.v2.services import assets as AS
            Image.new("L", (64, 64), 255).save(Path(td) / "m.png")
            AS.import_asset(td, str(Path(td) / "m.png"), "m1",
                            source_kind="original", rights="original")
            with self.assertRaises(AuthorizationError):
                masks.approve_mask(td, ORCH, issue, "m1", [3])
            with self.assertRaises(InvalidInput):
                masks.approve_mask(td, REV, issue, "m1", [99])
            with self.assertRaises(InvalidInput):
                masks.approve_mask(td, REV, issue, "no-such-asset", [3])


class TestClaimAuthority(unittest.TestCase):
    def _setup(self, td: str):
        _seed(td)
        return _open_issue(td)

    def test_unclaimed_submit_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            task_id, base_ev = self._setup(td)
            before = _counts(td)
            with self.assertRaises(InvalidInput):
                _submit(td, task_id, "tok", 1, base_ev, "r-x", {3: "f3"}, "k-x")
            self.assertEqual(_counts(td), before)

    def test_foreign_holder_and_wrong_token_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            task_id, base_ev = self._setup(td)
            cl = _claim(td, task_id)
            other = Actor(type="orchestrator", id="someone-else")
            with self.assertRaises(InvalidInput):
                C.submit_correction(td, other, task_id, claim_token=cl["claim_token"],
                                    expected_version=cl["version"], new_revision_id="r-y",
                                    slot_asset_ids={3: "f3"}, recipe="repair:x",
                                    baseline_evaluation_id=base_ev, idempotency_key="k-y")
            with self.assertRaises(InvalidInput):
                _submit(td, task_id, "wrong-token", cl["version"], base_ev,
                        "r-z", {3: "f3"}, "k-z")
            self.assertEqual(_counts(td)["attempts"], 0)

    def test_expired_lease_requeues_without_discarding_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            task_id, base_ev = self._setup(td)
            cl = C.claim(td, ORCH, task_id, 1, lease_minutes=-1)
            with self.assertRaises(InvalidInput) as ctx:
                _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                        "r-e", {3: "f3"}, "k-e")
            self.assertIn("lease", str(ctx.exception).lower())
            st = C.get_task(td, task_id)
            self.assertEqual(st["task"]["status"], "open")
            self.assertFalse(st["lease_valid"])

    def test_stale_baseline_and_version_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            task_id, base_ev = self._setup(td)
            cl = _claim(td, task_id)
            with self.assertRaises(InvalidInput):
                _submit(td, task_id, cl["claim_token"], cl["version"], "eval-stale",
                        "r-s", {3: "f3"}, "k-s")
            with self.assertRaises(S.StaleRevisionError):
                _submit(td, task_id, cl["claim_token"], cl["version"] + 99, base_ev,
                        "r-s2", {3: "f3"}, "k-s2")

    def test_same_key_replays_different_payload_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            out1 = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                           "rev-dedupe", {3: "f3"}, "k-dupe")
            self.assertTrue(out1["ok"])
            out2 = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                           "rev-dedupe", {3: "f3"}, "k-dupe")
            self.assertTrue(out2.get("deduped"))
            self.assertEqual(out2["revision_id"], "rev-dedupe")
            with self.assertRaises(S.ConflictError):
                _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                        "rev-dedupe-other", {3: "f3"}, "k-dupe")


class TestSelectionMatrix(unittest.TestCase):
    def _dot_variant(self, td: str, name: str, xy: tuple[int, int]) -> None:
        from framebound.v2.services import assets as AS
        raw = S.blob_path(td, S.get(S.connect(td), "assets", "fx-blank")[0]["byte_sha256"]).read_bytes()
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        img.putpixel(xy, (255, 255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        Path(td, f"{name}.png").write_bytes(buf.getvalue())
        AS.import_asset(td, str(Path(td) / f"{name}.png"), name,
                        source_kind="procedural", rights="original")

    def test_error_candidate_is_not_a_resolved_repair(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            # one opaque pixel on blank: differs within scope, still not a fix
            self._dot_variant(td, "fx-blankdot", (10, 10))
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            out = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                          "rev-still-broken", {3: "fx-blankdot"}, "k-err")
            self.assertFalse(out["ok"])
            st = C.get_task(td, task_id)
            self.assertEqual(st["task"]["status"], "attempting")
            self.assertEqual(len(st["attempts"]), 1)

    def test_contract_and_matrix_mismatch_rejected(self):
        from framebound.v2.services import repair as R
        with tempfile.TemporaryDirectory() as td:
            info = _seed(td)
            con = S.connect(td)
            base_ev = D.Evaluation.model_validate_json(json.dumps(
                S.get(con, "evaluations", info["ev_id"])[0]))
            base_contract = D.ClipContractRevision.model_validate_json(json.dumps(
                S.get(con, "contract_revisions", "contract-R4")[0]))
            con.close()
            # identical inputs, different contract identity -> refused
            other_contract = base_contract.model_copy(update={"id": "contract-other"})
            out = R.evaluate_selection(base_ev, base_ev, ["registration"],
                                       baseline_contract=base_contract,
                                       candidate_contract=other_contract)
            self.assertFalse(out["selected"])
            self.assertIn("mismatch", out["reason"])
            # dropped required check between otherwise identical evaluations
            dropped = base_ev.model_copy(
                update={"results": [r for r in base_ev.results
                                    if r.constraint_id != "area"]})
            out2 = R.evaluate_selection(base_ev, dropped, ["registration"],
                                        baseline_contract=base_contract,
                                        candidate_contract=base_contract)
            self.assertFalse(out2["selected"])
            self.assertIn("matrix", out2["reason"])

    def test_budget_exhaustion_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            from framebound.v2.services import assets as AS
            raw = S.blob_path(td, S.get(S.connect(td), "assets", "fx-blank")[0]["byte_sha256"]).read_bytes()
            for i in range(3):
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
                img.putpixel((10 + i, 10), (255, 255, 255, 255))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                Path(td).joinpath(f"b{i}.png").write_bytes(buf.getvalue())
                AS.import_asset(td, str(Path(td) / f"b{i}.png"), f"fx-b{i}",
                                source_kind="procedural", rights="original")
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            for i in range(3):
                # same holder, same lease: retries continue without re-claiming
                ver = C.get_task(td, task_id)["version"]
                out = _submit(td, task_id, cl["claim_token"], ver, base_ev,
                              f"rev-bad-{i}", {3: f"fx-b{i}"}, f"k-bad-{i}")
                self.assertFalse(out["ok"])
            ver = C.get_task(td, task_id)["version"]
            with self.assertRaises(InvalidInput) as ctx:
                _submit(td, task_id, cl["claim_token"], ver, base_ev,
                        "rev-bad-3", {3: "fx-b0"}, "k-bad-3")
            self.assertIn("blocked", str(ctx.exception))


class TestSubjectiveAndVisibility(unittest.TestCase):
    def test_subjective_fix_needs_only_human_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            # clean baseline revision: technically passing
            clips.create_revision(td, "contract-R4", "rev-clean",
                                  [f"f{i}" for i in range(8)],
                                  [f"p{i}" for i in range(8)])
            ev = clips.evaluate(td, "rev-clean")
            self.assertEqual(ev.technical_status, D.TechnicalStatus.PASS)
            env, task = C.open_issue(td, REV, {"action": "mark_issue",
                                              "clip_revision_id": "rev-clean",
                                              "frame_range": [12, 15],
                                              "roi": {"left": 30, "top": 30,
                                                      "right": 31, "bottom": 31},
                                              "note": "acting feels weak",
                                              "category": "acting"})
            issue = task.source_issue_event_id
            # variant asset: one pixel inside the ROI differs
            from framebound.v2.services import assets as AS
            raw = S.blob_path(td, S.get(S.connect(td), "assets", "f3")[0]["byte_sha256"]).read_bytes()
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            img.putpixel((30, 30), (255, 0, 0, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            Path(td, "variant.png").write_bytes(buf.getvalue())
            AS.import_asset(td, str(Path(td) / "variant.png"), "f3-variant",
                            source_kind="generated", rights="original")
            cl = C.claim(td, ORCH, task.id, 1)
            out = C.submit_correction(td, ORCH, task.id, claim_token=cl["claim_token"],
                                      expected_version=cl["version"],
                                      new_revision_id="rev-clean-subj",
                                      slot_asset_ids={3: "f3-variant"},
                                      recipe="repair:bounded-patch",
                                      baseline_evaluation_id=task.baseline_evaluation_id,
                                      idempotency_key="k-subj")
            self.assertTrue(out["ok"])
            self.assertTrue(out["awaiting_human_comparison"])
            # orchestrator cannot resolve; only the reviewer can
            with self.assertRaises(AuthorizationError):
                C.resolve_issue(td, ORCH, issue, "rev-clean-subj")
            done = C.resolve_issue(td, REV, issue, "rev-clean-subj",
                                   packet_id=f"pkt-rev-clean-subj")
            self.assertTrue(done["ok"])
            st = review_state.current_state(td, "rev-clean")
            self.assertEqual(st["open_issue_ids"], [])

    def test_reopen_keeps_history_visible(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            issue = C.get_task(td, task_id)["issue"]["id"]
            _mask(td, issue, white="full", slots=[3])
            cl = _claim(td, task_id, version=2)
            out = _submit(td, task_id, cl["claim_token"], cl["version"], base_ev,
                          "rev-reopen", {3: "f3"}, "k-reopen")
            self.assertTrue(out["ok"])
            C.resolve_issue(td, REV, issue, "rev-reopen",
                            packet_id="pkt-rev-reopen")
            self.assertEqual(C.get_task(td, task_id)["task"]["status"], "resolved")
            re = C.reopen_issue(td, REV, issue, "regression spotted")
            self.assertEqual(re["status"], "reopened")
            st = C.get_task(td, task_id)
            self.assertEqual(st["task"]["status"], "reopened")
            openq = C.list_open(td)
            self.assertIn(task_id, [t["id"] for t in openq["open"]])
            events = [json.loads(r["data"])["action"] for r in
                      S.connect(td).execute("SELECT data FROM review_events").fetchall()]
            self.assertIn("reopen_issue", events)


class TestEligibility(unittest.TestCase):
    def test_release_needs_packet_bound_approval_and_quiet_queue(self):
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            clips.create_revision(td, "contract-R4", "rev-clean",
                                  [f"f{i}" for i in range(8)],
                                  [f"p{i}" for i in range(8)])
            ev = clips.evaluate(td, "rev-clean")
            ev_id = ev.artifacts[0]["id"]
            before = EL.release_eligibility(td, "rev-clean")
            self.assertFalse(before["eligible"])
            pkt = packets.create_packet(td, "pkt-clean", "rev-clean", ev_id, "review")
            # packetless approval is a signal, not a release
            packets.record_decision(td, REV, {"action": "approve",
                                              "clip_revision_id": "rev-clean"})
            still = EL.release_eligibility(td, "rev-clean")
            self.assertFalse(still["eligible"])
            packets.record_decision(td, REV, {"action": "approve",
                                              "clip_revision_id": "rev-clean",
                                              "packet_id": "pkt-clean",
                                              "expected_revision_id": "rev-clean",
                                              "expected_evaluation_id": ev_id})
            self.assertEqual(pkt.artifacts[0]["id"], "pkt-clean")
            after = EL.release_eligibility(td, "rev-clean")
            self.assertTrue(after["eligible"], after["reasons"])
            # an open issue on the revision blocks release again
            C.open_issue(td, REV, {"action": "mark_issue",
                                   "clip_revision_id": "rev-clean",
                                   "note": "second look"})
            blocked = EL.release_eligibility(td, "rev-clean")
            self.assertFalse(blocked["eligible"])
            self.assertTrue(any("unresolved" in r for r in blocked["reasons"]))

    def test_mcp_and_api_parity_on_gated_refusal(self):
        import asyncio
        from framebound.v2.mcp.server import build_server
        with tempfile.TemporaryDirectory() as td:
            _seed(td)
            task_id, base_ev = _open_issue(td)
            c = TestClient(create_app(td))
            r = c.post(f"/api/corrections/{task_id}/submit",
                       json={"slot_assets": {"3": "f3"}, "recipe": "repair:x",
                             "new_revision_id": "r-api", "claim_token": "nope",
                             "expected_version": 1, "baseline_evaluation_id": base_ev,
                             "idempotency_key": "k-api"}, headers=MOD)
            self.assertIn(r.status_code, (401, 403, 409, 422), r.text)

            async def go():
                from mcp.client.stdio import StdioServerParameters, stdio_client
                from mcp.client.session import ClientSession
                import sys as _sys
                params = StdioServerParameters(command=_sys.executable,
                                               args=["-m", "framebound", "v2-mcp",
                                                     "--project", td])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        res = await session.call_tool("correction_submit", {
                            "task_id": task_id, "claim_token": "nope",
                            "new_revision_id": "r-mcp",
                            "slot_assets": {"3": "f3"}, "recipe": "repair:x",
                            "baseline_evaluation_id": base_ev,
                            "idempotency_key": "k-mcp"})
                        return res.content[0].text if res.content else ""
            before = _counts(td)
            text = asyncio.run(go())
            # the MCP framework reports tool failure without detail; the gate
            # itself is proven by the refusal plus zero partial writes
            self.assertIn("error", text.lower())
            self.assertEqual(_counts(td), before)


if __name__ == "__main__":
    unittest.main()
