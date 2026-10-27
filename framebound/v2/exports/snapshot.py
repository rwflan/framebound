"""Snapshot builder. Frozen explicit selection; honest portable training labels.

Label origins (never silently relabeled):
- human-approved: technical pass + human approval event for the EXACT revision
- weak-negative: failed candidates/attempts with named issue codes (valid negatives, never positives)
- procedural-test: synthetic fixtures (regression + demos only, excluded from positives by default)
- derived: holds repeats / rigid translations / composites (lineage recorded, distinct drawing count kept)
Exports carry label origin + lineage. Moving the directory must not break references.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from .. import domain as D
from .. import storage as S
from ..checks.raster import alpha_mask, silhouette

DATASET_VERSION = "2.0"


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _silhouette_records(img: Image.Image) -> dict:
    w, h = img.size
    px = img.convert("RGBA").tobytes()
    m = alpha_mask(px, w, h)
    s = silhouette(m, w, h)
    return {"bbox": s["bbox"] or [0, 0, 0, 0], "area": s["area"], "mask": m, "size": [w, h]}


def _rle(mask: bytearray, w: int, h: int) -> dict:
    import numpy as np
    from pycocotools import mask as coco_mask
    arr = np.array(mask, dtype=np.uint8).reshape((h, w), order="F")
    r = coco_mask.encode(arr)
    r["counts"] = r["counts"].decode()
    return r




def _approved_descendant(rid: str, slot: int, revs: dict, approvals: dict, evals: dict):
    """Find an approved descendant revision and its same-slot image rel path."""
    for cid, rev in revs.items():
        chain, cur = False, rev
        seen = 0
        while cur is not None and seen < 8:
            if cur.parent_revision_id == rid:
                chain = True
                break
            cur = revs.get(cur.parent_revision_id) if cur.parent_revision_id else None
            seen += 1
        if not chain:
            continue
        if cid not in approvals:
            continue
        ev = evals.get(cid)
        if ev is None or ev.technical_status != D.TechnicalStatus.PASS:
            continue
        return cid, f"data/{cid}-{slot:02d}.png"
    return None

def build_snapshot(project_dir: str, snapshot_name: str, clip_revision_ids: list[str],
                   out_dir: str, policy: dict | None = None) -> dict:
    """Build a portable snapshot. Returns manifest incl. exclusions with reasons."""
    pol = {"rights_allow": ["original"], "split": {"train": [], "test": []},
           "split_policy": "exclude", "include_procedural_positives": False}
    pol.update(policy or {})
    out = Path(out_dir)
    (out / "hf" / "data").mkdir(parents=True, exist_ok=True)
    (out / "coco").mkdir(parents=True, exist_ok=True)
    con = S.connect(project_dir)
    try:
        # frozen selection: explicit revision ids + their evaluations at export time
        revs, contracts, evals, approvals = {}, {}, {}, {}
        for rid in clip_revision_ids:
            rdata, _ = S.get(con, "clip_revisions", rid)
            rev = D.ClipRevision.model_validate(rdata)
            revs[rid] = rev
            cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
            contracts[rid] = D.ClipContractRevision.model_validate(cdata)
        for rid in clip_revision_ids:
            rows = con.execute("SELECT data FROM evaluations").fetchall()
            mine = [D.Evaluation.model_validate(json.loads(r["data"])) for r in rows
                    if json.loads(r["data"])["clip_revision_id"] == rid]
            if mine:
                evals[rid] = mine[-1]
        for r in con.execute("SELECT data FROM review_events").fetchall():
            e = D.ReviewEvent.model_validate(json.loads(r["data"]))
            if e.action == "approve":
                approvals[e.clip_revision_id] = e.id
        # frame assets + lineage
        frames: dict[str, dict] = {}
        for rid, rev in revs.items():
            for fid in rev.frame_instance_ids:
                fdata, _ = S.get(con, "frame_instances", fid)
                fi = D.FrameInstance.model_validate(fdata)
                adata, _ = S.get(con, "assets", fi.asset_id)
                a = D.Asset.model_validate(adata)
                frames[fid] = {"fi": fi, "asset": a, "rev": rid}
        manifest_files: dict[str, str] = {}
        exclusions: list[dict] = []

        def keep(asset: D.Asset, why: str) -> str | None:
            if asset.rights not in pol["rights_allow"]:
                exclusions.append({"asset": asset.id, "reason": f"rights {asset.rights} not in {pol['rights_allow']}",
                                   "context": why})
                return None
            if asset.source_kind == "procedural" and not pol["include_procedural_positives"] and why == "positive":
                exclusions.append({"asset": asset.id, "reason": "procedural-test: valid regression, not a training positive",
                                   "context": why})
                return None
            return asset.id

        # split leakage: same source drawing in train+test
        train_src = {frames[f]["fi"].source_drawing_id for f in frames
                     if frames[f]["rev"] in pol["split"].get("train", [])}
        test_src = {frames[f]["fi"].source_drawing_id for f in frames
                    if frames[f]["rev"] in pol["split"].get("test", [])}
        leaked = train_src & test_src
        if leaked:
            msg = f"split leakage: source drawings {sorted(leaked)} in train+test"
            if pol["split_policy"] == "strict":
                raise ValueError(msg)
            exclusions.append({"asset": sorted(leaked), "reason": msg, "context": "split"})

        coco_images, coco_anns, ann_id = [], [], 0
        meta_rows, pref_rows, temp_rows = [], [], []
        for rid, rev in revs.items():
            contract = contracts[rid]
            ev = evals.get(rid)
            approved = approvals.get(rid)
            split = next((s for s, ids in pol["split"].items() if rid in ids), "unsplit")
            temp_rows.append({"clip_revision_id": rid, "frames": len(rev.frame_instance_ids),
                              "holds": contract.timing.holds, "loop": contract.action.loop,
                              "ticks_per_second": contract.timing.ticks_per_second,
                              "duration_ticks": sum(contract.timing.holds),
                              "evaluation_id": ev.id if ev else None,
                              "technical_status": ev.technical_status.value if ev else "unevaluated"})
            in_test_leak = False
            for fid in rev.frame_instance_ids:
                fr = frames[fid]
                fi, a = fr["fi"], fr["asset"]
                if fi.source_drawing_id in leaked and split == "test":
                    in_test_leak = True
                    continue
                blob = S.blob_path(project_dir, a.byte_sha256)
                img = Image.open(blob).convert("RGBA")
                rel = f"hf/data/{rid}-{fi.slot:02d}.png"
                dest = out / rel
                img.save(dest)
                manifest_files[rel] = _h(dest.read_bytes())
                rec = _silhouette_records(img)
                coco_images.append({"id": len(coco_images), "file_name": f"../{rel}",
                                    "width": rec["size"][0], "height": rec["size"][1],
                                    "clip_revision_id": rid, "slot": fi.slot})
                coco_anns.append({"id": ann_id, "image_id": len(coco_images) - 1, "category_id": 0,
                                  "bbox": [rec["bbox"][0], rec["bbox"][1],
                                           rec["bbox"][2] - rec["bbox"][0], rec["bbox"][3] - rec["bbox"][1]],
                                  "area": rec["area"], "segmentation": _rle(rec["mask"], *rec["size"]),
                                  "iscrowd": 0})
                ann_id += 1
                origin = "procedural-test" if a.source_kind == "procedural" else (
                    "human-approved" if (approved and ev and ev.technical_status == D.TechnicalStatus.PASS)
                    else "unevaluated")
                meta_rows.append({"file_name": f"data/{rid}-{fi.slot:02d}.png",
                                  "character": rev.contract_revision_id, "clip": rid, "slot": fi.slot,
                                  "hold_ticks": fi.hold_ticks, "phase": fi.phase,
                                  "technical_status": ev.technical_status.value if ev else "unevaluated",
                                  "issue_codes": sorted({r.constraint_id for r in (ev.results if ev else [])
                                                         if r.outcome in ("fail", "error")}),
                                  "human_decision": "approved" if approved else "unreviewed",
                                  "label_origin": origin,
                                  "derivation_recipe": fi.derivation_recipe,
                                  "source_drawing_id": fi.source_drawing_id,
                                  "split": split})
                # preference pairs: a failed slot is only a valid rejected example when an
                # APPROVED descendant revision supplies the chosen fix for the same slot.
                # No approved fix → pair withheld with an explicit reason (never invented).
                if ev and ev.technical_status == D.TechnicalStatus.FAIL:
                    for r in ev.results:
                        if r.outcome == "fail" and r.scope == f"slot {fi.slot}":
                            fix = _approved_descendant(rid, fi.slot, revs, approvals, evals)
                            if fix is None:
                                exclusions.append({"clip": rid, "slot": fi.slot,
                                    "reason": f"no approved fix for failed slot ({r.constraint_id}); "
                                              "preference pair withheld", "context": "preference"})
                                continue
                            fix_rid, fix_rel = fix
                            if keep(a, "preference-rejected") is None:
                                continue
                            chosen_aid = next((fr["asset"].id for fr in frames.values()
                                               if fr["rev"] == fix_rid and fr["fi"].slot == fi.slot), None)
                            if chosen_aid is not None:
                                chosen_asset = next(fr["asset"] for fr in frames.values()
                                                    if fr["asset"].id == chosen_aid)
                                if keep(chosen_asset, "positive") is None:
                                    continue
                            pref_rows.append({"prompt": f"{contract.action.name} phase {fi.phase} "
                                                        f"(contract {contract.id}, slot {fi.slot})",
                                              "conditioning": contract.id,
                                              "chosen": fix_rel, "chosen_revision": fix_rid,
                                              "rejected": f"data/{rid}-{fi.slot:02d}.png",
                                              "rejected_revision": rid,
                                              "rejected_issue": r.constraint_id,
                                              "reason": r.reason, "split": split})
            if in_test_leak:
                exclusions.append({"clip": rid, "reason": "test frames sharing train source drawings excluded",
                                   "context": "split"})
        (out / "coco" / "annotations.json").write_text(json.dumps(
            {"images": coco_images, "annotations": coco_anns,
             "categories": [{"id": 0, "name": "character", "supercategory": "character"}]}, indent=2))
        manifest_files["coco/annotations.json"] = _h((out / "coco" / "annotations.json").read_bytes())
        (out / "hf" / "metadata.jsonl").write_text("\n".join(json.dumps(r) for r in meta_rows) + "\n")
        manifest_files["hf/metadata.jsonl"] = _h((out / "hf" / "metadata.jsonl").read_bytes())
        (out / "preferences.jsonl").write_text("\n".join(json.dumps(r) for r in pref_rows) + ("\n" if pref_rows else ""))
        manifest_files["preferences.jsonl"] = _h((out / "preferences.jsonl").read_bytes())
        (out / "temporal.jsonl").write_text("\n".join(json.dumps(r) for r in temp_rows) + "\n")
        manifest_files["temporal.jsonl"] = _h((out / "temporal.jsonl").read_bytes())
        (out / "hf" / "README.md").write_text(
            "# Dataset card\n\nProcedural-test + project snapshots exported by Framebound v2.\n\n"
            "- `hf/`: Hugging Face imagefolder (loadable with `datasets.load_dataset(\"imagefolder\", data_dir=...)`).\n"
            "- `coco/annotations.json`: COCO instances (bbox + RLE from alpha or SAM masks; mask source recorded per row).\n"
            "- `preferences.jsonl`: chosen/rejected pairs with conditioning, issue code, and reason.\n"
            "- `temporal.jsonl`: clip sequences with holds, loop flag, and evaluation ids.\n\n"
            "## Label semantics\n\n- `human-approved`: technical pass + human approval event for the exact revision.\n"
            "- `weak-negative`: failed frames with named issue codes — valid negatives, never positives.\n"
            "- `procedural-test`: synthetic fixtures — regressions/demos, excluded from positives by default.\n"
            "- `derived`: repeated holds / rigid translations / composites — lineage in `derivation_recipe`.\n"
            "Technical status and human decision are separate fields. Moving this directory preserves all references.\n")
        manifest_files["hf/README.md"] = _h((out / "hf" / "README.md").read_bytes())
        manifest = {"snapshot": snapshot_name, "dataset_version": DATASET_VERSION,
                    "schemas": {"domain": "2.0"}, "dependency_lock_id": "export-validation-1",
                    "clip_revisions": clip_revision_ids, "policy": pol, "files": manifest_files,
                    "exclusions": exclusions,
                    "counts": {"images": len(coco_images), "annotations": len(coco_anns),
                               "preferences": len(pref_rows), "temporal": len(temp_rows)}}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest
    finally:
        con.close()
