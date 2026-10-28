"""Snapshot builder. Frozen explicit selection; honest portable training labels.

Views (named, documented in the dataset card):
- positives (`hf/` imagefolder): frames whose revision is currently eligible
  (technical PASS + COMPLETE, fresh evidence, packet-bound human approval for
  the exact revision+evaluation, no unresolved blocking tasks) AND whose asset
  passes rights + procedural policy. Unknown-rights, procedural-unless-opted,
  unreviewed and rejected targets are absent here, with per-frame reasons.
- research (`research/`): every other requested frame with truthful origins —
  a labeled archive, never masquerading as the positive view.
- preferences (`preferences.jsonl`): ONLY explicit pairwise human comparisons
  (a comparison packet binding chosen+rejected plus a reviewer approve decision
  on that packet; same contract). Approval of a descendant alone is insufficient.
- weak preferences (`weak_preferences.jsonl`): technical-ranking view, labeled weak.
- temporal (`temporal.jsonl`): ordered frame records with holds/timing/traces.
- closure (`closure/`): contracts, characters, guides, reference pixels,
  evaluations, attempts, review/comparison decisions, event provenance, masks.

Label origins (never silently relabeled): human-approved, weak-negative,
procedural-test, derived. Moving the directory preserves all references:
no absolute local paths, credentials, or expiring provider URLs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from PIL import Image

from .. import domain as D
from .. import storage as S
from ..checks.raster import alpha_mask, silhouette

DATASET_VERSION = "2.1"


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _silhouette_records(img: Image.Image) -> dict:
    w, h = img.size
    px = img.convert("RGBA").tobytes()
    m = alpha_mask(px, w, h)
    s = silhouette(m, w, h)
    return {"bbox": s["bbox"] or [0, 0, 0, 0], "area": s["area"], "mask": m, "size": [w, h]}


def _rle(mask: bytes | bytearray, w: int, h: int) -> dict:
    """COCO RLE from a row-major 0/1 mask.

    Row-major bytes reshape to (height, width) in C order, then convert to
    Fortran-contiguous for pycocotools. Reinterpreting the stream with
    reshape(order='F') scrambles non-square geometry while preserving area —
    that defect (F09) must never return.
    """
    import numpy as np
    from pycocotools import mask as coco_mask
    if len(mask) != w * h:
        raise ValueError(f"mask {len(mask)} bytes != {w}x{h}")
    arr = np.asfortranarray(np.frombuffer(bytes(mask), dtype=np.uint8).reshape((h, w)))
    r = coco_mask.encode(arr)
    r["counts"] = r["counts"].decode()
    return r


def _root_revision(revs: dict[str, D.ClipRevision], rid: str) -> str:
    cur, seen = rid, 0
    while cur in revs and revs[cur].parent_revision_id and seen < 64:
        cur = revs[cur].parent_revision_id
        seen += 1
    return cur


def _family_key(project_dir: str, con, revs: dict[str, D.ClipRevision],
                rev: D.ClipRevision) -> str:
    """Character/reference/derivation family: one identity must not straddle splits."""
    char_id = _contract_char(con, rev)
    try:
        chdata, _ = S.get(con, "character_revisions", char_id)
    except KeyError:
        chdata = {}
    refs = (chdata.get("identity_asset_ids") or []) + (chdata.get("style_asset_ids") or [])
    px = []
    for aid in refs:
        try:
            adata, _ = S.get(con, "assets", aid)
            px.append(adata.get("pixel_sha256", "?")[:16])
        except KeyError:
            px.append("missing")
    return "|".join([char_id, ",".join(sorted(refs)), ",".join(sorted(px)),
                     f"root={_root_revision(revs, rev.id)}"])




def _contract_char(con, rev: D.ClipRevision) -> str:
    try:
        cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
        return str(cdata.get("character_revision_id", "?"))
    except KeyError:
        return "?"


def _explicit_pairs(project_dir: str, con, revs: dict, evals: dict) -> tuple[list[dict], list[dict]]:
    """Explicit human comparisons vs technical-ranking weak view.

    Explicit: a comparison packet (binds chosen + rejected, same contract)
    with a reviewer approve decision on that packet for the chosen revision.
    Descendant approval alone yields only a weak-ranking entry, never a pair.
    """
    decisions = []
    for r in con.execute("SELECT data FROM review_events").fetchall():
        try:
            raw = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            e = D.ReviewEvent.model_validate(raw)
        except Exception:
            try:
                e = D.ReviewEvent.model_validate(r["data"])
            except Exception:
                continue
        decisions.append(e)
    pairs, weak = [], []
    for r in con.execute("SELECT data FROM review_packets").fetchall():
        pdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        try:
            pkt = D.ReviewPacket.model_validate(pdata)
        except Exception:
            continue
        if not pkt.comparison_revision_id or pkt.clip_revision_id not in revs \
                or pkt.comparison_revision_id not in revs:
            continue
        chosen_ev = evals.get(pkt.clip_revision_id)
        rejected_ev = evals.get(pkt.comparison_revision_id)
        approved = any(d.action == "approve" and d.actor_type == "reviewer"
                       and d.clip_revision_id == pkt.clip_revision_id
                       and d.packet_id == pkt.id for d in decisions)
        entry = {
            "prompt": None,  # filled per slot below
            "conditioning": None,
            "chosen_revision": pkt.clip_revision_id,
            "rejected_revision": pkt.comparison_revision_id,
            "comparison_packet": pkt.id,
            "rejected_issue": None,
            "reason": None,
        }
        if approved and chosen_ev is not None and rejected_ev is not None:
            fails = sorted({x.constraint_id for x in rejected_ev.results
                            if x.outcome in ("fail", "error")})
            entry.update({
                "origin": "human-comparison",
                "rejected_issue": fails[0] if fails else "dispreferred-variant",
                "reason": f"reviewer preferred {pkt.clip_revision_id} over "
                          f"{pkt.comparison_revision_id} via {pkt.id}",
            })
            pairs.append(entry)
        else:
            entry.update({
                "origin": "technical-ranking",
                "reason": "no explicit human comparison on this packet; "
                          "ranking by technical status only",
            })
            weak.append(entry)
    return pairs, weak


def build_snapshot(project_dir: str, snapshot_name: str, clip_revision_ids: list[str],
                   out_dir: str, policy: dict | None = None) -> dict:
    """Build a portable snapshot under a temp dir, validate, atomically publish.

    Returns the manifest. Persists an ExportSnapshot row binding identity,
    policy, selected revisions/evaluations, dependency versions and content.
    """
    pol = {"rights_allow": ["original"], "split": {"train": [], "dev": [], "test": []},
           "split_policy": "exclude", "include_procedural_positives": False,
           "seed": 0}
    pol.update(policy or {})
    from ..safe_output import prepare_output_dir
    out = prepare_output_dir(out_dir, replace=bool(pol.get("replace", False)),
                             tool="framebound-export-snapshot", refuse_inside=project_dir)
    tmp = out.parent / f"{out.name}.tmp-{uuid.uuid4().hex[:12]}"
    tmp.mkdir(parents=True)
    try:
        manifest = _build_into(project_dir, snapshot_name, clip_revision_ids, tmp, pol)
        _self_check(tmp, manifest)
        # atomic publish: out is empty+marked; swap tmp into place
        for child in out.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            else:
                shutil.rmtree(child)
        for child in tmp.iterdir():
            shutil.move(str(child), str(out / child.name))
        _record_snapshot(project_dir, snapshot_name, clip_revision_ids, pol, manifest)
        return manifest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _record_snapshot(project_dir: str, name: str, rids: list[str],
                     pol: dict, manifest: dict) -> None:
    import hashlib as _hh
    lock = Path(project_dir).parent / "requirements.lock"
    repo_lock = Path(__file__).resolve().parents[3] / "requirements.lock"
    digest = ""
    for cand in (repo_lock,):
        if cand.is_file():
            digest = _hh.sha256(cand.read_bytes()).hexdigest()[:16]
            break
    pol_summary = json.dumps({"rights_allow": pol.get("rights_allow"),
                              "procedural_positives": pol.get("include_procedural_positives"),
                              "split_policy": pol.get("split_policy"),
                              "seed": pol.get("seed"),
                              "splits": {k: len(v) for k, v in pol.get("split", {}).items()}})
    row = D.ExportSnapshot(id=f"snap-{name}", clip_revision_ids=rids,
                           policy=pol_summary[:500],
                           dependency_lock_id=f"requirements:{digest}" if digest else "no-lock",
                           byte_manifest={k: v for k, v in manifest["files"].items()})
    con = S.connect(project_dir)
    try:
        try:
            S.insert(con, row)
        except S.ConflictError:
            old, ver = S.get(con, "export_snapshots", row.id)
            if json.loads(json.dumps(old))["byte_manifest"] != row.byte_manifest:
                raise S.ConflictError(f"snapshot {row.id} already recorded with different content")
    finally:
        con.close()


def _self_check(tmp: Path, manifest: dict) -> None:
    for rel, digest in manifest["files"].items():
        p = tmp / rel
        if not p.is_file():
            raise ValueError(f"snapshot self-check: missing {rel}")
        if _h(p.read_bytes()) != digest:
            raise ValueError(f"snapshot self-check: hash mismatch {rel}")


def _build_into(project_dir: str, snapshot_name: str, clip_revision_ids: list[str],
                out: Path, pol: dict) -> dict:
    from ..services import eligibility as EL
    (out / "hf" / "data").mkdir(parents=True, exist_ok=True)
    (out / ".framebound-output").write_text(json.dumps(
        {"tool": "framebound-export-snapshot", "snapshot": snapshot_name}) + "\n")
    manifest_files_marker = {".framebound-output": _h((out / ".framebound-output").read_bytes())}
    (out / "research" / "media").mkdir(parents=True, exist_ok=True)
    (out / "coco").mkdir(parents=True, exist_ok=True)
    (out / "closure" / "references").mkdir(parents=True, exist_ok=True)
    (out / "closure" / "masks").mkdir(parents=True, exist_ok=True)
    con = S.connect(project_dir)
    try:
        revs, contracts, evals = {}, {}, {}
        for rid in clip_revision_ids:
            try:
                rdata, _ = S.get(con, "clip_revisions", rid)
            except KeyError:
                raise ValueError(f"unknown clip revision {rid}")
            rev = D.ClipRevision.model_validate(rdata)
            revs[rid] = rev
            cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
            contracts[rid] = D.ClipContractRevision.model_validate(cdata)
        for rid in clip_revision_ids:
            rows = con.execute("SELECT data FROM evaluations").fetchall()
            mine = [D.Evaluation.model_validate(json.loads(r["data"]) if isinstance(r["data"], str) else r["data"])
                    for r in rows
                    if (json.loads(r["data"]) if isinstance(r["data"], str) else r["data"])["clip_revision_id"] == rid]
            if mine:
                mine.sort(key=lambda e: (e.created_at, e.id))
                evals[rid] = mine[-1]
        frames: dict[str, dict] = {}
        for rid, rev in revs.items():
            for fid in rev.frame_instance_ids:
                fdata, _ = S.get(con, "frame_instances", fid)
                fi = D.FrameInstance.model_validate(fdata)
                adata, _ = S.get(con, "assets", fi.asset_id)
                frames[fid] = {"fi": fi, "asset": D.Asset.model_validate(adata), "rev": rid}
        # eligibility per revision (current: technical + approval + fresh + quiet)
        eligible = {}
        for rid in clip_revision_ids:
            rep = EL.release_eligibility(project_dir, rid)
            eligible[rid] = rep
        families = {rid: _family_key(project_dir, con, revs, rev) for rid, rev in revs.items()}
        # split membership + family/duplicate validation
        split_of = {}
        for s, ids in pol["split"].items():
            for rid in ids or []:
                if rid in clip_revision_ids:
                    split_of[rid] = s
        dup_px: dict[str, list[str]] = {}
        for fid, fr in frames.items():
            dup_px.setdefault(fr["asset"].pixel_sha256, []).append(f"{fr['rev']}:{fr['fi'].slot}")
        manifest_files: dict[str, str] = {}
        exclusions: list[dict] = []

        def exclude(asset_id: str | list, reason: str, context: str) -> None:
            exclusions.append({"asset": asset_id, "reason": reason, "context": context})

        # family + duplicate leakage across differing splits
        for s1, ids1 in (pol["split"] or {}).items():
            for s2, ids2 in (pol["split"] or {}).items():
                if s1 >= s2:
                    continue
                fam1 = {families[r] for r in (ids1 or []) if r in families}
                fam2 = {families[r] for r in (ids2 or []) if r in families}
                shared = fam1 & fam2
                if shared:
                    msg = (f"split leakage: family {sorted(shared)[:2]} in {s1}+{s2}; "
                           f"with one character family, {s2} cannot claim held-out identity")
                    if pol["split_policy"] == "strict":
                        raise ValueError(msg)
                    exclude(sorted(shared)[:2], msg, "split-family")
        px_splits: dict[str, set[str]] = {}
        for fid, fr in frames.items():
            px_splits.setdefault(fr["asset"].pixel_sha256, set()).add(
                split_of.get(fr["rev"], "unsplit"))
        for px, splits in px_splits.items():
            real = {s for s in splits if s != "unsplit"}
            if len(real) > 1:
                msg = f"exact pixel duplicate across splits {sorted(real)}"
                if pol["split_policy"] == "strict":
                    raise ValueError(msg)
                exclude(px[:16], msg, "split-duplicate")

        coco_images, coco_anns, ann_id = [], [], 0
        meta_rows, research_rows = [], []
        pos_count = 0
        for rid, rev in revs.items():
            contract = contracts[rid]
            ev = evals.get(rid)
            rep = eligible[rid]
            split = split_of.get(rid, "unsplit")
            for fid in rev.frame_instance_ids:
                fr = frames[fid]
                fi, a = fr["fi"], fr["asset"]
                reasons = []
                if a.rights not in pol["rights_allow"]:
                    reasons.append(f"rights {a.rights!r} not in {pol['rights_allow']}")
                if a.source_kind == "procedural" and not pol["include_procedural_positives"]:
                    reasons.append("procedural-test: valid regression, not a training positive")
                if not rep["eligible"]:
                    reasons.append("revision ineligible: " + "; ".join(rep["reasons"][:2]))
                blob = S.blob_path(project_dir, a.byte_sha256)
                img = Image.open(blob).convert("RGBA")
                rec = _silhouette_records(img)
                rle = _rle(rec["mask"], *rec["size"])
                img_id = len(coco_images)
                if reasons:
                    # research archive: full original preserved, truthful origin
                    rel = f"research/media/{a.id}.png"
                    dest = out / rel
                    dest.write_bytes(blob.read_bytes())
                    manifest_files[rel] = _h(dest.read_bytes())
                    for r_ in reasons:
                        exclude(a.id, r_, "positive")
                    failing = bool(ev and any(r.outcome in ("fail", "error")
                                                       for r in ev.results
                                                       if r.scope == f"slot {fi.slot}"))
                    research_rows.append(_row(rid, rev, fi, ev, split, a, fi, families[rid],
                                             origin=("procedural-test" if a.source_kind == "procedural"
                                                     else "weak-negative" if failing
                                                     else "unreviewed" if not rep["eligible"]
                                                     else "withheld"),
                                             file_ref=f"../{rel}", exclusion=reasons[0]))
                    img_ref = f"../{rel}"
                else:
                    rel = f"hf/data/{rid}-{fi.slot:02d}.png"
                    dest = out / rel
                    img.save(dest)
                    manifest_files[rel] = _h(dest.read_bytes())
                    pos_count += 1
                    meta_rows.append(_row(rid, rev, fi, ev, split, a, fi, families[rid],
                                          origin="human-approved", file_ref=f"data/{rid}-{fi.slot:02d}.png",
                                          exclusion=None))
                    img_ref = f"../{rel}"
                coco_images.append({"id": img_id, "file_name": img_ref,
                                    "width": rec["size"][0], "height": rec["size"][1],
                                    "clip_revision_id": rid, "slot": fi.slot,
                                    "asset_id": a.id, "pixel_sha256": a.pixel_sha256,
                                    "mask_source": "alpha"})
                coco_anns.append({"id": ann_id, "image_id": img_id, "category_id": 0,
                                  "bbox": [rec["bbox"][0], rec["bbox"][1],
                                           rec["bbox"][2] - rec["bbox"][0], rec["bbox"][3] - rec["bbox"][1]],
                                  "area": rec["area"], "segmentation": rle,
                                  "iscrowd": 0})
                ann_id += 1
        # preferences: explicit comparisons only; weak view separated
        pairs, weak = _explicit_pairs(project_dir, con, revs, evals)
        pref_rows = []
        for pr in pairs:
            ch, rj = pr["chosen_revision"], pr["rejected_revision"]
            ch_files = _rev_files(out, ch, frames)
            rj_files = _rev_files(out, rj, frames)
            pref_rows.append({
                "prompt": f"{contracts[ch].action.name} clip (contract {contracts[ch].id})",
                "conditioning": {"contract": contracts[ch].id,
                                 "chosen_evaluation": evals[ch].id if ch in evals else None,
                                 "rejected_evaluation": evals[rj].id if rj in evals else None,
                                 "execution": "correction repair recipe + contract conditioning; "
                                 "not identical generation prompts"},
                "chosen": ch_files, "chosen_revision": ch,
                "rejected": rj_files, "rejected_revision": rj,
                "rejected_issue": pr["rejected_issue"],
                "origin": "human-comparison",
                "comparison_packet": pr["comparison_packet"],
                "reason": pr["reason"],
                "split": split_of.get(ch, "unsplit")})
        weak_rows = [{**w, "conditioning": "technical status only; no human comparison",
                      } for w in weak]
        # temporal with ordered resolvable refs + explicit missing coverage
        temp_rows = []
        for rid, rev in revs.items():
            contract = contracts[rid]
            ev = evals.get(rid)
            order = []
            for fid in rev.frame_instance_ids:
                fr = frames[fid]
                fi = fr["fi"]
                in_pos = (out / "hf" / "data" / f"{rid}-{fi.slot:02d}.png").exists()
                rel = (f"hf/data/{rid}-{fi.slot:02d}.png" if in_pos
                       else f"research/media/{fr['asset'].id}.png")
                order.append({"slot": fi.slot, "frame_instance_id": fid,
                              "asset_id": fi.asset_id,
                              "pixel_sha256": fr["asset"].pixel_sha256,
                              "file": rel, "hold_ticks": fi.hold_ticks,
                              "phase": fi.phase,
                              "registration_id": fi.registration_id,
                              "derivation_recipe": fi.derivation_recipe})
            temp_rows.append({
                "clip_revision_id": rid, "contract_revision_id": rev.contract_revision_id,
                "frames": order, "holds": contract.timing.holds,
                "ticks_per_second": contract.timing.ticks_per_second,
                "total_ticks": sum(contract.timing.holds),
                "loop": contract.action.loop,
                "terminal": "hold-last" if not contract.action.loop else "loop",
                "traces": {"world_positions": None, "planted": None,
                           "transition": None,
                           "missing": ["world_positions", "planted", "transition_traces"],
                           "presented_holds": [f["hold_ticks"] for f in order]},
                "evaluation_id": ev.id if ev else None,
                "technical_status": ev.technical_status.value if ev else "unevaluated"})
        # closure: contracts, characters, guides, pixels, evals, events, attempts, masks
        closure: dict[str, str] = {}
        cond = {"contracts": {rid: contracts[rid].model_dump(mode="json") for rid in revs}}
        chars = {}
        for rid in revs:
            cid = contracts[rid].character_revision_id
            try:
                cdata, _ = S.get(con, "character_revisions", cid)
                chars[cid] = cdata
            except KeyError:
                pass
        cond["characters"] = chars
        guides = {}
        for r in con.execute("SELECT data FROM motion_guides").fetchall():
            gdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            guides[gdata["id"]] = gdata
        cond["motion_guides"] = guides
        (out / "closure" / "conditioning.json").write_text(json.dumps(cond, indent=2))
        # reference pixels
        ref_aids = set()
        for c in cond["contracts"].values():
            ref = c.get("references", {})
            for k in ("identity", "style"):
                if ref.get(k):
                    ref_aids.add(ref[k])
        for g in guides.values():
            for e in g.get("entries", []):
                ref_aids.add(e["asset_id"])
        for aid in sorted(a for a in ref_aids if a):
            try:
                adata, _ = S.get(con, "assets", aid)
            except KeyError:
                exclusions.append({"asset": aid, "reason": "reference asset missing from store",
                                   "context": "closure"})
                continue
            dest = out / "closure" / "references" / f"{aid}.png"
            dest.write_bytes(S.blob_path(project_dir, adata["byte_sha256"]).read_bytes())
        eval_rows = []
        for rid, ev in evals.items():
            eval_rows.append(ev.model_dump(mode="json"))
        (out / "closure" / "evaluations.jsonl").write_text(
            "\n".join(json.dumps(r) for r in eval_rows) + ("\n" if eval_rows else ""))
        evt_rows = []
        for r in con.execute("SELECT data FROM review_events").fetchall():
            evt_rows.append(r["data"] if isinstance(r["data"], str)
                            else json.dumps(r["data"]))
        (out / "closure" / "events.jsonl").write_text("\n".join(evt_rows) + ("\n" if evt_rows else ""))
        att_rows = []
        for r in con.execute("SELECT data FROM attempts").fetchall():
            att_rows.append(r["data"] if isinstance(r["data"], str)
                            else json.dumps(r["data"]))
        (out / "closure" / "attempts.jsonl").write_text("\n".join(att_rows) + ("\n" if att_rows else ""))
        mask_rows = []
        for r in con.execute("SELECT data FROM edit_masks").fetchall():
            mdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            mask_rows.append(mdata)
            try:
                adata, _ = S.get(con, "assets", mdata["mask_asset_id"])
                dest = out / "closure" / "masks" / f"{mdata['id']}.png"
                dest.write_bytes(S.blob_path(project_dir, adata["byte_sha256"]).read_bytes())
            except KeyError:
                pass
        (out / "closure" / "masks.jsonl").write_text(
            "\n".join(json.dumps(r) for r in mask_rows) + ("\n" if mask_rows else ""))
        # write data files
        (out / "coco" / "annotations.json").write_text(json.dumps(
            {"images": coco_images, "annotations": coco_anns,
             "categories": [{"id": 0, "name": "character", "supercategory": "character"}]}))
        manifest_files["coco/annotations.json"] = _h((out / "coco" / "annotations.json").read_bytes())
        (out / "hf" / "metadata.jsonl").write_text(
            "\n".join(json.dumps(r) for r in meta_rows) + ("\n" if meta_rows else ""))
        manifest_files["hf/metadata.jsonl"] = _h((out / "hf" / "metadata.jsonl").read_bytes())
        (out / "research" / "metadata.jsonl").write_text(
            "\n".join(json.dumps(r) for r in research_rows) + ("\n" if research_rows else ""))
        manifest_files["research/metadata.jsonl"] = _h((out / "research" / "metadata.jsonl").read_bytes())
        (out / "preferences.jsonl").write_text(
            "\n".join(json.dumps(r) for r in pref_rows) + ("\n" if pref_rows else ""))
        manifest_files["preferences.jsonl"] = _h((out / "preferences.jsonl").read_bytes())
        (out / "weak_preferences.jsonl").write_text(
            "\n".join(json.dumps(r) for r in weak_rows) + ("\n" if weak_rows else ""))
        manifest_files["weak_preferences.jsonl"] = _h((out / "weak_preferences.jsonl").read_bytes())
        (out / "temporal.jsonl").write_text(
            "\n".join(json.dumps(r) for r in temp_rows) + ("\n" if temp_rows else ""))
        manifest_files["temporal.jsonl"] = _h((out / "temporal.jsonl").read_bytes())
        manifest_files["closure/conditioning.json"] = _h((out / "closure" / "conditioning.json").read_bytes())
        manifest_files["closure/evaluations.jsonl"] = _h((out / "closure" / "evaluations.jsonl").read_bytes())
        manifest_files["closure/events.jsonl"] = _h((out / "closure" / "events.jsonl").read_bytes())
        manifest_files["closure/attempts.jsonl"] = _h((out / "closure" / "attempts.jsonl").read_bytes())
        manifest_files["closure/masks.jsonl"] = _h((out / "closure" / "masks.jsonl").read_bytes())
        for p in sorted((out / "closure" / "references").glob("*.png")):
            manifest_files[f"closure/references/{p.name}"] = _h(p.read_bytes())
        for p in sorted((out / "closure" / "masks").glob("*.png")):
            manifest_files[f"closure/masks/{p.name}"] = _h(p.read_bytes())
        (out / "hf" / "README.md").write_text(
            "# Dataset card\n\nFramebound v2 snapshot: positives, research archive, preferences, temporal.\n\n"
            "- `hf/` (imagefolder): ELIGIBLE positives only — current human acceptance + technical pass.\n"
            "  Load with `datasets.load_dataset(\"imagefolder\", data_dir=\"hf\")`. Empty positives is a\n"
            "  legitimate outcome (see manifest exclusions); never invent examples.\n"
            "- `research/`: full requested corpus with truthful origins — regression archive, not positives.\n"
            "- `coco/annotations.json`: every exported frame, RLE from alpha (mask_source recorded).\n"
            "- `preferences.jsonl`: explicit human comparisons only (origin human-comparison).\n"
            "- `weak_preferences.jsonl`: technical-ranking view (origin technical-ranking) — not DPO pairs.\n"
            "- `temporal.jsonl`: ordered frames, holds/timing/traces, explicit missing coverage.\n"
            "- `closure/`: contracts, characters, guides, reference pixels, evaluations, attempts,\n"
            "  review/comparison decisions, event provenance, edit masks. RGBA originals preserved.\n\n"
            "## Label semantics\n\n- `human-approved`: technical pass + packet-bound human approval, current.\n"
            "- `weak-negative`: failed frames with named issue codes — negatives, never positives.\n"
            "- `procedural-test`: synthetic fixtures — regressions/demos, excluded from positives by default.\n"
            "Technical status and human decision are separate fields. Moving this directory preserves refs.\n")
        manifest_files["hf/README.md"] = _h((out / "hf" / "README.md").read_bytes())
        manifest = {"snapshot": snapshot_name, "dataset_version": DATASET_VERSION,
                    "schemas": {"domain": "2.0"}, "dependency_lock_id": "export-validation-1",
                    "clip_revisions": clip_revision_ids, "policy": pol,
                    "files": {**manifest_files_marker, **manifest_files},
                    "exclusions": exclusions, "families": families, "seed": pol.get("seed", 0),
                    "counts": {"images": len(coco_images), "annotations": len(coco_anns),
                               "positives": pos_count, "research": len(research_rows),
                               "preferences": len(pref_rows),
                               "weak_preferences": len(weak_rows),
                               "temporal": len(temp_rows)}}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    finally:
        con.close()
    return manifest


def _row(rid: str, rev: D.ClipRevision, fi, ev, split: str, asset: D.Asset,
         fi2, family: str, origin: str, file_ref: str, exclusion: str | None) -> dict:
    return {"file_name": file_ref, "character": rev.contract_revision_id,
            "clip": rid, "slot": fi.slot, "hold_ticks": fi.hold_ticks,
            "phase": fi.phase,
            "technical_status": ev.technical_status.value if ev else "unevaluated",
            "issue_codes": sorted({r.constraint_id for r in (ev.results if ev else [])
                                   if r.outcome in ("fail", "error")}),
            "human_decision": "approved" if origin == "human-approved" else "unreviewed",
            "label_origin": origin,
            "derivation_recipe": fi.derivation_recipe,
            "source_drawing_id": fi.source_drawing_id,
            "asset_id": asset.id, "rights": asset.rights,
            "source_kind": asset.source_kind,
            "pixel_sha256": asset.pixel_sha256,
            "family": family, "split": split,
            "exclusion": exclusion}


def _rev_files(out: Path, rid: str, frames: dict) -> list[dict]:
    """All packaged files for a revision with pixel hashes (mutation-detectable)."""
    rows = []
    for fp in sorted((out / "hf" / "data").glob(f"{rid}-*.png")):
        rows.append({"file": f"hf/data/{fp.name}", "sha256": _h(fp.read_bytes())})
    for fid, fr in frames.items():
        if fr["rev"] != rid:
            continue
        rp = out / "research" / "media" / f"{fr['asset'].id}.png"
        if rp.is_file():
            rows.append({"file": f"research/media/{rp.name}",
                         "sha256": _h(rp.read_bytes())})
    return rows
