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


def evaluate_selection(baseline: D.Evaluation, candidate: D.Evaluation, targets: list[str],
                       frozen_min_gain: float = 0.0, subjective: bool = False,
                       candidate_hashes: list[str] | None = None,
                       prior_signatures: list[str] | None = None) -> dict:
    """Selection policy. Technical repairs need target resolution + zero regressions.
    Subjective corrections (baseline technically clean) need same gates + human comparison."""
    if candidate_hashes and prior_signatures:
        sig = no_progress_signature(targets, candidate_hashes, {})
        if sig in (prior_signatures or []):
            return {"selected": False, "needs_attention": True,
                    "reason": "no-progress signature already attempted; blind retry refused"}
    base_fail = {(r.constraint_id, r.scope) for r in baseline.results if r.outcome == "fail"}
    cand_fail = {(r.constraint_id, r.scope) for r in candidate.results if r.outcome == "fail"}
    new_violations = sorted(cand_fail - base_fail)
    if new_violations:
        return {"selected": False, "reason": f"regression: new violations {new_violations}"}
    base_cov = sum(1 for r in baseline.results if r.outcome in ("pass", "fail"))
    cand_cov = sum(1 for r in candidate.results if r.outcome in ("pass", "fail"))
    if cand_cov < base_cov:
        return {"selected": False, "reason": "required coverage reduced"}
    if subjective:
        if candidate.technical_status != D.TechnicalStatus.PASS:
            return {"selected": False, "reason": "subjective repair must still pass all gates"}
        return {"selected": True, "awaiting_human_comparison": True,
                "reason": "gates pass; only the human can resolve the subjective issue"}
    resolved = [t for t in targets
                if not any(c == t for c, _ in cand_fail) and any(c == t for c, _ in base_fail)]
    if not resolved:
        return {"selected": False, "reason": f"no target resolved: {targets}"}
    return {"selected": True, "resolved": resolved, "reason": "target resolved with zero regressions"}
