"""R1 regressions: real authority and transaction layer at public boundaries.

Every test hits the transport or service where the previous shortcut lived;
none asserts a value the implementation filled in for itself.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from framebound.v2 import domain as D
from framebound.v2 import storage as S
from framebound.v2.api.app import create_app
from framebound.v2.checks import fixtures as F
from framebound.v2.services import approvals as A
from framebound.v2.services import briefs as B
from framebound.v2.services import clips, contracts, packets, sessions as SN
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import InvalidInput

MOD = {"X-Actor-Id": "spark-1"}  # orchestrator: no session token, never a reviewer


def _seed_approval_project(td: str) -> dict:
    """Procedural assets + character + guide + contract. No approvals yet."""
    from framebound.v2.services import assets as AS
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    aid = {}
    for i, rel in enumerate(meta["clean"]):
        name = f"f{i}"
        AS.import_asset(td, str(src / rel), name, source_kind="procedural", rights="original")
        aid[name] = name
    AS.import_asset(td, str(src / meta["clean"][0]), "id-art",
                    source_kind="original", rights="original")
    AS.import_asset(td, str(src / meta["clean"][1]), "st-art",
                    source_kind="original", rights="original")
    con = S.connect(td)
    try:
        S.insert(con, D.CharacterRevision(
            id="char-R1", project_id="p", identity_asset_ids=["id-art"],
            style_asset_ids=["st-art"], view_set=["side"], canvas={"width": 64, "height": 64},
            scale_ruler="head_height_14px_at_native"))
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
    guide = {"schema_version": "2.0", "id": "mg-R1", "character_revision_id": "char-R1",
             "entries": [{"phase": f"p{i}", "asset_id": f"f{i}", "byte_sha256": hashes[f"f{i}"]}
                          for i in range(8)]}
    A.propose_motion_guide(td, Actor(type="orchestrator", id="spark-1"), guide)
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "contract-R1", "character_revision_id": "char-R1",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "id-art", "style": "st-art", "motion_guide_revision": "mg-R1"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                           for i in range(8)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    clips.create_revision(td, "contract-R1", "clip-R1", [f"f{i}" for i in range(8)],
                          [f"p{i}" for i in range(8)])
    ev = clips.evaluate(td, "clip-R1")
    return {"ev_id": ev.artifacts[0]["id"]}


def _reviewer_headers(td: str, reviewer_id: str = "human-1") -> dict:
    c = TestClient(create_app(td))
    pr = c.post("/api/reviewer/pair", json={"reviewer_id": reviewer_id})
    assert pr.status_code == 201, pr.text
    op = c.post("/api/reviewer/open", json={"pairing_code": pr.json()["pairing_code"]})
    assert op.status_code == 201, op.text
    return {"X-Session-Token": op.json()["session_token"]}


class TestStoredApprovalAuthority(unittest.TestCase):
    def test_cli_mcp_and_http_resolve_real_reference_approval(self):
        import asyncio
        with tempfile.TemporaryDirectory() as td:
            info = _seed_approval_project(td)
            # no approval yet: every transport must refuse, not invent authority
            from framebound.v2 import cli_commands as CC
            with self.assertRaises(InvalidInput):
                CC.dispatch(SimpleNamespace(cmd="brief-compile", contract_id="contract-R1",
                                            slot="0", project=td))
            with self.assertRaises(InvalidInput):
                B.compile_reference_brief(td, "contract-R1", 0)

            async def mcp_refused():
                import sys as _sys
                from mcp.client.stdio import StdioServerParameters, stdio_client
                from mcp.client.session import ClientSession
                params = StdioServerParameters(command=_sys.executable,
                                               args=["-m", "framebound", "v2-mcp", "--project", td])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        try:
                            res = await session.call_tool("brief_compile",
                                                          {"contract_id": "contract-R1", "slot": 0})
                        except Exception:
                            return True  # protocol-level refusal: also a refusal
                        return bool(res.is_error)  # tool-level refusal without stored approval
            self.assertTrue(asyncio.run(mcp_refused()))

            # reviewer pairs, approves through the stored flow; transports now succeed
            _reviewer_headers(td)
            from framebound.v2.services import approvals as AP
            out = AP.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-R1", "mg-R1")
            self.assertTrue(out.ok)
            got = CC.dispatch(SimpleNamespace(cmd="brief-compile", contract_id="contract-R1",
                                              slot="0", project=td))
            self.assertIn("approval_id", got)
            self.assertEqual(got["motion_guide_id"], "mg-R1")
            self.assertIn("sha256:", got["brief"]["inputs"][2]["source"])

            async def mcp_ok():
                import sys as _sys
                from mcp.client.stdio import StdioServerParameters, stdio_client
                from mcp.client.session import ClientSession
                params = StdioServerParameters(command=_sys.executable,
                                               args=["-m", "framebound", "v2-mcp", "--project", td])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        res = await session.call_tool("brief_compile",
                                                      {"contract_id": "contract-R1", "slot": 0})
                        if getattr(res, "is_error", False):
                            raise AssertionError(f"approved brief refused: {res.content}")
                        return True
            self.assertTrue(asyncio.run(mcp_ok()))

    def test_guide_phase_gap_is_not_bridged(self):
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            A.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-R1", "mg-R1")
            # guide with a missing phase cannot authorize that slot
            con = S.connect(td)
            try:
                gdata, _ = S.get(con, "motion_guides", "mg-R1")
                g = D.MotionGuide.model_validate_json(json.dumps(gdata))
                g.id = "mg-gap"
                g.entries = [e for e in g.entries if e.phase != "p3"]
                S.insert(con, g)
            finally:
                con.close()
            A.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-R1", "mg-R1")
            # latest approval still points at mg-R1 (complete); re-approving onto the gap guide
            # then briefing slot 3 must fail
            A.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-R1", "mg-gap")
            with self.assertRaises(InvalidInput):
                B.compile_reference_brief(td, "contract-R1", 3)
            # other slots still resolve against the gap guide's remaining phases
            ok = B.compile_reference_brief(td, "contract-R1", 0)
            self.assertEqual(ok["motion_guide_id"], "mg-gap")


class TestReviewerSessions(unittest.TestCase):
    def test_reviewer_role_cannot_be_self_asserted(self):
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            c = TestClient(create_app(td))
            # legacy header self-assertion is ignored: treated as orchestrator -> 403
            r = c.post("/api/issues", json={"clip_revision_id": "clip-R1", "note": "x"},
                       headers={"X-Actor-Type": "reviewer", "X-Actor-Id": "mallory"})
            self.assertEqual(r.status_code, 403, r.text)
            d = c.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-R1"},
                       headers={"X-Actor-Type": "reviewer", "X-Actor-Id": "mallory"})
            self.assertEqual(d.status_code, 403, d.text)
            # bogus token -> 401, not reviewer powers
            r2 = c.post("/api/issues", json={"clip_revision_id": "clip-R1", "note": "x"},
                        headers={"X-Session-Token": "deadbeef"})
            self.assertEqual(r2.status_code, 401, r2.text)
            # orchestrator cannot decide even with an id header
            d2 = c.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-R1"},
                        headers=MOD)
            self.assertEqual(d2.status_code, 403, d2.text)
            # genuine ceremony works
            REV = _reviewer_headers(td)
            r3 = c.post("/api/issues", json={"clip_revision_id": "clip-R1", "note": "real"},
                        headers=REV)
            self.assertEqual(r3.status_code, 201, r3.text)

    def test_pairing_code_is_single_use(self):
        with tempfile.TemporaryDirectory() as td:
            pr = SN.pair_reviewer(td, "human-1")
            SN.open_session(td, pr["pairing_code"])
            from framebound.v2.services.errors import AuthorizationError
            with self.assertRaises(AuthorizationError):
                SN.open_session(td, pr["pairing_code"])


class TestRelationshipValidation(unittest.TestCase):
    def _http_project(self, td: str):
        from framebound.v2.services import assets as AS
        src = Path(td) / "src"
        meta = F.build_cycle(src)
        for i, rel in enumerate(meta["clean"]):
            AS.import_asset(td, str(src / rel), f"f-clean-{i}", source_kind="procedural")
        AS.import_asset(td, str(src / meta["clean"][0]), "a-id", source_kind="procedural")
        AS.import_asset(td, str(src / meta["clean"][1]), "a-st", source_kind="procedural")
        contracts.propose_contract(td, {
            "schema_version": "2.0", "id": "contract-R1", "character_revision_id": "char-01",
            "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
            "canvas": {"width": 64, "height": 64, "units": "native_px"},
            "timing": {"ticks_per_second": 60, "holds": [4] * 8},
            "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-01"},
            "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"}
                               for i in range(8)],
            "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
            "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
        aids = [f"f-clean-{i}" for i in range(8)]
        clips.create_revision(td, "contract-R1", "clip-A", aids, [f"p{i}" for i in range(8)])
        AS.import_asset(td, str(src / meta["faults"]["phase"]), "f-wrong", source_kind="procedural")
        faulty = [f"f-clean-{i}" for i in range(8)]
        faulty[3] = "f-wrong"
        clips.create_revision(td, "contract-R1", "clip-B", faulty, [f"p{i}" for i in range(8)])
        ev = clips.evaluate(td, "clip-B")
        packets.create_packet(td, "pkt-B", "clip-B", ev.artifacts[0]["id"], "review B")

    def test_packet_revision_frame_and_issue_relationships_validated(self):
        with tempfile.TemporaryDirectory() as td:
            self._http_project(td)
            c = TestClient(create_app(td))
            REV = _reviewer_headers(td)
            # approval naming a packet that addresses a DIFFERENT revision is rejected
            d = c.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-A",
                                                "packet_id": "pkt-B"}, headers=REV)
            self.assertEqual(d.status_code, 422, d.text)
            # unknown packet rejected
            d2 = c.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-B",
                                                "packet_id": "pkt-nope"}, headers=REV)
            self.assertEqual(d2.status_code, 422, d2.text)
            # decision without any stored evaluation is rejected
            clips.create_revision(td, "contract-R1", "clip-C",
                                  [f"f-clean-{i}" for i in range(8)], [f"p{i}" for i in range(8)])
            d3 = c.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-C",
                                                "packet_id": "pkt-B"}, headers=REV)
            self.assertIn(d3.status_code, (404, 422), d3.text)
            # issue with a frame instance from another revision is rejected
            con = S.connect(td)
            try:
                fdata, _ = S.get(con, "frame_instances", "clip-A-fi-00")
            finally:
                con.close()
            r = c.post("/api/issues", json={"clip_revision_id": "clip-B", "packet_id": "pkt-B",
                                             "frame_instance_id": "clip-A-fi-00", "note": "x"},
                       headers=REV)
            self.assertEqual(r.status_code, 422, r.text)
            # frame_range beyond the contract ticks is rejected
            r2 = c.post("/api/issues", json={"clip_revision_id": "clip-B", "packet_id": "pkt-B",
                                              "frame_range": [0, 9000], "note": "x"}, headers=REV)
            self.assertEqual(r2.status_code, 422, r2.text)
            # ROI outside the canvas is rejected (F14: 9000px on a 64px canvas)
            r3 = c.post("/api/issues", json={"clip_revision_id": "clip-B", "packet_id": "pkt-B",
                                              "frame_range": [3, 5],
                                              "roi": {"left": 0, "top": 0, "right": 9000,
                                                      "bottom": 9000}, "note": "x"}, headers=REV)
            self.assertEqual(r3.status_code, 422, r3.text)
            # a valid issue records category + geometry, and retry is idempotent
            r4 = c.post("/api/issues", json={"id": "evt-fixed-1", "clip_revision_id": "clip-B",
                                              "packet_id": "pkt-B", "frame_range": [3, 5],
                                              "roi": {"left": 8, "top": 8, "right": 56,
                                                      "bottom": 60},
                                              "note": "torso pulse", "category": "torso-pulse"},
                        headers=REV)
            self.assertEqual(r4.status_code, 201, r4.text)
            r5 = c.post("/api/issues", json={"id": "evt-fixed-1", "clip_revision_id": "clip-B",
                                              "packet_id": "pkt-B", "frame_range": [3, 5],
                                              "roi": {"left": 8, "top": 8, "right": 56,
                                                      "bottom": 60},
                                              "note": "torso pulse", "category": "torso-pulse"},
                        headers=REV)
            self.assertEqual(r5.status_code, 201, r5.text)
            # same id, different action -> conflict, not silent overwrite
            d4 = c.post("/api/decisions", json={"id": "evt-fixed-1", "action": "approve",
                                                "clip_revision_id": "clip-B",
                                                "packet_id": "pkt-B"}, headers=REV)
            self.assertEqual(d4.status_code, 409, d4.text)
            # stale evaluation view is refused against server state
            d5 = c.post("/api/decisions", json={"action": "approve", "clip_revision_id": "clip-B",
                                                "packet_id": "pkt-B",
                                                "expected_evaluation_id": "ev-stale"},
                        headers=REV)
            self.assertEqual(d5.status_code, 409, d5.text)


class TestAtomicTransactions(unittest.TestCase):
    def test_atomic_issue_task_and_candidate_creation_with_fault_injection(self):
        from framebound.v2.services import corrections as C
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            actor = Actor(type="reviewer", id="human-1")
            # fault between the event and task inserts leaves neither row
            calls = {"n": 0}
            real_stage = S.stage

            def flaky(con, model):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("injected crash")
                return real_stage(con, model)
            S.stage = flaky
            try:
                with self.assertRaises(RuntimeError):
                    C.open_issue(td, actor, {"id": "evt-atomic-1", "clip_revision_id": "clip-R1",
                                             "note": "boom"})
            finally:
                S.stage = real_stage
            con = S.connect(td)
            try:
                self.assertEqual(con.execute(
                    "SELECT COUNT(*) AS n FROM review_events WHERE id='evt-atomic-1'").fetchone()["n"], 0)
                self.assertEqual(con.execute(
                    "SELECT COUNT(*) AS n FROM correction_tasks WHERE id='task-evt-atomic-1'").fetchone()["n"], 0)
            finally:
                con.close()
            # the same command retries cleanly after the crash
            env, task = C.open_issue(td, actor, {"id": "evt-atomic-1", "clip_revision_id": "clip-R1",
                                                 "note": "boom"})
            self.assertTrue(env.ok)
            # colliding frame ids cannot leave a partial revision
            con = S.connect(td)
            try:
                S.insert(con, D.FrameInstance(id="clip-X-fi-00", clip_revision_id="clip-X", slot=0,
                                              asset_id="f0", phase="p0", hold_ticks=4,
                                              registration_id="r", source_drawing_id="f0",
                                              derivation_recipe="x"))
            finally:
                con.close()
            with self.assertRaises(S.ConflictError):
                clips.create_revision(td, "contract-R1", "clip-X",
                                      [f"f{i}" for i in range(8)], [f"p{i}" for i in range(8)])
            con = S.connect(td)
            try:
                n = con.execute("SELECT COUNT(*) AS n FROM frame_instances WHERE id LIKE 'clip-X%'").fetchone()["n"]
                self.assertEqual(n, 1)  # only the pre-existing planted row
                self.assertEqual(con.execute(
                    "SELECT COUNT(*) AS n FROM clip_revisions WHERE id='clip-X'").fetchone()["n"], 0)
            finally:
                con.close()

    def test_migration_upgrades_legacy_db_without_data_loss(self):
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            con = S.connect(td)
            try:
                self.assertEqual(con.execute(
                    "SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"], 1)
                # simulate a v1 database: drop R1 tables, reset the version marker
                for t in ("reviewer_pairings", "reviewer_sessions", "motion_guides",
                          "reference_approvals"):
                    con.execute(f"DROP TABLE IF EXISTS {t}")
                con.execute("UPDATE meta SET v='1' WHERE k='migration_version'")
                con.commit()
            finally:
                con.close()
            con = S.connect(td)
            try:
                ver = con.execute("SELECT v FROM meta WHERE k='migration_version'").fetchone()["v"]
                self.assertEqual(ver, "2")
                self.assertEqual(con.execute(
                    "SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"], 1)
                # authority tables exist again and work
                pr = SN.pair_reviewer(td, "human-1")
                self.assertIn("pairing_code", pr)
            finally:
                con.close()


class TestSequenceAndIdempotency(unittest.TestCase):
    def test_frame_phase_hold_lengths_and_slots_match_contract(self):
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            # one frame short of the eight-frame contract
            with self.assertRaises(InvalidInput):
                clips.create_revision(td, "contract-R1", "clip-short",
                                      [f"f{i}" for i in range(7)], [f"p{i}" for i in range(7)])
            # eight assets but one phase string
            with self.assertRaises(InvalidInput):
                clips.create_revision(td, "contract-R1", "clip-short2",
                                      [f"f{i}" for i in range(8)], ["p0"])
            # wrong phase name smuggled into a slot
            phases = [f"p{i}" for i in range(8)]
            phases[3] = "p4"
            with self.assertRaises(InvalidInput):
                clips.create_revision(td, "contract-R1", "clip-wrong",
                                      [f"f{i}" for i in range(8)], phases)
            # out-of-range replacement slot
            with self.assertRaises(InvalidInput):
                clips.register_candidate(td, "clip-R1", "clip-R1x", {8: "f0"},
                                         recipe="repair:x")
            # the failed attempts stored nothing
            con = S.connect(td)
            try:
                n = con.execute("SELECT COUNT(*) AS n FROM clip_revisions").fetchone()["n"]
                self.assertEqual(n, 1)
            finally:
                con.close()

    def test_same_idempotency_key_different_payload_conflicts(self):
        from framebound.v2.services import jobs as J
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            A.approve_reference(td, Actor(type="reviewer", id="human-1"), "char-R1", "mg-R1")
            brief0 = B.compile_reference_brief(td, "contract-R1", 0)["brief"]
            brief1 = B.compile_reference_brief(td, "contract-R1", 1)["brief"]
            # server resolves pixels from the store; no caller bytes needed
            j1 = J.submit_generation(td, brief0, [], "key-1")
            j2 = J.submit_generation(td, brief0, [], "key-1")
            self.assertEqual(j1.artifacts[0]["id"], j2.artifacts[0]["id"])
            self.assertTrue(any(a.get("deduped") for a in j2.artifacts))
            # same key, different brief -> conflict, never silent reuse
            with self.assertRaises(S.ConflictError):
                J.submit_generation(td, brief1, [], "key-1")
            # tampered caller bytes are rejected against stored pixels
            tampered = [{"asset_id": brief0["inputs"][0]["asset_id"],
                         "byte_sha256": "00" * 64,
                         "bytes_b64": "AAA="}]
            with self.assertRaises(InvalidInput):
                J.submit_generation(td, brief0, tampered, "key-tamper")

    def test_strict_numbers_and_hashes_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            bad = {
                "schema_version": "2.0", "id": "contract-bad", "character_revision_id": "char-01",
                "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
                "canvas": {"width": 64, "height": 64, "units": "native_px"},
                "timing": {"ticks_per_second": 60, "holds": ["4", True, 2.0, 4, 4, 4, 4, 4]},
                "references": {"identity": "a", "style": "b", "motion_guide_revision": "m"},
                "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"m{i}"}
                                   for i in range(8)],
                "constraints": [],
                "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}}
            with self.assertRaises(InvalidInput):
                contracts.propose_contract(td, bad)

    def test_claim_binds_holder_and_wrong_version_conflicts(self):
        from framebound.v2.services import corrections as C
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            actor = Actor(type="reviewer", id="human-1")
            env, task = C.open_issue(td, actor, {"id": "evt-claim-1",
                                                 "clip_revision_id": "clip-R1", "note": "x"})
            with self.assertRaises(S.StaleRevisionError):
                C.claim(td, Actor(type="orchestrator", id="spark-1"), task.id, 0)
            out = C.claim(td, Actor(type="orchestrator", id="spark-1"), task.id, 1)
            self.assertEqual(out["holder"], "spark-1")
            self.assertIn("claim_token", out)
            con = S.connect(td)
            try:
                stored = D.CorrectionTask.model_validate_json(
                    json.dumps(S.get(con, "correction_tasks", task.id)[0]))
            finally:
                con.close()
            self.assertEqual(stored.claim_holder, "spark-1")
            self.assertNotIn("claim_token", stored.model_dump())  # only the hash persists
            with self.assertRaises(InvalidInput):
                C.claim(td, Actor(type="orchestrator", id="other"), task.id, 2)


class TestStateReducer(unittest.TestCase):
    def test_current_state_folds_latest_decision(self):
        from framebound.v2.services import review_state as RS
        with tempfile.TemporaryDirectory() as td:
            _seed_approval_project(td)
            actor = Actor(type="reviewer", id="human-1")
            self.assertEqual(RS.current_state(td, "clip-R1")["acceptance"], "unreviewed")
            packets.record_review_event(td, actor, {"id": "d1", "action": "approve",
                                                    "clip_revision_id": "clip-R1"})
            self.assertEqual(RS.current_state(td, "clip-R1")["acceptance"], "approved")
            packets.record_review_event(td, actor, {"id": "d2", "action": "needs_changes",
                                                    "clip_revision_id": "clip-R1"})
            st = RS.current_state(td, "clip-R1")
            self.assertEqual(st["acceptance"], "needs_changes")
            self.assertEqual(st["decided_by"], "human-1")
            packets.record_review_event(td, actor, {"id": "m1", "action": "mark_issue",
                                                    "clip_revision_id": "clip-R1", "note": "x"})
            from framebound.v2.services import corrections as C
            env, task = C.open_issue(td, actor, {"id": "m1", "clip_revision_id": "clip-R1",
                                                 "note": "x"})
            st = RS.current_state(td, "clip-R1")
            self.assertIn("m1", st["open_issue_ids"])


if __name__ == "__main__":
    unittest.main()
