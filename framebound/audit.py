"""Contract loading and hash-bound audit reports.

A report binds the contract, every input file, and the analyzer itself.
A stale report therefore cannot hide behind an unchanged entry point.
Technical status is always separate from visual acceptance: no check in
this package grants art approval.
"""
import hashlib
import json
from pathlib import Path
from .checks import check_clip, load_images
from .pngcodec import read_png, sha256_file

ANALYZER_FILES = ["checks.py", "audit.py", "pngcodec.py"]


def load_contract(path):
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    if contract.get("schema") != 1:
        raise ValueError("Contract schema must be 1")
    for key in ("character", "canvas", "frames"):
        if key not in contract:
            raise ValueError(f"Contract missing {key}")
    return contract


def _resolve(base, rel):
    return (Path(base) / rel).resolve()


def _check_hash(base, item, issues, role):
    path = _resolve(base, item["file"])
    if not path.is_file():
        issues.append({"code": "missing_input", "detail": f"{role}: {item['file']}", "slot": None, "severity": "error"})
        return False
    if item.get("sha256") and sha256_file(path) != item["sha256"]:
        issues.append({"code": "changed_input", "detail": f"{role} changed after freezing: {item['file']}", "slot": None, "severity": "error"})
        return False
    return True


def audit(contract_path, frame_files=None, anchors=None):
    contract_path = Path(contract_path).resolve()
    base = contract_path.parent
    contract = load_contract(contract_path)
    issues = []
    inputs = {contract_path.name: sha256_file(contract_path)}

    for frag in contract.get("forbidden_path_fragments", []):
        for f in contract["frames"]:
            if frag in "/" + f.replace("\\", "/"):
                issues.append({"code": "rejected_generation_input", "detail": f, "slot": None, "severity": "error"})

    files = frame_files or contract["frames"]
    for f in files:
        p = _resolve(base, f)
        inputs[str(f)] = sha256_file(p) if p.is_file() else None
    frames = load_images([_resolve(base, f) for f in files])

    references = None
    if contract.get("references"):
        for item in contract["references"]:
            _check_hash(base, item, issues, "phase reference")
            inputs[item["file"]] = sha256_file(_resolve(base, item["file"]))
        references = load_images([_resolve(base, i["file"]) for i in contract["references"]])

    master = None
    if contract.get("master"):
        _check_hash(base, contract["master"], issues, "approved master")
        inputs[contract["master"]["file"]] = sha256_file(_resolve(base, contract["master"]["file"]))
        master = read_png(_resolve(base, contract["master"]["file"]))

    found, metrics = check_clip(contract, frames, references, master, anchors)
    issues.extend(found)
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] != "error"]
    analyzer = {n: hashlib.sha256((Path(__file__).parent / n).read_bytes()).hexdigest() for n in ANALYZER_FILES}
    evidence_src = json.dumps({"inputs": inputs, "analyzer": analyzer}, sort_keys=True).encode()
    return {
        "schema": 1, "tool": "framebound", "character": contract["character"],
        "clip": contract.get("clip", "default"),
        "technical_status": "fail" if errors else "pass",
        "visual_acceptance": "open", "automatic_art_approval": False,
        "errors": errors, "warnings": warnings, "metrics": metrics,
        "inputs": inputs, "analyzer_sha256": analyzer,
        "evidence_id": hashlib.sha256(evidence_src).hexdigest(),
        "unmeasured": [
            "Occluded joints, limb volume across unlike poses, grace and acting are not certified by raster checks.",
            "A technical pass never grants visual acceptance; human review is a separate, recorded step.",
        ],
    }


def preflight(contract_path, candidate_manifest_path):
    """Read-only check of proposed replacement frames. Never writes art."""
    manifest = json.loads(Path(candidate_manifest_path).read_text(encoding="utf-8"))
    contract = load_contract(contract_path)
    files = list(contract["frames"])
    for cand in manifest["candidates"]:
        slot = cand["slot"]
        if cand.get("per_pose_fit"):
            raise ValueError("Candidate declares per-pose fitting; rejected")
        if not (0 <= slot < len(files)):
            raise ValueError(f"Candidate slot {slot} outside clip")
        files[slot] = cand["file"]
    report = audit(contract_path, frame_files=files)
    report["evaluation_mode"] = "candidate-preflight"
    report["candidates"] = manifest["candidates"]
    return report
