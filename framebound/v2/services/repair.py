"""Bounded repair: named targets, protected pixels, no-regression selection, 3-attempt budget.

Default P0 budget: 3 generation/repair attempts per target + project cost ceiling.
A no-progress signature (target IDs + candidate content hashes + unchanged metrics) stops
the loop with needs_attention instead of retrying blind.
"""
from __future__ import annotations

from .. import domain as D
from .errors import InvalidInput

MAX_ATTEMPTS_PER_TARGET = 3


def plan(baseline_eval: D.Evaluation, targets: list[str], mask_id: str,
         protected_ids: list[str], attempt_count: int = 0) -> dict:
    if attempt_count >= MAX_ATTEMPTS_PER_TARGET:
        return {"needs_attention": True,
                "reason": f"budget exhausted: {attempt_count} attempts >= {MAX_ATTEMPTS_PER_TARGET}"}
    unknown = [t for t in targets if t not in {r.constraint_id for r in baseline_eval.results}]
    if unknown:
        raise InvalidInput(f"unknown target constraints: {unknown}")
    return {"task": "bounded_repair", "baseline_evaluation_id": baseline_eval.id,
            "targets": targets, "allowed_mask_id": mask_id, "protected_ids": protected_ids,
            "attempt": attempt_count + 1, "budget": MAX_ATTEMPTS_PER_TARGET,
            "rules": ["resolve a target or improve its metric beyond the frozen minimum",
                      "no new violations", "no protected-metric worsening", "no required-coverage reduction",
                      "retrying identical content hashes is refused"]}


def no_progress_signature(target_ids: list[str], candidate_hashes: list[str], metrics: dict) -> str:
    from ..providers.ledger import attempt_fingerprint
    return attempt_fingerprint("repair", "baseline", sorted(target_ids), sorted(candidate_hashes), metrics)


# ---------------------------------------------------------------- R4: bounded scope

def _canonical_of(project_dir: str, asset_id: str) -> tuple[bytes, int, int]:
    """Canonical RGBA pixels + dimensions for a stored asset."""
    import json as _json
    from PIL import Image as _Image
    from .. import storage as _S
    from ..media.canonical import canonical_pixels as _canon
    con = _S.connect(project_dir)
    try:
        try:
            adata, _ = _S.get(con, "assets", asset_id)
        except KeyError:
            from .errors import InvalidInput as _II
            raise _II(f"missing_input: asset {asset_id} not stored")
        raw = _S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
        import io as _io
        img = _Image.open(_io.BytesIO(raw)).convert("RGBA")
        return _canon(img), img.size[0], img.size[1]
    finally:
        con.close()


def verify_scope(project_dir: str, baseline_revision_id: str,
                 slot_asset_ids: dict[int, str], task) -> dict:
    """Enforce pixel-bounded repair: changed pixels must lie in ROI/mask.

    Rejects whole-frame swaps for tiny ROIs, out-of-scope slots, protected
    (outside-region) pixel edits, and no-op submits. Returns changed slots.
    """
    import json as _json
    from .. import storage as _S
    from . import masks as _M
    from .errors import InvalidInput as _II
    from .. import domain as _D
    con = _S.connect(project_dir)
    try:
        try:
            rdata, _ = _S.get(con, "clip_revisions", baseline_revision_id)
        except KeyError:
            raise _II(f"unknown clip revision {baseline_revision_id}")
        base = _D.ClipRevision.model_validate_json(_json.dumps(rdata))
        base_by_slot = {}
        for fid in base.frame_instance_ids:
            fdata, _ = _S.get(con, "frame_instances", fid)
            fi = _D.FrameInstance.model_validate_json(_json.dumps(fdata))
            base_by_slot[fi.slot] = fi.asset_id
    finally:
        con.close()
    scope = _M.scope_slots(project_dir, task)
    replaced = set(slot_asset_ids)
    outside = sorted(replaced - scope)
    if outside:
        raise _II(f"replacement slots {outside} lie outside the authorized scope "
                  f"{sorted(scope)}: claim them with range/mask authority first")
    changed_slots: list[int] = []
    changed_pixels = 0
    for slot in sorted(replaced):
        base_px, bw, bh = _canonical_of(project_dir, base_by_slot[slot])
        cand_px, cw, ch = _canonical_of(project_dir, slot_asset_ids[slot])
        if (bw, bh) != (cw, ch):
            raise _II(f"slot {slot}: candidate dimensions {cw}x{ch} != baseline {bw}x{bh}")
        diff = [i for i in range(bw * bh) if base_px[i * 4:(i + 1) * 4] != cand_px[i * 4:(i + 1) * 4]]
        if not diff:
            continue
        allowed = _M.allowed_region(project_dir, task, slot)
        if allowed is None:
            raise _II(f"slot {slot}: {len(diff)} pixels change with no authorized ROI/mask region")
        bad = [i for i in diff if not allowed[i]]
        if bad:
            raise _II(f"slot {slot}: {len(bad)} changed pixels lie outside the authorized "
                      f"ROI/mask region (first at pixel {bad[0]}); protected pixels are immutable")
        changed_slots.append(slot)
        changed_pixels += len(diff)
    if not changed_slots:
        raise _II("no pixel change within the authorized scope: refusing a no-op repair")
    return {"ok": True, "changed_slots": changed_slots,
            "changed_pixels": changed_pixels, "scope_slots": sorted(scope)}


def _pairs(ev) -> set[tuple[str, str]]:
    return {(r.constraint_id, r.scope) for r in ev.results}


def evaluate_selection(baseline, candidate, targets: list[str],
                       frozen_min_gain: float = 0.0, subjective: bool = False,
                       candidate_hashes: list[str] | None = None,
                       prior_signatures: list[str] | None = None,
                       baseline_contract=None, candidate_contract=None) -> dict:
    """Selection policy with full matrix equivalence (R4).

    When contract context is provided (the service path always provides it),
    the candidate must address the identical contract, required set and
    expected (constraint, scope) matrix: a dropped check, a retimed clip or a
    newly error/unmeasured required target can never count as resolved.
    """
    from .. import domain as _D
    if candidate_hashes and prior_signatures:
        sig = no_progress_signature(targets, candidate_hashes, {})
        if sig in (prior_signatures or []):
            return {"selected": False, "needs_attention": True,
                    "reason": "no-progress signature already attempted; blind retry refused"}
    if baseline_contract is not None or candidate_contract is not None:
        if baseline_contract is None or candidate_contract is None:
            return {"selected": False,
                    "reason": "contract context incomplete: both revisions must resolve"}
        if baseline_contract.id != candidate_contract.id:
            return {"selected": False,
                    "reason": f"contract mismatch: {baseline_contract.id} vs {candidate_contract.id}"}
        base_req = {c.id for c in baseline_contract.constraints if c.required}
        cand_req = {c.id for c in candidate_contract.constraints if c.required}
        if base_req != cand_req:
            return {"selected": False,
                    "reason": f"required set changed: {sorted(base_req ^ cand_req)}"}
        if _pairs(baseline) != _pairs(candidate):
            return {"selected": False,
                    "reason": "expected scope matrix changed between baseline and candidate"}
    base_fail = {(r.constraint_id, r.scope) for r in baseline.results if r.outcome == "fail"}
    base_bad = {(r.constraint_id, r.scope) for r in baseline.results
                if r.outcome in ("fail", "error")}
    cand_fail = {(r.constraint_id, r.scope) for r in candidate.results if r.outcome == "fail"}
    new_violations = sorted(cand_fail - base_fail)
    if new_violations:
        return {"selected": False, "reason": f"regression: new violations {new_violations}"}
    base_cov = sum(1 for r in baseline.results if r.outcome in ("pass", "fail"))
    cand_cov = sum(1 for r in candidate.results if r.outcome in ("pass", "fail"))
    if cand_cov < base_cov:
        return {"selected": False, "reason": "required coverage reduced"}
    if subjective:
        if candidate.technical_status != _D.TechnicalStatus.PASS:
            return {"selected": False, "reason": "subjective repair must still pass all gates"}
        if baseline.technical_status != _D.TechnicalStatus.PASS:
            return {"selected": False,
                    "reason": "subjective path needs a technically passing baseline"}
        return {"selected": True, "awaiting_human_comparison": True,
                "reason": "gates pass; only the human can resolve the subjective issue"}
    for t in targets:
        if t not in {c for c, _ in base_bad}:
            return {"selected": False, "reason": f"target {t} is not failing in the baseline"}
        if any(c == t for c, _ in cand_fail):
            return {"selected": False, "reason": f"target {t} still failing in the candidate"}
        bad_states = [r.outcome.value for r in candidate.results
                      if r.constraint_id == t and r.outcome.value in ("error", "unmeasured")]
        if bad_states:
            return {"selected": False,
                    "reason": f"target {t} is {bad_states[0]} in the candidate, not resolved"}
    if candidate.technical_status != _D.TechnicalStatus.PASS:
        return {"selected": False,
                "reason": f"candidate is {candidate.technical_status.value}: "
                          "acceptance needs all publication-blocking gates"}
    resolved = [t for t in targets if t in {c for c, _ in base_bad}]
    if not resolved:
        return {"selected": False, "reason": f"no target resolved: {targets}"}
    return {"selected": True, "resolved": resolved, "reason": "target resolved with zero regressions"}
