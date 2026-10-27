"""Reference brief compilation against stored authority (R1).

This is the ONLY path to a generation brief: contract + slot in, stored human
approval + stored motion guide + hash-verified assets out. Transports (CLI/MCP)
must call this service; the previous per-transport fabricated approval dicts
are removed. Without a current human approval, compilation fails instead of
passing with invented authority.
"""
from __future__ import annotations

import json

from .. import domain as D
from .. import storage as S
from ..briefs import compile_brief
from . import approvals as A
from .errors import InvalidInput


def compile_reference_brief(project_dir: str, contract_id: str, slot: int) -> dict:
    con = S.connect(project_dir)
    try:
        try:
            cdata, _ = S.get(con, "contract_revisions", contract_id)
        except KeyError:
            raise InvalidInput(f"unknown contract revision {contract_id}")
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise InvalidInput(f"slot must be an exact integer, got {slot!r}")
        if not (0 <= slot < len(contract.timing.holds)):
            raise InvalidInput(f"slot {slot} outside 0..{len(contract.timing.holds) - 1}")
        approval = A.current_approval(project_dir, contract.character_revision_id)
        if not A.approval_event_is_human(project_dir, approval.event_id):
            raise InvalidInput("reference approval is not a recorded human reviewer decision")
        assets: dict[str, D.Asset] = {}
        for aid in [*approval.identity_asset_ids, *approval.style_asset_ids]:
            asset, raw = A._asset_bytes(project_dir, con, aid)
            import hashlib as _h
            if _h.sha256(raw).hexdigest() != approval.asset_hashes.get(aid):
                raise InvalidInput(f"reference asset {aid}: bytes changed since human approval")
            assets[aid] = asset
        gdata, _ = S.get(con, "motion_guides", approval.motion_guide_id)
        guide = D.MotionGuide.model_validate_json(json.dumps(gdata))
        entry = next((e for e in contract.phase_schedule if e.slot == slot), None)
        if entry is None:
            raise InvalidInput(f"contract has no phase scheduled for slot {slot}")
        gentry = next((g for g in guide.entries if g.phase == entry.phase), None)
        if gentry is None:
            raise InvalidInput(f"motion guide {guide.id} has no authority for phase {entry.phase!r}")
        gasset, graw = A._asset_bytes(project_dir, con, gentry.asset_id)
        import hashlib as _h
        if _h.sha256(graw).hexdigest() != gentry.byte_sha256:
            raise InvalidInput(f"phase guide asset {gentry.asset_id}: bytes changed since approval")
        phase_authority = {
            entry.motion_reference_id:
                f"motion-guide:{guide.id}#phase={gentry.phase}:{gentry.asset_id}"
                f"@sha256:{gentry.byte_sha256[:16]}"
        }
        approvals_map = {aid: {"approved": True, "event_id": approval.event_id}
                         for aid in assets}
        bundle = compile_brief(contract, slot, assets, approvals_map, phase_authority)
    finally:
        con.close()
    return {"conditioning_sha256": bundle.conditioning_sha256, "brief": bundle.bundle,
            "approval_id": approval.id, "motion_guide_id": approval.motion_guide_id}
