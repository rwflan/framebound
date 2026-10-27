"""Bounded repair: plan from a report, evaluate a candidate batch.

A candidate is selected for human review only if the whole batch passes
every gate, strictly reduces errors, and changes no protected pixels.
Nothing here writes runtime art or grants approval.
"""
import json
from pathlib import Path
from .audit import audit, load_contract
from .pngcodec import read_png

CODE_TO_INSTRUCTION = {
    "surface_span_drift": "Redraw the local region between the declared features from the approved master; preserve legs, contacts and anchors. The span target is a guide, never a warp.",
    "surface_span_pulse": "Redraw the later frame's local feature region to match the standing-derived span; preserve all other pixels.",
    "silhouette_area_drift": "Redraw the frame at the approved native scale; do not fit the pose to the canvas.",
    "silhouette_width_drift": "Redraw the frame at the approved native scale; check for a local size pulse against neighbours.",
    "silhouette_height_drift": "Redraw the frame at the approved native scale; preserve full limb lengths.",
    "phase_correspondence": "Redraw this slot from its frozen phase reference; the current drawing matches a different phase.",
    "stalled_phase": "Redraw one of the collapsed pair from its phase reference so the required motion step exists.",
    "missing_support_contact": "Redraw so the declared support contact is visibly planted in its frozen window.",
    "appearance_palette_drift": "Redraw using only the approved master palette; no new hues.",
    "anchor_drift": "Redraw so the declared reviewed anchor returns to its phase position.",
}


def plan(report_path, out_path):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    tasks = []
    for err in report["errors"]:
        tasks.append({
            "code": err["code"], "slot": err.get("slot"), "detail": err["detail"],
            "instruction": CODE_TO_INSTRUCTION.get(err["code"], "Redraw the slot from its brief; preserve protected regions."),
            "brief_command": None, "requires_preflight": True,
        })
    result = {"schema": 1, "source_evidence_id": report["evidence_id"], "tasks": tasks,
              "generation_automatic": False, "runtime_writes": False, "automatic_art_approval": False}
    Path(out_path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _protected_errors(before, after, contract, slot):
    """Pixels outside the allowed repair region must be identical."""
    region = None
    for r in contract.get("repair_regions", []):
        if r["slot"] == slot:
            region = r["region"]
    bw, bh, b = before; aw, ah, a = after
    if (bw, bh) != (aw, ah):
        return ["repair_canvas"]
    errors = []
    left, top, right, bottom = region if region else [0, 0, 0, 0]
    changed_outside = 0
    for y in range(bh):
        for x in range(bw):
            i = (y * bw + x) * 4
            if b[i:i + 4] != a[i:i + 4] and not (left <= x < right and top <= y < bottom):
                changed_outside += 1
    if changed_outside:
        errors.append(f"repair_outside_mask:{changed_outside}px")
    for prot in contract.get("protected_regions", []):
        pl, pt, pr, pb = prot["region"]
        for y in range(pt, pb):
            for x in range(pl, pr):
                i = (y * bw + x) * 4
                if b[i:i + 4] != a[i:i + 4]:
                    errors.append("repair_protected_region")
                    return errors
    return errors


def evaluate(contract_path, candidate_manifest_path, out_path):
    from .audit import preflight
    contract_path = Path(contract_path).resolve()
    contract = load_contract(contract_path)
    manifest = json.loads(Path(candidate_manifest_path).read_text(encoding="utf-8"))
    baseline = audit(contract_path)
    result = preflight(contract_path, candidate_manifest_path)
    violations = []
    base_frames = contract["frames"]
    for cand in manifest["candidates"]:
        slot = cand["slot"]
        before = read_png(contract_path.parent / base_frames[slot])
        after = read_png(contract_path.parent / cand["file"])
        for code in _protected_errors(before, after, contract, slot):
            violations.append({"code": code, "slot": slot})
    improvement = len(result["errors"]) < len(baseline["errors"])
    selected = not violations and not result["errors"] and improvement
    decision = {"schema": 1, "before_errors": baseline["errors"], "after_errors": result["errors"],
                "protection_errors": violations, "technical_improvement": improvement,
                "selected_for_review": selected, "runtime_writes": False,
                "automatic_art_approval": False,
                "scope": "Bounded technical selection for human review, not art approval."}
    Path(out_path).write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    return decision
