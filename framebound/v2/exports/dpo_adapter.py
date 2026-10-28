"""Concrete preference consumer: multimodal chosen/rejected/common-prompt records.

Reads a published snapshot's preferences.jsonl and materializes one record
per explicit human comparison: the shared conditioning (contract +
evaluations), the chosen pixels and the rejected pixels, opened through the
targeted loader (PIL here; the schema carries file refs + hashes so a
datasets/torch adapter can join without re-parsing). Weak technical rankings
are never yielded here — see weak_preferences.jsonl, explicitly labeled.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


def load_preferences(snapshot_dir: str | Path) -> list[dict]:
    """Materialize every explicit human-comparison pair with decoded pixels.

    Raises on the first unreadable chosen/rejected image: a training consumer
    must fail loudly rather than silently drop pairs.
    """
    snap = Path(snapshot_dir)
    rows = []
    for line in (snap / "preferences.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        pr = json.loads(line)
        if pr.get("origin") != "human-comparison":
            raise ValueError(f"non-human pair in preferences.jsonl: {pr.get('origin')}")
        cond = pr.get("conditioning") or {}
        if not cond.get("contract") or not cond.get("chosen_evaluation") \
                or not cond.get("rejected_evaluation"):
            raise ValueError("pair lacks common conditioning "
                             f"(contract/evaluations): {pr.get('comparison_packet')}")
        chosen = [_open(snap, f) for f in (pr.get("chosen") or [])]
        rejected = [_open(snap, f) for f in (pr.get("rejected") or [])]
        if not chosen or not rejected:
            raise ValueError(f"pair {pr.get('comparison_packet')} has empty chosen/rejected")
        rows.append({
            "prompt": pr.get("prompt"),
            "conditioning": cond,
            "comparison_packet": pr.get("comparison_packet"),
            "rejected_issue": pr.get("rejected_issue"),
            "reason": pr.get("reason"),
            "split": pr.get("split", "unsplit"),
            "chosen_images": chosen,
            "rejected_images": rejected,
        })
    return rows


def _open(snap: Path, ref: dict) -> dict:
    p = snap / ref["file"]
    if not p.is_file():
        raise ValueError(f"pair file missing from snapshot: {ref['file']}")
    with Image.open(p) as im:
        im.load()
        size = (im.size[0], im.size[1])
        mode = im.mode
    return {"file": ref["file"], "sha256": ref.get("sha256"),
            "size": size, "mode": mode}
