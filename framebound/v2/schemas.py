"""Export versioned v2 JSON Schemas + write complete valid examples."""
from __future__ import annotations

import json
from pathlib import Path

from . import domain as D

MODELS = {
    "project": D.Project, "asset": D.Asset, "character_revision": D.CharacterRevision,
    "clip_contract_revision": D.ClipContractRevision, "frame_instance": D.FrameInstance,
    "clip_revision": D.ClipRevision, "annotation_revision": D.AnnotationRevision,
    "check_result": D.CheckResult, "evaluation": D.Evaluation, "attempt": D.Attempt,
    "review_packet": D.ReviewPacket, "review_event": D.ReviewEvent,
    "correction_task": D.CorrectionTask, "job": D.Job, "export_snapshot": D.ExportSnapshot,
    "result_envelope": D.ResultEnvelope,
    "run": D.Run, "compiled_brief": D.CompiledBrief, "world_trace": D.WorldTrace,
    "transition_trace": D.TransitionTrace, "motion_guide": D.MotionGuide,
    "reference_approval": D.ReferenceApproval, "registration": D.Registration,
    "edit_mask": D.EditMask,
}


def export_schemas(out_dir: str | Path) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in MODELS.items():
        p = out / f"{name}.schema.json"
        p.write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
        written.append(str(p))
    return written


def valid_contract_example() -> dict:
    return {
        "schema_version": "2.0", "id": "contract-run-01", "character_revision_id": "char-rev-01",
        "action": {"name": "run", "view": "side", "facing": "right", "loop": True},
        "canvas": {"width": 256, "height": 256, "units": "native_px"},
        "timing": {"ticks_per_second": 60, "holds": [4, 4, 4, 4, 4, 4, 4, 4]},
        "root_policy": {"mode": "in_place", "ground_y": 236},
        "references": {"identity": "asset-identity", "style": "asset-style", "motion_guide_revision": "motion-guide-01"},
        "phase_schedule": [
            {"slot": 0, "phase": "A_contact", "motion_reference_id": "pose-A-contact"},
            {"slot": 1, "phase": "A_compression", "motion_reference_id": "pose-A-compression"},
            {"slot": 2, "phase": "A_passing", "motion_reference_id": "pose-A-passing"},
            {"slot": 3, "phase": "A_flight", "motion_reference_id": "pose-A-flight"},
            {"slot": 4, "phase": "B_contact", "motion_reference_id": "pose-B-contact"},
            {"slot": 5, "phase": "B_compression", "motion_reference_id": "pose-B-compression"},
            {"slot": 6, "phase": "B_passing", "motion_reference_id": "pose-B-passing"},
            {"slot": 7, "phase": "B_flight", "motion_reference_id": "pose-B-flight"},
        ],
        "constraints": [
            {"id": "registration", "check": "native_registration", "required": True},
            {"id": "support", "check": "declared_contacts", "required": True,
             "annotation_revision_id": "contacts-01", "max_error_px": 1.0},
            {"id": "local_body", "check": "visible_span", "required": False,
             "annotation_revision_id": "features-01", "reference_revision_id": "span-bounds-01"},
        ],
        "allowed_transforms": {"per_pose_scale": False, "rigid_translation_budget_px": 2},
        "transition_contract_ids": ["idle-run-01", "run-idle-01", "run-attack-01"],
    }


def valid_character_example() -> dict:
    return {
        "schema_version": "2.0", "id": "char-rev-01", "project_id": "proj-demo",
        "identity_asset_ids": ["asset-identity"], "style_asset_ids": ["asset-style"],
        "view_set": ["side"], "canvas": {"width": 256, "height": 256, "units": "native_px"},
        "scale_ruler": "head_height_32px_at_native",
    }
