"""Reference authority: stored motion guides + stored human approvals, never caller claims.

- Draft motion guides may be proposed through model tools (orchestrator/system).
- Only a reviewer session can approve a character revision's references, binding
  exact asset hashes + the motion guide in an immutable ReferenceApproval record.
- Brief compilation resolves this stored authority; there is no adapter that can
  invent approval or phase guides.
"""
from __future__ import annotations

import json
import uuid

from .. import domain as D
from .. import storage as S
from .authz import Actor, require_reviewer
from .errors import InvalidInput


def _asset_bytes(project_dir: str, con, asset_id: str) -> tuple[D.Asset, bytes]:
    row = con.execute("SELECT data FROM assets WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        raise InvalidInput(f"missing_input: reference asset {asset_id} not stored")
    asset = D.Asset.model_validate_json(row["data"])
    blob = S.blob_path(project_dir, asset.byte_sha256)
    if not blob.is_file():
        raise InvalidInput(f"missing_input: blob for asset {asset_id} is gone")
    return asset, blob.read_bytes()


def propose_motion_guide(project_dir: str, actor: Actor, guide: dict) -> D.ResultEnvelope:
    """Model/orchestrator tool: store a draft motion guide. Drafts authorize nothing."""
    try:
        mg = D.MotionGuide.model_validate(guide)
    except Exception as e:
        raise InvalidInput(f"motion guide invalid: {e}") from e
    con = S.connect(project_dir)
    try:
        try:
            cdata, _ = S.get(con, "character_revisions", mg.character_revision_id)
        except KeyError:
            raise InvalidInput(f"unknown character revision {mg.character_revision_id}")
        if mg.supersedes:
            try:
                S.get(con, "motion_guides", mg.supersedes)
            except KeyError:
                raise InvalidInput(f"unknown superseded guide {mg.supersedes}")
        with S.atomic(con):
            for entry in mg.entries:
                asset, _ = _asset_bytes(project_dir, con, entry.asset_id)
                import hashlib as _h
                if _h.sha256(S.blob_path(project_dir, asset.byte_sha256).read_bytes()).hexdigest() != entry.byte_sha256:
                    raise InvalidInput(f"guide entry {entry.phase}: hash does not match stored asset bytes")
            S.stage(con, mg)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-guide-{mg.id}", revision_id=mg.id,
                            next_actions=["approve_reference"])


def approve_reference(project_dir: str, actor: Actor, character_revision_id: str,
                      motion_guide_id: str, event_id: str | None = None) -> D.ResultEnvelope:
    """Reviewer-only: bind a character revision's identity/style assets + motion guide.

    Re-approval supersedes the previous record; the old record stays immutable.
    """
    require_reviewer(actor, "approve_reference")
    con = S.connect(project_dir)
    try:
        try:
            cdata, _ = S.get(con, "character_revisions", character_revision_id)
        except KeyError:
            raise InvalidInput(f"unknown character revision {character_revision_id}")
        char = D.CharacterRevision.model_validate_json(json.dumps(cdata))
        try:
            gdata, _ = S.get(con, "motion_guides", motion_guide_id)
        except KeyError:
            raise InvalidInput(f"unknown motion guide {motion_guide_id}")
        guide = D.MotionGuide.model_validate_json(json.dumps(gdata))
        if guide.character_revision_id != character_revision_id:
            raise InvalidInput("motion guide addresses a different character revision")
        with S.atomic(con):
            hashes: dict[str, str] = {}
            for aid in [*char.identity_asset_ids, *char.style_asset_ids]:
                asset, raw = _asset_bytes(project_dir, con, aid)
                if "rejected" in (asset.eligible_roles or []):
                    raise InvalidInput(f"rejected asset {aid} cannot be approved as a reference")
                import hashlib as _h
                digest = _h.sha256(raw).hexdigest()
                if digest != asset.byte_sha256:
                    raise InvalidInput(f"asset {aid}: stored bytes no longer match recorded hash")
                hashes[aid] = digest
            for entry in guide.entries:
                asset, raw = _asset_bytes(project_dir, con, entry.asset_id)
                import hashlib as _h
                if _h.sha256(raw).hexdigest() != entry.byte_sha256:
                    raise InvalidInput(f"guide phase {entry.phase}: bytes changed since proposal")
                hashes[entry.asset_id] = _h.sha256(raw).hexdigest()
            # supersede the previous current approval, if any
            prev = None
            for r in con.execute("SELECT id, data FROM reference_approvals").fetchall():
                ap = D.ReferenceApproval.model_validate_json(r["data"])
                if ap.character_revision_id == character_revision_id and ap.supersedes is None:
                    # check whether a newer record already supersedes it
                    newer = [r2 for r2 in con.execute("SELECT data FROM reference_approvals").fetchall()
                             if D.ReferenceApproval.model_validate_json(r2["data"]).supersedes == ap.id]
                    if not newer:
                        prev = ap
                        break
            eid = event_id or f"evt-{uuid.uuid4().hex[:12]}"
            ev = D.ReviewEvent(id=eid, actor_type="reviewer", actor_id=actor.id,
                               action="approve_reference", clip_revision_id=character_revision_id,
                               note=f"reference approval for {character_revision_id} via {motion_guide_id}")
            try:
                S.stage(con, ev)
            except S.ConflictError:
                raise S.ConflictError(f"approval event {eid} already recorded with different content")
            ap = D.ReferenceApproval(id=f"rappr-{uuid.uuid4().hex[:12]}",
                                     character_revision_id=character_revision_id,
                                     motion_guide_id=motion_guide_id,
                                     identity_asset_ids=list(char.identity_asset_ids),
                                     style_asset_ids=list(char.style_asset_ids),
                                     asset_hashes=hashes, reviewer_id=actor.id, event_id=eid,
                                     supersedes=prev.id if prev else None)
            S.stage(con, ap)
    finally:
        con.close()
    return D.ResultEnvelope(ok=True, operation_id=f"op-approve-ref-{ap.id}", revision_id=character_revision_id,
                            human_acceptance=D.HumanAcceptance.APPROVED,
                            artifacts=[{"id": ap.id, "role": "reference_approval"},
                                       {"id": eid, "role": "review_event"}],
                            next_actions=["brief_compile"])


def current_approval(project_dir: str, character_revision_id: str) -> D.ReferenceApproval:
    """Return the current (non-superseded) human reference approval, or raise."""
    con = S.connect(project_dir)
    try:
        rows = con.execute("SELECT data FROM reference_approvals").fetchall()
        approvals = [D.ReferenceApproval.model_validate_json(r["data"]) for r in rows]
    finally:
        con.close()
    mine = [a for a in approvals if a.character_revision_id == character_revision_id]
    superseded = {a.supersedes for a in mine if a.supersedes}
    current = [a for a in mine if a.id not in superseded]
    if not current:
        raise InvalidInput(f"no current reference approval for {character_revision_id}: "
                           "a reviewer must approve references before briefing generation")
    # latest record wins if several (ordered by creation time)
    current.sort(key=lambda a: a.created_at)
    return current[-1]


def approval_event_is_human(project_dir: str, event_id: str) -> bool:
    con = S.connect(project_dir)
    try:
        try:
            edata, _ = S.get(con, "review_events", event_id)
        except KeyError:
            return False
    finally:
        con.close()
    return D.ReviewEvent.model_validate_json(json.dumps(edata)).actor_type == "reviewer"
