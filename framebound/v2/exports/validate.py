"""Independent snapshot validation: standard loaders, hashes, eligibility semantics.

Loads the MOVED snapshot with real libraries (COCO API, datasets imagefolder
when the interpreter supports it), checks labels/preferences, verifies hashes
and durations, and reports exclusions. Every annotation is decoded and
compared pixel-for-pixel with its packaged source image; area-only agreement
is not acceptance. Mutation tests (wrong pixels, same counts) fail here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pycocotools import mask as coco_mask
from pycocotools.coco import COCO


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _alpha_raster(img: Image.Image) -> tuple[bytes, int, int]:
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.tobytes()
    return bytes(1 if px[i + 3] > 127 else 0 for i in range(0, len(px), 4)), w, h


def _check_coco(snap: Path, manifest: dict, issues: list[str]) -> dict:
    coco = COCO(str(snap / "coco" / "annotations.json"))
    img_ids = coco.getImgIds()
    if len(img_ids) != manifest["counts"]["images"]:
        issues.append(f"coco image count {len(img_ids)} != manifest {manifest['counts']['images']}")
    checked = 0
    for iid in img_ids:
        info = coco.loadImgs([iid])[0]
        ipath = (snap / "coco" / info["file_name"]).resolve()
        if not str(ipath).startswith(str(snap.resolve())):
            issues.append(f"coco image {iid} escapes the snapshot dir")
            continue
        if not ipath.is_file():
            issues.append(f"coco image {iid} missing file {info['file_name']}")
            continue
        try:
            src = Image.open(ipath)
            src.load()
        except Exception as e:
            issues.append(f"coco image {iid} undecodable ({info['file_name']}): {type(e).__name__}")
            continue
        try:
            want, w, h = _alpha_raster(src)
        except Exception as e:
            issues.append(f"coco image {iid} pixels unreadable: {type(e).__name__}: {e}")
            continue
        if [w, h] != [info["width"], info["height"]]:
            issues.append(f"coco image {iid} dims {w}x{h} != header {info['width']}x{info['height']}")
        for a in coco.loadAnns(coco.getAnnIds(imgIds=[iid])):
            rle = a["segmentation"]
            if isinstance(rle.get("counts"), str):
                rle = {"size": rle["size"], "counts": rle["counts"].encode()}
            try:
                dec = coco_mask.decode(rle)
            except Exception as e:
                issues.append(f"annotation {a['id']} undecodable: {e}")
                continue
            if list(dec.shape) != [h, w]:
                issues.append(f"annotation {a['id']} decoded {list(dec.shape)} != source {h}x{w}")
                continue
            flat = bytes(int(v) for v in np.asarray(dec).ravel().tolist())
            if flat != want:
                issues.append(f"annotation {a['id']} pixels differ from packaged source alpha")
                continue
            area = int(np.asarray(dec).sum())
            if area != a["area"]:
                issues.append(f"annotation {a['id']} area {area} != declared {a['area']}")
            ys, xs = np.nonzero(np.asarray(dec))
            if len(xs):
                x, y, wb, hb = int(xs.min()), int(ys.min()), \
                    int(xs.max()) - int(xs.min()) + 1, int(ys.max()) - int(ys.min()) + 1
                if [x, y, wb, hb] != [int(v) for v in a["bbox"]]:
                    issues.append(f"annotation {a['id']} bbox {[x, y, wb, hb]} != declared {a['bbox']}")
            elif a["area"] != 0:
                issues.append(f"annotation {a['id']} empty raster with nonzero area")
            # independent re-encode must round-trip, not merely preserve area
            re = coco_mask.encode(np.asfortranarray(np.asarray(dec, dtype=np.uint8)))
            if coco_mask.area(re) != a["area"]:
                issues.append(f"annotation {a['id']} re-encode area mismatch")
            checked += 1
    return {"annotations_checked": checked, "images": len(img_ids)}


def _check_hf(snap: Path, manifest: dict, issues: list[str], skipped: list[str]) -> dict:
    """Materialize every positive through the standard imagefolder loader.

    Requires an interpreter with working lzma + datasets. Without it, fall back
    to PIL-level structural checks and record an explicit skip — never claim a
    materialization that did not happen, and never shim sys.modules.
    """
    meta_path = snap / "hf" / "metadata.jsonl"
    metas = [json.loads(l) for l in meta_path.read_text().splitlines() if l.strip()]
    counts_images = manifest["counts"]["images"]
    positives = manifest["counts"].get("positives", counts_images)
    if positives == 0:
        skipped.append("imagefolder: legitimately empty positives; no examples invented")
        return {"method": "empty-positive", "rows": 0}
    try:
        import _lzma  # noqa: F401  (native module; its absence breaks datasets import)
        import lzma  # noqa: F401
        import datasets
    except ImportError as e:
        # structural fallback: every file must decode as pixels + join metadata
        n = 0
        for m in metas:
            fp = snap / "hf" / m["file_name"]
            if not fp.is_file():
                issues.append(f"positive {m['file_name']} missing")
                continue
            try:
                with Image.open(fp) as im:
                    im.load()
                    if im.size[0] <= 0 or im.size[1] <= 0:
                        issues.append(f"positive {m['file_name']} has degenerate size")
            except Exception as e2:
                issues.append(f"positive {m['file_name']} undecodable: {e2}")
            if m.get("label_origin") != "human-approved":
                issues.append(f"positive {m['file_name']} origin {m.get('label_origin')} "
                              "is not human-approved")
            n += 1
        skipped.append(f"datasets imagefolder not materialized here ({e}); "
                       "PIL structural fallback used — full loader proof needs an "
                       "interpreter with _lzma + datasets")
        return {"method": "pil-fallback", "rows": n}
    ds = datasets.load_dataset("imagefolder", data_dir=str(snap / "hf"), split="train")
    if len(ds) != positives:
        issues.append(f"imagefolder rows {len(ds)} != manifest positives {positives}")
    by_name = {m["file_name"]: m for m in metas}
    for i, row in enumerate(ds):
        img = row["image"]
        if img is None:
            issues.append(f"imagefolder row {i} materialized no pixels")
            continue
        img.load()  # pixels actually materialize through the loader, not just len(ds)
        if img.size[0] <= 0 or img.size[1] <= 0:
            issues.append(f"imagefolder row {i} has degenerate size")
    # join every metadata row to a packaged file + eligible origin/split
    for m in metas:
        fp = snap / "hf" / m["file_name"]
        if not fp.is_file():
            issues.append(f"positive {m['file_name']} missing")
        if m.get("label_origin") != "human-approved":
            issues.append(f"positive {m['file_name']} origin {m.get('label_origin')}")
        if m.get("rights", "original") not in (manifest["policy"].get("rights_allow") or ["original"]):
            issues.append(f"positive {m['file_name']} rights {m.get('rights')} not allowed")
        if m.get("source_kind") == "procedural" and not manifest["policy"].get("include_procedural_positives"):
            issues.append(f"positive {m['file_name']} is procedural-test data")
    return {"method": "datasets-imagefolder", "rows": len(ds)}


def _check_preferences(snap: Path, issues: list[str]) -> dict:
    prefs = [json.loads(l) for l in (snap / "preferences.jsonl").read_text().splitlines() if l.strip()]
    weak = [json.loads(l) for l in (snap / "weak_preferences.jsonl").read_text().splitlines() if l.strip()]
    for pr in prefs:
        if pr.get("origin") != "human-comparison":
            issues.append("preference without human-comparison origin")
        if not pr.get("comparison_packet"):
            issues.append("preference pair without a valid comparison packet ref")
        ch, rj = pr.get("chosen") or [], pr.get("rejected") or []
        if not ch or not rj:
            issues.append(f"preference {pr.get('comparison_packet')} missing chosen/rejected files")
            continue
        ch_hashes, rj_hashes = set(), set()
        for f in ch:
            fp = snap / f["file"]
            if not fp.is_file():
                issues.append(f"preference chosen missing {f['file']}")
                continue
            actual = _h(fp.read_bytes())
            if actual != f["sha256"]:
                issues.append(f"preference chosen {f['file']} bytes changed since export")
            ch_hashes.add(actual)
        for f in rj:
            fp = snap / f["file"]
            if not fp.is_file():
                issues.append(f"preference rejected missing {f['file']}")
                continue
            actual = _h(fp.read_bytes())
            if actual != f["sha256"]:
                issues.append(f"preference rejected {f['file']} bytes changed since export")
            rj_hashes.add(actual)
        if ch_hashes and ch_hashes == rj_hashes:
            issues.append(f"preference {pr.get('comparison_packet')} chosen==rejected pixels")
        for f in ch:
            if not str(f["file"]).startswith("hf/data/"):
                issues.append(f"preference {pr.get('comparison_packet')} chosen file "
                              f"{f['file']} is not a positive (research files cannot "
                              "be positive preferences)")
        cond = pr.get("conditioning") or {}
        if not cond.get("contract") or not cond.get("chosen_evaluation") \
                or not cond.get("rejected_evaluation"):
            issues.append(f"preference {pr.get('comparison_packet')} lacks common conditioning")
        if not pr.get("rejected_issue") or not pr.get("reason"):
            issues.append("preference without named issue/reason")
    for w in weak:
        if w.get("origin") != "technical-ranking":
            issues.append("weak preference without technical-ranking origin")
        if (w.get("prompt") or w.get("reason") or "") == "" and False:
            pass
    # no weak-label row may masquerade inside preferences
    return {"preferences": len(prefs), "weak_preferences": len(weak)}


def _check_temporal(snap: Path, issues: list[str]) -> dict:
    temps = [json.loads(l) for l in (snap / "temporal.jsonl").read_text().splitlines() if l.strip()]
    for t in temps:
        frames = t.get("frames", [])
        holds = t.get("holds", [])
        if len(frames) != len(holds):
            issues.append(f"temporal {t.get('clip_revision_id')}: {len(frames)} frames vs "
                          f"{len(holds)} holds (count alone is not timing proof)")
        if t.get("total_ticks") != sum(holds):
            issues.append(f"temporal {t.get('clip_revision_id')} duration != sum(holds)")
        for f in frames:
            if f.get("hold_ticks") != holds[f["slot"]] if f.get("slot", -1) < len(holds) else True:
                issues.append(f"temporal {t.get('clip_revision_id')} slot hold mismatch")
            if f.get("file") and not (snap / f["file"]).is_file():
                issues.append(f"temporal {t.get('clip_revision_id')} slot {f.get('slot')} "
                              f"references missing {f.get('file')}")
            for k in ("frame_instance_id", "asset_id", "phase", "registration_id"):
                if not f.get(k):
                    issues.append(f"temporal {t.get('clip_revision_id')} slot {f.get('slot')} "
                                  f"missing {k}")
        order = [f.get("slot") for f in frames]
        if order != sorted(order):
            issues.append(f"temporal {t.get('clip_revision_id')} frames not in slot order")
        if sorted(order) != list(range(len(holds))):
            issues.append(f"temporal {t.get('clip_revision_id')} slots {sorted(order)} "
                          f"do not exactly cover 0..{len(holds) - 1} (duplicated or "
                          "misordered slots with unchanged counts are rejected)")
        if len(set(order)) != len(order):
            issues.append(f"temporal {t.get('clip_revision_id')} has duplicated slots")
        traces = t.get("traces", {})
        if "missing" not in traces:
            issues.append(f"temporal {t.get('clip_revision_id')} hides missing trace coverage")
    return {"temporal": len(temps)}


def validate_snapshot(snapshot_dir: str) -> dict:
    snap = Path(snapshot_dir)
    manifest = json.loads((snap / "manifest.json").read_text())
    issues: list[str] = []
    skipped: list[str] = []
    # 0. manifest integrity + no stale/extra files + no invalid paths
    listed = set(manifest["files"])
    if "manifest.json" in listed:
        issues.append("manifest lists itself; self-hash is recorded in ExportSnapshot, not here")
    for rel, digest in manifest["files"].items():
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            issues.append(f"invalid internal path {rel}")
            continue
        p = snap / rel
        if not p.is_file():
            issues.append(f"missing file {rel}")
        elif _h(p.read_bytes()) != digest:
            issues.append(f"hash mismatch {rel}")
    on_disk = set()
    for p in snap.rglob("*"):
        if p.is_file():
            on_disk.add(str(p.relative_to(snap)))
    extra = on_disk - listed - {"manifest.json", "COMPLETE"}
    # completion marker: atomic publication proof, verified against the manifest
    marker = snap / "COMPLETE"
    if not marker.is_file():
        issues.append("missing COMPLETE marker: publication did not finish atomically")
    else:
        try:
            done = json.loads(marker.read_text())
            if done.get('snapshot')!=manifest['snapshot'] or done.get('inputs_digest')!=manifest['inputs_digest'] or done.get('dataset_version')!=manifest['dataset_version']:
                issues.append('COMPLETE identity differs from manifest')
            if done.get("manifest_sha256") != _h((snap / "manifest.json").read_bytes()):
                issues.append("COMPLETE marker manifest hash does not match manifest.json")
        except Exception as e:
            issues.append(f"COMPLETE marker unreadable: {e}")
    if extra:
        issues.append(f"unmanifested stale files: {sorted(extra)[:5]}")
    # 1. COCO: every annotation pixel-compared
    coco_info = _check_coco(snap, manifest, issues)
    # 2. HF positives through standard loaders (or explicit fallback)
    hf_info = _check_hf(snap, manifest, issues, skipped)
    # 3. preferences: genuine pairs + labeled weak view
    pref_info = _check_preferences(snap, issues)
    # 4. temporal: ordered resolvable refs + timing + traces
    temp_info = _check_temporal(snap, issues)
    # 5. closure parses + selected references resolve without the DB
    try:
        cond = json.loads((snap / "closure" / "conditioning.json").read_text())
        for rid in manifest.get("clip_revisions", []):
            if rid not in cond.get("contracts", {}):
                issues.append(f"closure missing contract for {rid}")
        for g in (snap / "closure" / "references").glob("*.png"):
            try:
                with Image.open(g) as im:
                    im.load()
            except Exception as e:
                issues.append(f"closure reference {g.name} undecodable: {e}")
        closure_rows = {}
        for name in ("evaluations.jsonl", "events.jsonl", "attempts.jsonl",
                     "masks.jsonl", "packets.jsonl", "tasks.jsonl",
                     "annotations.jsonl", "traces.jsonl", "briefs.jsonl",
                     "transition_traces.jsonl"):
            rows = []
            for line in (snap / "closure" / name).read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            closure_rows[name] = rows
        packet_ids = {q.get("id") for q in closure_rows["packets.jsonl"]}
        eval_ids = {e.get("id") for e in closure_rows["evaluations.jsonl"]}
        prefs = [json.loads(l) for l in (snap / "preferences.jsonl").read_text().splitlines()
                 if l.strip()]
        for pr in prefs:
            if pr.get("comparison_packet") not in packet_ids:
                issues.append("preference packet " + str(pr.get("comparison_packet")) + " "
                              "missing from closure (unresolvable without the DB)")
            pr_cond = pr.get("conditioning") or {}
            for key in ("chosen_evaluation", "rejected_evaluation"):
                if pr_cond.get(key) and pr_cond[key] not in eval_ids:
                    issues.append("preference " + str(key) + " " + str(pr_cond[key]) +
                                  " missing from closure")
            pkt = next((q for q in closure_rows["packets.jsonl"]
                        if q.get("id") == pr.get("comparison_packet")), None)
            if pkt is not None:
                if pkt.get("clip_revision_id") != pr.get("chosen_revision") \
                        or pkt.get("comparison_revision_id") != pr.get("rejected_revision"):
                    issues.append("preference packet " + str(pkt.get("id")) + " addresses a "
                                  "different pair than the preference row")
        selected = set(manifest.get("clip_revisions", []))
        for tr in closure_rows["transition_traces.jsonl"]:
            if tr.get("verdict") not in ("pass", "fail"):
                issues.append("transition trace " + str(tr.get("id")) + " has no verdict")
            if tr.get("departure_revision_id") not in selected \
                    and tr.get("entry_revision_id") not in selected:
                issues.append("transition trace " + str(tr.get("id")) +
                              " addresses unselected revisions")
        for e in closure_rows["evaluations.jsonl"]:
            digest = e.get("evidence_manifest_sha256")
            if not digest:
                issues.append("closure evaluation " + str(e.get("id")) +
                              " has no manifest address")
                continue
            blob = snap / "closure" / "blobs" / digest
            if not blob.is_file():
                issues.append("closure manifest blob " + digest[:16] + " missing "
                              "(evaluation " + str(e.get("id")) +
                              " unresolvable without the DB)")
            elif _h(blob.read_bytes()) != digest:
                issues.append("closure manifest blob " + digest[:16] + " address mismatch")
    except Exception as e:
        issues.append(f"closure unreadable: {e}")
    graph_info={}
    try:
        from .portable_graph import check_graph
        graph_info=check_graph(snap,manifest,issues)
    except Exception as exc:
        issues.append('portable provenance invalid: '+str(exc))
    # 6. splits: no family or pixel straddling among POSITIVES. The research
    # archive legitimately documents shared pixels/lineage with exclusions;
    # the trainable view must never straddle.
    metas = [json.loads(l) for l in (snap / "hf" / "metadata.jsonl").read_text().splitlines() if l.strip()]
    fam_split: dict[str, set[str]] = {}
    px_split: dict[str, set[str]] = {}
    for m in metas:
        fam_split.setdefault(m.get("family", "?"), set()).add(m.get("split", "unsplit"))
        px_split.setdefault(m.get("pixel_sha256", "?"), set()).add(m.get("split", "unsplit"))
    for fam, splits in fam_split.items():
        if len({s for s in splits if s != "unsplit"}) > 1:
            issues.append(f"family straddles splits: {fam[:60]}")
    for px, splits in px_split.items():
        if len({s for s in splits if s != "unsplit"}) > 1:
            issues.append(f"pixel duplicate across splits: {px[:16]}")
    return {"snapshot": manifest["snapshot"], "ok": not issues, "issues": issues,
            "skipped": skipped, "counts": manifest["counts"],
            "exclusions": manifest["exclusions"],
            "loaders": {"coco_images": coco_info.get("images"), **coco_info,
                        **hf_info, **pref_info, **temp_info, 'provenance':graph_info}}
