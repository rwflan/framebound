"""Generation brief compiler.

Binds the immutable master, an independent identity reference, the exact
phase reference, and neighbouring frames by SHA-256. A previous edit may
never be the sole reference, and rejected paths are forbidden inputs.
The compiler makes no generation request; the orchestrating model calls
Muse Image (or any generator) with the brief, then preflights the result.
"""
import json
from pathlib import Path
from .audit import load_contract
from .pngcodec import sha256_file


def compile_brief(contract_path, slot, out_dir):
    contract_path = Path(contract_path).resolve()
    base = contract_path.parent
    contract = load_contract(contract_path)
    frames = contract["frames"]
    if not (0 <= slot < len(frames)):
        raise ValueError(f"Slot {slot} outside clip of {len(frames)} frames")
    refs = contract.get("references", [])
    if slot >= len(refs):
        raise ValueError("No frozen phase reference for this slot; add one before generating")
    inputs = []
    master = contract.get("master")
    if master:
        inputs.append({"role": "approved_master", "file": master["file"],
                       "sha256": sha256_file(base / master["file"])})
    if contract.get("identity_reference"):
        item = contract["identity_reference"]
        inputs.append({"role": "identity_reference", "file": item["file"],
                       "sha256": sha256_file(base / item["file"])})
    inputs.append({"role": "phase_reference", "file": refs[slot]["file"],
                   "sha256": refs[slot].get("sha256") or sha256_file(base / refs[slot]["file"])})
    for nb in (slot - 1, slot + 1):
        if 0 <= nb < len(frames):
            inputs.append({"role": f"neighbour_{nb}", "file": frames[nb],
                           "sha256": sha256_file(base / frames[nb])})
    brief = {
        "schema": 1, "character": contract["character"], "clip": contract.get("clip", "default"),
        "slot": slot, "canvas": contract["canvas"], "per_pose_fit": False,
        "inputs": inputs,
        "phase_reference_sha256": inputs[-3 if len(inputs) >= 3 else -1]["sha256"] if inputs else None,
        "constraints": {
            "native_canvas": contract["canvas"],
            "holds": contract.get("holds"),
            "preserve": "Native scale and registration, complete limbs/feet, declared contacts and anchors, locked cadence. No whole-frame fitting, no limb warping.",
            "requires_post_generation_preflight": True,
            "automatic_art_approval": False,
        },
        "instruction": (f"Draw frame {slot} of the {contract.get('clip', 'clip')} cycle for "
                        f"{contract['character']} on the exact {contract['canvas'][0]}x{contract['canvas'][1]} canvas. "
                        "Use the approved master for body and costume, the phase reference for pose, "
                        "and the neighbours for continuity. Do not use any rejected or previous-edit image as the sole reference."),
    }
    # phase_reference_sha256 must be the phase input, not a neighbour.
    brief["phase_reference_sha256"] = next(i["sha256"] for i in inputs if i["role"] == "phase_reference")
    validate_brief(contract, brief, base)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / f"brief-slot-{slot}.json"
    path.write_text(json.dumps(brief, indent=2) + "\n", encoding="utf-8")
    return path, brief


def validate_brief(contract, brief, base):
    issues = []
    inputs = brief.get("inputs", [])
    if len(inputs) < 2:
        issues.append("sole_generated_reference: a previous edit must never be the sole authoring reference")
    master = contract.get("master", {})
    if master and not any(i.get("file") == master.get("file") for i in inputs):
        issues.append("missing_clean_master: brief does not include the immutable approved master")
    for item in inputs:
        for frag in contract.get("forbidden_path_fragments", []):
            if frag in "/" + item.get("file", "").replace("\\", "/"):
                issues.append(f"rejected_generation_input: {item.get('file')}")
        p = Path(base) / item.get("file", "")
        if not p.is_file() or (item.get("sha256") and sha256_file(p) != item["sha256"]):
            issues.append(f"changed_generation_input: {item.get('file')}")
        if not item.get("role"):
            issues.append(f"missing_input_role: {item.get('file')}")
    if not brief.get("phase_reference_sha256"):
        issues.append("missing_phase_brief: request must identify the exact motion phase")
    if issues:
        raise ValueError("; ".join(issues))
    return True
