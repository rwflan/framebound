"""Compile a generation/repair brief: approved identity+style+phase authority, hash-bound.

Rules enforced here:
- a previous edit is never the sole reference (original refs always bundled);
- rejected/forbidden paths are never referenceable inputs;
- reference roles checked against approval/lineage records, never filename fragments;
- silhouette-only guidance is rejected where internal linework matters (keep full art).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .. import domain as D
from ..services.errors import InvalidInput


@dataclass
class BriefBundle:
    bundle: dict
    conditioning_sha256: str


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def compile_brief(contract: D.ClipContractRevision, slot: int,
                  assets: dict[str, D.Asset], approvals: dict[str, dict],
                  phase_authority: dict[str, str],
                  neighboring_slots: bool = True) -> BriefBundle:
    """assets: asset_id -> Asset for every referenced id. approvals: asset_id -> approval record."""
    if not (0 <= slot < len(contract.timing.holds)):
        raise InvalidInput(f"slot {slot} outside 0..{len(contract.timing.holds) - 1}")
    entry = next(e for e in contract.phase_schedule if e.slot == slot)
    needed = [contract.references.get("identity"), contract.references.get("style")]
    motion_ref = contract.references.get("motion_guide_revision")
    missing = [r for r in needed if not r]
    if missing or not motion_ref:
        raise InvalidInput(f"brief lacks independent authority: missing {missing}, motion guide {motion_ref}")
    phase_src = phase_authority.get(entry.motion_reference_id)
    if not phase_src:
        raise InvalidInput(f"no independent phase authority for {entry.motion_reference_id}: "
                           "the frame under test never supplies its own expected result")
    inputs = []
    for role, aid in (("approved_identity", contract.references["identity"]),
                      ("approved_style", contract.references["style"])):
        a = assets.get(aid)
        if a is None:
            raise InvalidInput(f"missing_input: reference asset {aid} not found")
        ap = approvals.get(aid)
        if not ap or not ap.get("approved"):
            raise InvalidInput(f"reference {aid} lacks explicit human approval or verified import")
        if "rejected" in (a.eligible_roles or []) or ap.get("rejected"):
            raise InvalidInput(f"rejected candidate {aid} is forbidden as a generation reference")
        inputs.append({"role": role, "asset_id": aid, "byte_sha256": a.byte_sha256,
                       "pixel_sha256": a.pixel_sha256, "approval": ap.get("event_id", "imported")})
    inputs.append({"role": "phase_authority", "motion_reference_id": entry.motion_reference_id,
                   "source": phase_src})
    # prior/next accepted context where eligible (accepted revisions only, never the candidate)
    ctx = []
    if neighboring_slots:
        ctx = [{"slot": entry.slot, "phase": entry.phase,
                "hold_ticks": contract.timing.holds[slot]}]
    bundle = {
        "schema_version": "2.0", "contract_revision_id": contract.id, "slot": slot,
        "action": contract.action.model_dump(), "canvas": contract.canvas.model_dump(),
        "holds": contract.timing.holds, "ticks_per_second": contract.timing.ticks_per_second,
        "root_policy": contract.root_policy.model_dump(),
        "allowed_transforms": contract.allowed_transforms.model_dump(),
        "inputs": inputs, "phase_context": ctx,
        "preservation": ["native canvas", "frozen calibration", "protected regions unchanged",
                         "no per-pose fitting"],
        "forbidden": ["previous edits as sole reference", "rejected paths",
                      "silhouette-only guidance where linework matters"],
        "instruction": (f"Draw phase '{entry.phase}' ({contract.action.name}, {contract.action.view} view, "
                        f"{contract.action.facing} facing) on the {contract.canvas.width}x{contract.canvas.height} "
                        f"native canvas, matching approved identity/style and the independent phase guide "
                        f"{entry.motion_reference_id}. Preserve canvas, holds, and protected regions exactly."),
        "evaluation_tools_next": ["candidate_register", "clip_evaluate"],
    }
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
    bundle["conditioning_sha256"] = digest
    return BriefBundle(bundle=bundle, conditioning_sha256=digest)
