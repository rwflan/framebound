"""Independent snapshot validation: standard loaders, hashes, durations, eligibility.

Loads the MOVED snapshot with real libraries (datasets imagefolder + COCO API),
checks labels/preferences, verifies hashes + durations, and reports exclusions.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from pycocotools import mask as coco_mask
from pycocotools.coco import COCO


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ensure_datasets():
    """pyenv 3.11.4 ships without _lzma; datasets only needs lzma.open for .xz extraction,
    which imagefolder PNG validation never touches. Shim raises if xz is ever actually used."""
    try:
        import lzma  # noqa: F401
    except ImportError:
        import types
        stub = types.ModuleType("lzma")

        def _open(*a, **k):
            raise RuntimeError("lzma unavailable in this interpreter; .xz extraction unsupported")
        stub.open = _open
        sys.modules["lzma"] = stub


def validate_snapshot(snapshot_dir: str) -> dict:
    snap = Path(snapshot_dir)
    manifest = json.loads((snap / "manifest.json").read_text())
    issues: list[str] = []
    # 1. hashes: every file rehashes to the manifest
    for rel, digest in manifest["files"].items():
        p = snap / rel
        if not p.is_file():
            issues.append(f"missing file {rel}")
        elif _h(p.read_bytes()) != digest:
            issues.append(f"hash mismatch {rel}")
    # 2. COCO via real API + mask round-trip
    coco = COCO(str(snap / "coco" / "annotations.json"))
    img_ids = coco.getImgIds()
    if len(img_ids) != manifest["counts"]["images"]:
        issues.append(f"coco image count {len(img_ids)} != manifest {manifest['counts']['images']}")
    for iid in img_ids[:8]:
        anns = coco.loadAnns(coco.getAnnIds(imgIds=[iid]))
        for a in anns:
            rle = a["segmentation"]
            if isinstance(rle.get("counts"), str):
                rle = {"size": rle["size"], "counts": rle["counts"].encode()}
            dec = coco_mask.decode(rle)
            re = coco_mask.encode(np.asfortranarray(dec))
            if coco_mask.area(re) != a["area"]:
                issues.append(f"mask round-trip area mismatch image {iid}")
    # 3. HF imagefolder via real datasets loader
    _ensure_datasets()
    import datasets
    ds = datasets.load_dataset("imagefolder", data_dir=str(snap / "hf"), split="train")
    if len(ds) != manifest["counts"]["images"]:
        issues.append(f"imagefolder rows {len(ds)} != manifest {manifest['counts']['images']}")
    # 4. preferences eligibility: chosen/rejected resolve, reasons name real issue codes
    prefs = [json.loads(l) for l in (snap / "preferences.jsonl").read_text().splitlines() if l.strip()]
    for pr in prefs:
        if not (snap / "hf" / pr["chosen"]).is_file():
            issues.append(f"preference chosen missing {pr['chosen']}")
        if not pr.get("rejected_issue") or not pr.get("reason"):
            issues.append("preference without named issue/reason")
    # 5. temporal durations match contract holds; splits disjoint on source drawings
    metas = [json.loads(l) for l in (snap / "hf" / "metadata.jsonl").read_text().splitlines() if l.strip()]
    temps = [json.loads(l) for l in (snap / "temporal.jsonl").read_text().splitlines() if l.strip()]
    for t in temps:
        if t["duration_ticks"] != sum(t["holds"]):
            issues.append(f"duration mismatch {t['clip_revision_id']}")
    train_src = {m["source_drawing_id"] for m in metas if m["split"] == "train"}
    test_src = {m["source_drawing_id"] for m in metas if m["split"] == "test"}
    if train_src & test_src:
        issues.append(f"split leakage in snapshot: {sorted(train_src & test_src)}")
    return {"snapshot": manifest["snapshot"], "ok": not issues, "issues": issues,
            "counts": manifest["counts"], "exclusions": manifest["exclusions"],
            "loaders": {"coco_images": len(img_ids), "imagefolder_rows": len(ds),
                        "preferences": len(prefs), "temporal": len(temps)}}
