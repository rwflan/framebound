"""DTO conformance: live endpoint responses validate against api/dto.py.

Guards the generated web/src/api-types.ts: if a response stops matching its
DTO, the desk types are stale and this fails before the TypeScript build.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from framebound.v2.api import dto as DTO
from framebound.v2.api.app import create_app
from framebound.v2.checks import fixtures as F
from framebound.v2.services import assets, characters, clips, contracts, packets, projects
from framebound.v2.services import corrections as C
from framebound.v2.services.authz import Actor

REV = Actor(type="reviewer", id="human-1")
MOD = Actor(type="orchestrator", id="spark-1")


def _seed(td: str) -> dict:
    src = Path(td) / "src"
    meta = F.build_cycle(src)
    for i, rel in enumerate(meta["clean"]):
        assets.import_asset(td, str(src / rel), f"f{i}", source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][0]), "a-id", source_kind="procedural")
    assets.import_asset(td, str(src / meta["clean"][1]), "a-st", source_kind="procedural")
    projects.create_project(td, {"id": "project-dto", "name": "Review project"})
    characters.propose_character(td, {"id": "char-01", "project_id": "project-dto",
        "identity_asset_ids": ["a-id"], "style_asset_ids": ["a-st"], "view_set": ["side"],
        "canvas": {"width": 64, "height": 64}, "scale_ruler": "Frozen test canvas"})
    contracts.propose_contract(td, {
        "schema_version": "2.0", "id": "c-dto-01", "character_revision_id": "char-01",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 64, "height": 64, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4] * 8},
        "references": {"identity": "a-id", "style": "a-st", "motion_guide_revision": "mg-01"},
        "phase_schedule": [{"slot": i, "phase": f"p{i}", "motion_reference_id": f"pose-{i}"} for i in range(8)],
        "constraints": [{"id": "registration", "check": "native_registration", "required": True}],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2}})
    clips.create_revision(td, "c-dto-01", "rev-a", [f"f{i}" for i in range(8)],
                          [f"p{i}" for i in range(8)])
    clips.create_revision(td, "c-dto-01", "rev-b", [f"f{i}" for i in range(8)],
                          [f"p{i}" for i in range(8)])
    eva = clips.evaluate(td, "rev-a")
    evb = clips.evaluate(td, "rev-b")
    packets.create_packet(td, "pkt-a", "rev-a", eva.artifacts[0]["id"], "review")
    packets.create_packet(td, "pkt-ab", "rev-b", evb.artifacts[0]["id"], "compare",
                          comparison_revision_id="rev-a")
    env, task = C.open_issue(td, REV, {"action": "mark_issue",
                                       "clip_revision_id": "rev-b",
                                       "packet_id": "pkt-ab",
                                       "frame_range": [12, 15], "note": "x",
                                       "category": "hole"})
    return {"task_id": task.id, "evb": evb.artifacts[0]["id"]}


class DtoConformance(unittest.TestCase):
    def test_store_marker_changes_for_external_writes_but_not_reads(self):
        with tempfile.TemporaryDirectory() as td:
            projects.create_project(td, {'id': 'one', 'name': 'First'})
            c = TestClient(create_app(td))
            before = c.get('/api/changes')
            self.assertEqual(before.status_code, 200)
            DTO.ChangesDto.model_validate(before.json())
            c.get('/api/project')
            self.assertEqual(c.get('/api/changes').json(), before.json())
            projects.create_project(td, {'id': 'two', 'name': 'Second'})
            self.assertNotEqual(c.get('/api/changes').json(), before.json())
    def test_source_desk_build_wins_over_stale_packaging_stage(self):
        import framebound.v2.api.app as app_module
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.git').touch()
            ((root / 'web' / 'dist').resolve()).mkdir(parents=True)
            (root / 'web' / 'package.json').write_text('{}')
            (root / 'web' / 'dist' / 'index.html').write_text('current design')
            package = root / 'package'
            (package / 'desk').mkdir(parents=True)
            (package / 'desk' / 'index.html').write_text('old design')
            with patch.object(app_module, '__file__', str(root / 'framebound' / 'v2' / 'api' / 'app.py')), patch('importlib.resources.files', return_value=package):
                self.assertEqual(app_module._desk_dir(), (root / 'web' / 'dist').resolve())

    def test_live_responses_match_dtos(self):
        with tempfile.TemporaryDirectory() as td:
            info = _seed(td)
            c = TestClient(create_app(td))
            b = c.get("/api/packet/pkt-a")
            self.assertEqual(b.status_code, 200, b.text)
            DTO.PacketBundleDto.model_validate(b.json())
            self.assertTrue(all(f["asset_url"] for f in b.json()["frames"]))
            evaluation = b.json()["evaluation"]
            self.assertTrue(evaluation["created_at"])
            self.assertEqual(len(evaluation["evidence_manifest_sha256"]), 64)
            self.assertIsNotNone(evaluation["results"][0]["observed_value"])
            self.assertIn("expected_interval", evaluation["results"][0])
            project = c.get('/api/project')
            self.assertEqual(project.status_code, 200)
            DTO.ProjectSummaryDto.model_validate(project.json())
            self.assertEqual(project.json()['projects'], [{'id': 'project-dto', 'name': 'Review project'}])
            references = c.get('/api/references').json()
            self.assertEqual(references['character_revisions'][0]['project_id'], 'project-dto')
            q = c.get("/api/compare", params={"base": "rev-a", "other": "rev-b"})
            self.assertEqual(q.status_code, 200, q.text)
            DTO.CompareBundleDto.model_validate(q.json())
            self.assertTrue(q.json()["timing_equal"])
            bad = c.get("/api/compare", params={"base": "rev-a", "other": "nope"})
            self.assertEqual(bad.status_code, 422)
            iss = c.get("/api/issues", params={"revision": "rev-b"})
            self.assertEqual(iss.status_code, 200, iss.text)
            details = [DTO.IssueDetailDto.model_validate(r) for r in iss.json()]
            self.assertEqual(len(details), 1)
            self.assertEqual(details[0].frame_range, [12, 15])
            self.assertEqual(details[0].task_status, "open")
            allq = c.get("/api/corrections", params={"status": "all"})
            self.assertEqual(allq.status_code, 200)
            DTO.CorrectionsListDto.model_validate(allq.json())
            openq = c.get("/api/corrections")
            self.assertIn(info["task_id"], openq.text)
            t = c.get(f"/api/corrections/{info['task_id']}")
            self.assertEqual(t.status_code, 200, t.text)
            DTO.TaskStatusDto.model_validate(t.json())
            a1 = c.get("/api/activity")
            self.assertEqual(a1.status_code, 200)
            page = DTO.ActivityPageDto.model_validate(a1.json())
            self.assertTrue(page.events)
            a2 = c.get("/api/activity", params={"since": page.cursor})
            self.assertEqual(a2.status_code, 200)
            self.assertEqual(a2.json()["events"], [])
            e = c.get("/api/eligibility/rev-a")
            self.assertEqual(e.status_code, 200)
            DTO.EligibilityDto.model_validate(e.json())
            x = c.post("/api/exports", json={"name": "dto-exp",
                                             "revisions": ["rev-a", "rev-b"], "policy": {}})
            self.assertEqual(x.status_code, 201, x.text)
            DTO.ExportResultDto.model_validate(x.json())
            x2 = c.get("/api/exports/dto-exp")
            self.assertEqual(x2.status_code, 200)
            DTO.ExportResultDto.model_validate(x2.json())


if __name__ == "__main__":
    unittest.main()
