"""Annotation geometry: typed points/masks with proposal/review provenance.

A bare label cannot support measurements: every annotation carries point
geometry, a mask asset, or both, in native_px, plus who proposed it and who
(if anyone) reviewed it. Consumers (support evidence, protection masks) read
these records; nothing in the generic evaluator invents geometry.
"""
from __future__ import annotations

import json

from .. import domain as D
from .. import storage as S
from .authz import Actor, require_reviewer
from .errors import InvalidInput


def propose(project_dir: str, actor: Actor, annotation: dict) -> D.ResultEnvelope:
    """Model/orchestrator tool: store proposed geometry. Proposals authorize nothing."""
    try:
        ann = D.AnnotationRevision.model_validate(annotation)
    except Exception as e:
        raise InvalidInput(f"annotation invalid: {e}") from e
    if ann.annotator_type == 'human_reviewed' or ann.reviewer or ann.review_event_id:
        require_reviewer(actor, 'review_annotation')
        ann.reviewer = actor.id
    con = S.connect(project_dir)
    try:
        with S.atomic(con):
            try:
                adata, _ = S.get(con, "assets", ann.source_asset_id)
            except KeyError:
                raise InvalidInput(f"unknown source asset {ann.source_asset_id}")
            asset = D.Asset.model_validate_json(json.dumps(adata))
            if asset.byte_sha256 != ann.source_pixel_sha256 and asset.pixel_sha256 != ann.source_pixel_sha256:
                raise InvalidInput("annotation source hash matches neither stored bytes nor pixels")
            if ann.frame_instance_id:
                try:
                    S.get(con, "frame_instances", ann.frame_instance_id)
                except KeyError:
                    raise InvalidInput(f"unknown frame instance {ann.frame_instance_id}")
            if ann.mask_asset_id:
                try:
                    S.get(con, "assets", ann.mask_asset_id)
                except KeyError:
                    raise InvalidInput(f"unknown mask asset {ann.mask_asset_id}")
            S.stage(con, ann)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-annotation-{ann.id}", revision_id=ann.id,
                            next_actions=["review_annotation"])


def for_asset(project_dir: str, asset_id: str) -> list[D.AnnotationRevision]:
    con = S.connect(project_dir)
    try:
        out = []
        for r in con.execute("SELECT data FROM annotation_revisions").fetchall():
            try:
                ann = D.AnnotationRevision.model_validate_json(r["data"])
            except Exception:
                continue
            if ann.source_asset_id == asset_id:
                out.append(ann)
    finally:
        con.close()
    return out
