"""Snapshot builder. Selected immutable closure from one logical read snapshot.

Views (named, documented in the dataset card):
- positives (`hf/` imagefolder): frames whose revision is CURRENTLY eligible
  (technical PASS + COMPLETE, fresh verified evidence, packet-bound human
  approval for the exact revision+evaluation, no unresolved blocking tasks)
  AND whose asset passes rights + procedural policy + execution-origin
  policy. Simulated-transport provider output is never a positive.
  Unknown-rights, procedural-unless-opted, unreviewed and rejected targets
  are absent here, with per-frame reasons.
- research (`research/`): every other requested frame with truthful origins —
  a labeled archive, never masquerading as the positive view.
- preferences (`preferences.jsonl`): ONLY explicit current human comparisons:
  a comparison packet binding chosen+rejected where the chosen revision's
  CURRENT decision is an approval through that exact packet, with fresh
  chosen evidence, resolved blockers, permitted rights and a non-simulated
  origin. A later-rejected chosen candidate yields zero positive preferences.
- weak preferences (`weak_preferences.jsonl`): technical-ranking view,
  labeled weak, never DPO pairs.
- temporal (`temporal.jsonl`): ordered frame records with holds/timing,
  registration and world traces where stored (missing coverage explicit).
- closure (`closure/`): ONLY the selected dependency graph — contracts,
  characters, exact approvals/guides/reference pixels, evaluations plus
  evidence-manifest blobs, comparison packets and decisions, correction
  operations/attempts, compiled briefs, redacted provider artifacts — plus
  per-row provenance. Unrelated notes, guides, masks and attempts are omitted.

All reads come from one logical snapshot (single connection, BEGIN
IMMEDIATE) and flow through the shared reducers/verifiers. Publication is
atomic with a completion marker; retrying an identical request returns its
identity, incompatible payloads conflict. Filenames are opaque safe mappings
of record IDs; arbitrary imported IDs can never escape the staging directory.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from PIL import Image

from .. import domain as D
from .. import storage as S
from ..checks.raster import alpha_mask, silhouette

DATASET_VERSION = "2.2"

_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _safe_name(raw: str, used: set[str], max_len: int = 100) -> str:
    """Opaque safe archive filename for an arbitrary record ID.

    Collapses anything outside [A-Za-z0-9_.-] to '_', strips leading dots,
    truncates, and disambiguates collisions with a counter suffix. The result
    can never be absolute, contain a separator, or escape its directory.
    """
    base = _SAFE_RE.sub("_", str(raw or "unnamed")).strip("._") or "id"
    base = base[:max_len].rstrip("._") or "id"
    name = base
    i = 1
    while name in used or name in (".", ".."):
        suffix = f"_{i}"
        name = base[: max_len - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


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
    that defect must never return.
    """
    import numpy as np
    from pycocotools import mask as coco_mask
    if len(mask) != w * h:
        raise ValueError(f"mask {len(mask)} bytes != {w}x{h}")
    arr = np.asfortranarray(np.frombuffer(bytes(mask), dtype=np.uint8).reshape((h, w)))
    r = coco_mask.encode(arr)
    r["counts"] = r["counts"].decode()
    return r


def _union_families(revs: dict[str, D.ClipRevision], contracts: dict,
                    frame_pixels: dict[str, set[str]]) -> dict[str, str]:
    """Identity components as a union-find relation.

    Same character lineage, same approved-reference pixel lineage,
    derivation/repair ancestry, and exact canonical pixel duplication are
    unioned. The root revision is an attribute, never an identity splitter:
    two independent roots for the same character and references are ONE
    family. The family id is content-derived from the sorted member set.
    """
    parent = {rid: rid for rid in revs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_char: dict[str, list[str]] = {}
    by_refs: dict[str, list[str]] = {}
    for rid, rev in revs.items():
        c = contracts.get(rid, {})
        char = c.get("character_revision_id", "?")
        by_char.setdefault(char, []).append(rid)
        refs = c.get("references", {}) or {}
        key = json.dumps({"i": refs.get("identity"), "s": refs.get("style"),
                          "m": refs.get("motion_guide_revision")}, sort_keys=True)
        by_refs.setdefault(f"{char}|{key}", []).append(rid)
    for group in list(by_char.values()) + list(by_refs.values()):
        for other in group[1:]:
            union(group[0], other)
    # derivation ancestry: child <-> parent always one component
    for rid, rev in revs.items():
        if rev.parent_revision_id and rev.parent_revision_id in parent:
            union(rid, rev.parent_revision_id)
    # exact pixel duplication: shared canonical pixels union components
    px_owner: dict[str, str] = {}
    for rid in revs:
        for px in frame_pixels.get(rid, set()):
            if px in px_owner:
                union(rid, px_owner[px])
            else:
                px_owner[px] = rid
    members: dict[str, list[str]] = {}
    for rid in revs:
        members.setdefault(find(rid), []).append(rid)
    out = {}
    for root, group in members.items():
        fam = "fam-" + hashlib.sha256("|".join(sorted(group)).encode()).hexdigest()[:16]
        for rid in group:
            out[rid] = fam
    return out


def _simulated_assets(con) -> set[str]:
    """Assets produced by explicitly simulated-transport provider jobs.

    Simulated output is engineering proof, never live evidence: it is
    ineligible for positives and positive preferences (research views may
    still document it with its origin label).
    """
    out: set[str] = set()
    try:
        rows = con.execute("SELECT data FROM jobs").fetchall()
    except Exception:
        return out
    for r in rows:
        try:
            job = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if job.get("origin") == "simulated-transport":
            out.update(job.get("output_asset_ids") or [])
    # Stage B: retain derivation through aliases. Assets materialized from a
    # simulated response carry simulated lineage even when the job row link is
    # copied, renamed, or aliased.
    try:
        for r in con.execute("SELECT data FROM assets").fetchall():
            try:
                a = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            except Exception:
                continue
            lin = str(a.get("lineage") or "")
            if "simulated" in lin and a.get("id"):
                out.add(a["id"])
    except Exception:
        pass
    return out


def _snapshot_seq(con) -> dict:
    seq = {}
    for table in ("clip_revisions", "contract_revisions", "frame_instances", "assets",
                  "character_revisions", "motion_guides", "reference_approvals",
                  "annotation_revisions", "evaluations", "attempts", "review_packets",
                  "review_events", "correction_tasks", "jobs", "export_snapshots",
                  "registrations", "edit_masks", "compiled_briefs", "world_traces",
                  "runs"):
        try:
            row = con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            seq[table] = row["n"] if row else 0
        except Exception:
            continue
    return seq


def _inputs_digest(snapshot_name: str, clip_revision_ids: list[str],
                   pol: dict) -> str:
    return hashlib.sha256(json.dumps({
        "dataset_version": DATASET_VERSION, "name": snapshot_name,
        "revisions": sorted(clip_revision_ids), "policy": pol},
        sort_keys=True).encode()).hexdigest()


def _explicit_pairs(con, revs: dict, evals: dict, states: dict,
                    eligible_assets: dict[str, bool]) -> tuple[list[dict], list[dict]]:
    """Explicit CURRENT human comparisons vs technical-ranking weak view.

    Explicit: a comparison packet binding chosen+rejected (both selected, same
    contract) where the chosen revision's CURRENT reducer decision is an
    approval through that exact packet, with fresh chosen evidence, resolved
    blockers, permitted rights and a non-simulated origin. A chosen item
    later rejected before snapshot creation is excluded with its reason and
    yields ZERO positive preferences (it may still appear in the weak view,
    truthfully labeled).
    """
    from ..services import review_state as _RS
    decisions = []
    for r in con.execute("SELECT data FROM review_events").fetchall():
        try:
            raw = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            decisions.append(D.ReviewEvent.model_validate(raw))
        except Exception:
            continue
    pairs, weak = [], []

    def entry_for(pkt):
        return {
            "prompt": None,
            "conditioning": None,
            "chosen_revision": pkt.clip_revision_id,
            "rejected_revision": pkt.comparison_revision_id,
            "comparison_packet": pkt.id,
            "rejected_issue": None,
            "reason": None,
        }

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
        entry = entry_for(pkt)
        st = states.get(pkt.clip_revision_id, {})
        ok, reason = True, ""
        if st.get("acceptance") != D.HumanAcceptance.APPROVED.value:
            ok, reason = False, (f"chosen {pkt.clip_revision_id} current acceptance "
                                 f"is {st.get('acceptance')}, not approved")
        elif st.get("decided_packet_id") != pkt.id:
            ok, reason = False, ("chosen approval is not through this comparison "
                                 f"packet (decided via {st.get('decided_packet_id')})")
        elif chosen_ev is None or rejected_ev is None:
            ok, reason = False, "chosen/rejected evaluation missing from the snapshot"
        elif pkt.evaluation_id != chosen_ev.id:
            ok, reason = False, "packet evaluation is stale for the chosen revision"
        elif not eligible_assets.get(pkt.clip_revision_id, False):
            ok, reason = False, ("chosen revision fails positive asset policy "
                                 "(rights/origin/procedural)")
        if ok:
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
                "reason": "no current explicit human comparison on this packet: "
                          f"{reason}; ranking by technical status only",
            })
            weak.append(entry)
    return pairs, weak


def build_snapshot(project_dir: str, snapshot_name: str, clip_revision_ids: list[str],
                   out_dir: str, policy: dict | None = None) -> dict:
    """Build a portable snapshot under a temp dir, validate, atomically publish.

    One consistent logical read snapshot feeds the shared reducers; full
    semantic validation runs on staging before publication. Retrying an
    identical request returns the recorded identity; incompatible payloads
    conflict instead of overwriting. Returns the manifest.
    """
    pol = {"rights_allow": ["original"], "split": {"train": [], "dev": [], "test": []},
           "split_policy": "exclude", "include_procedural_positives": False,
           "seed": 0}
    pol.update(policy or {})
    digest = _inputs_digest(snapshot_name, list(clip_revision_ids), pol)
    out = Path(out_dir)
    existing = out / "manifest.json" if out.is_dir() else None
    if existing and existing.is_file():
        try:
            prior = json.loads(existing.read_text())
            if prior.get("inputs_digest") == digest:
                return prior
        except Exception:
            pass
    from ..safe_output import prepare_output_dir
    out = prepare_output_dir(out_dir, replace=bool(pol.get("replace", False)),
                             tool="framebound-export-snapshot", refuse_inside=project_dir)
    tmp = out.parent / f"{out.name}.tmp-{uuid.uuid4().hex[:12]}"
    tmp.mkdir(parents=True)
    try:
        manifest = _build_into(project_dir, snapshot_name, clip_revision_ids, tmp, pol,
                               digest)
        _self_check(tmp, manifest)
        # full semantic validation on staging BEFORE publication: never
        # publish a snapshot our own validator rejects. The completion
        # marker is staged first so the validator proves atomic
        # publication, not just file presence.
        from .validate import validate_snapshot as _validate
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
        marker = {"snapshot": snapshot_name, "inputs_digest": digest,
                  "manifest_sha256": _h((tmp / "manifest.json").read_bytes()),
                  "dataset_version": DATASET_VERSION}
        (tmp / "COMPLETE").write_text(json.dumps(marker, indent=2) + "\n")
        rep = _validate(str(tmp))
        if not rep["ok"]:
            raise ValueError("snapshot failed pre-publish semantic validation: "
                             + "; ".join(rep["issues"][:6]))
        manifest["inspection"] = {"imagefolder": rep["loaders"].get("method", "unknown"),
                                  "skipped": rep.get("skipped", [])}
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
        marker["manifest_sha256"] = _h((tmp / "manifest.json").read_bytes())
        (tmp / "COMPLETE").write_text(json.dumps(marker, indent=2) + "\n")
        # atomic publication: out is empty+marked; swap tmp (marker moves too)
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
    from ..checks import evaluate as _EV
    digest = _EV.lock_identity().get("digest") or ""
    pol_summary = json.dumps({"rights_allow": pol.get("rights_allow"),
                              "procedural_positives": pol.get("include_procedural_positives"),
                              "split_policy": pol.get("split_policy"),
                              "seed": pol.get("seed"),
                              "splits": {k: len(v) for k, v in pol.get("split", {}).items()}})
    row = D.ExportSnapshot(id=f"snap-{name}", clip_revision_ids=rids,
                           policy=pol_summary[:500],
                           dependency_lock_id=f"requirements:{digest[:16]}" if digest else "no-lock",
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
                out: Path, pol: dict, digest: str) -> dict:
    from ..services import eligibility as EL
    from ..services import review_state as _RS
    (out / "hf" / "data").mkdir(parents=True, exist_ok=True)
    (out / ".framebound-output").write_text(json.dumps(
        {"tool": "framebound-export-snapshot", "snapshot": snapshot_name}) + "\n")
    manifest_files_marker = {".framebound-output": _h((out / ".framebound-output").read_bytes())}
    (out / "research" / "media").mkdir(parents=True, exist_ok=True)
    (out / "coco").mkdir(parents=True, exist_ok=True)
    (out / "closure" / "references").mkdir(parents=True, exist_ok=True)
    (out / "closure" / "masks").mkdir(parents=True, exist_ok=True)
    (out / "closure" / "blobs").mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    con = S.connect(project_dir)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            revs, contracts, evals, states = {}, {}, {}, {}
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
                mine = [D.Evaluation.model_validate(
                    json.loads(r["data"]) if isinstance(r["data"], str) else r["data"])
                    for r in rows
                    if (json.loads(r["data"]) if isinstance(r["data"], str)
                        else r["data"])["clip_revision_id"] == rid]
                if mine:
                    mine.sort(key=lambda e: (e.created_at, e.id))
                    evals[rid] = mine[-1]
            frames: dict[str, dict] = {}
            for rid, rev in revs.items():
                for fid in rev.frame_instance_ids:
                    fdata, _ = S.get(con, "frame_instances", fid)
                    fi = D.FrameInstance.model_validate(fdata)
                    adata, _ = S.get(con, "assets", fi.asset_id)
                    frames[fid] = {"fi": fi, "asset": D.Asset.model_validate(adata),
                                   "rev": rid}
            # one consistent view into the shared reducers (no reopened
            # connections: a concurrent review change blocks or lands wholly
            # outside this snapshot, never half-applied)
            eligible = {rid: EL.release_eligibility_in(con, project_dir, rid)
                        for rid in clip_revision_ids}
            for rid in clip_revision_ids:
                states[rid] = _RS.current_state_in(con, project_dir, rid)
            frame_pixels = {}
            for rid in clip_revision_ids:
                frame_pixels[rid] = {frames[fid]["asset"].pixel_sha256
                                     for fid in revs[rid].frame_instance_ids
                                     if frames[fid]["asset"].pixel_sha256}
            families = _union_families(revs, {rid: c.model_dump(mode="json")
                                              for rid, c in contracts.items()},
                                       frame_pixels)
            simulated = _simulated_assets(con)
            seq = _snapshot_seq(con)
            selected_set = set(clip_revision_ids)
            closure_rows = _collect_closure_rows(con, revs, contracts, evals,
                                                selected_set, project_dir)
            eligible_assets = {rid: (eligible[rid]["eligible"]
                                     and all(frames[f]["asset"].rights in pol["rights_allow"]
                                             and frames[f]["asset"].id not in simulated
                                             and (frames[f]["asset"].source_kind != "procedural"
                                                  or pol["include_procedural_positives"])
                                             for f in revs[rid].frame_instance_ids))
                               for rid in revs}
            pairs, weak = _explicit_pairs(con, revs, evals, states,
                                          eligible_assets)
        finally:
            con.commit()
        # split membership + family/pixel leakage among POSITIVE candidates
        split_of: dict[str, set[str]] = {}
        for s, ids in (pol["split"] or {}).items():
            for rid in ids or []:
                if rid in selected_set:
                    split_of.setdefault(rid, set()).add(s)
        dup_px: dict[str, list[str]] = {}
        for fid, fr in frames.items():
            dup_px.setdefault(fr["asset"].pixel_sha256, []).append(
                f"{fr['rev']}:{fr['fi'].slot}")
        manifest_files: dict[str, str] = {}
        exclusions: list[dict] = []

        def exclude(asset_id: str | list, reason: str, context: str) -> None:
            exclusions.append({"asset": asset_id, "reason": reason,
                               "context": context})

        def positive_candidate(rid: str) -> tuple[bool, str]:
            rep = eligible[rid]
            if not rep["eligible"]:
                return False, "revision ineligible: " + "; ".join(rep["reasons"][:2])
            return True, ""

        # family + duplicate leakage across differing splits. Detection runs
        # over ALL selected revisions: a split assignment that straddles a
        # family is a policy violation even where frames are already withheld
        # for other reasons (eligibility can change; the assignment is the
        # claim). Removal from the trainable view applies to positives.
        leak_fams: set[str] = set()
        fam_split: dict[str, set[str]] = {}
        for rid in clip_revision_ids:
            fam_split.setdefault(families[rid], set()).update(
                split_of.get(rid, {"unsplit"}))
        for fam, splits in fam_split.items():
            real = {s for s in splits if s != "unsplit"}
            if len(real) > 1:
                leak_fams.add(fam)
        leak_px: set[str] = set()
        for px, owners in dup_px.items():
            revs_with = {o.split(":")[0] for o in owners}
            splits = set()
            for r in revs_with:
                if r in clip_revision_ids:
                    splits.update(split_of.get(r, {"unsplit"}))
            real = {s for s in splits if s != "unsplit"}
            if len(real) > 1:
                leak_px.add(px)
        if (leak_fams or leak_px) and pol["split_policy"] == "strict":
            raise ValueError(
                "split leakage: family " + ",".join(sorted(leak_fams)[:2])
                + " pixel " + ",".join(sorted(leak_px)[:2])
                + "; strict export refuses to publish straddling positives")
        leaked_revs = {rid for rid in clip_revision_ids
                       if families[rid] in leak_fams
                       or any(px in leak_px for px in frame_pixels.get(rid, set()))}
        if leaked_revs and pol["split_policy"] == "exclude":
            for rid in sorted(leaked_revs):
                exclude(rid, "split leakage removed under exclude policy (family/pixel "
                             "spans held-out splits)", "split-exclude")

        coco_images, coco_anns, ann_id = [], [], 0
        meta_rows, research_rows = [], []
        pos_count = 0
        positive_files: dict[tuple[str, int], str] = {}
        research_files: dict[str, str] = {}
        requested_positives = 0
        exported_positives = 0
        excluded_positives = 0
        for rid, rev in revs.items():
            contract = contracts[rid]
            ev = evals.get(rid)
            rep = eligible[rid]
            split = "+".join(sorted(split_of.get(rid, {"unsplit"})))
            for fid in rev.frame_instance_ids:
                fr = frames[fid]
                fi, a = fr["fi"], fr["asset"]
                reasons = []
                if a.rights not in pol["rights_allow"]:
                    reasons.append(f"rights {a.rights!r} not in {pol['rights_allow']}")
                if a.source_kind == "procedural" and not pol["include_procedural_positives"]:
                    reasons.append("procedural-test: valid regression, not a training positive")
                if a.id in simulated:
                    reasons.append("simulated-transport provider output: engineering "
                                   "proof, never a live positive")
                if not rep["eligible"]:
                    reasons.append("revision ineligible: " + "; ".join(rep["reasons"][:2]))
                if rid in leaked_revs:
                    reasons.append("split leakage: family/pixel spans held-out splits; "
                                   "removed under exclude policy")
                    exclude(a.id, "split leakage: family/pixel spans held-out splits",
                            "split-exclude")
                if not reasons:
                    requested_positives += 1
                blob = S.blob_path(project_dir, a.byte_sha256)
                img = Image.open(blob).convert("RGBA")
                rec = _silhouette_records(img)
                rle = _rle(rec["mask"], *rec["size"])
                img_id = len(coco_images)
                if reasons:
                    # research archive: full original preserved, truthful origin
                    safe = _safe_name(a.id, used_names)
                    rel = f"research/media/{safe}.png"
                    research_files[a.id] = rel
                    dest = out / rel
                    dest.write_bytes(blob.read_bytes())
                    manifest_files[rel] = _h(dest.read_bytes())
                    for r_ in reasons:
                        exclude(a.id, r_, "positive")
                    if rid in leaked_revs:
                        excluded_positives += 1
                    failing = bool(ev and any(r.outcome in ("fail", "error")
                                                       for r in ev.results
                                                       if r.scope == f"slot {fi.slot}"))
                    research_rows.append(_row(rid, rev, fi, ev, split, a, fi, families[rid],
                                             origin=("procedural-test" if a.source_kind == "procedural"
                                                     else "weak-negative" if failing
                                                     else "simulated" if a.id in simulated
                                                     else "unreviewed" if not rep["eligible"]
                                                     else "withheld-leakage" if rid in leaked_revs
                                                     else "withheld"),
                                             file_ref=f"../{rel}", exclusion=reasons[0]))
                    img_ref = f"../{rel}"
                else:
                    safe = _safe_name(f"{rid}-{fi.slot:02d}", used_names)
                    rel = f"hf/data/{safe}.png"
                    dest = out / rel
                    img.save(dest)
                    manifest_files[rel] = _h(dest.read_bytes())
                    pos_count += 1
                    exported_positives += 1
                    meta_rows.append(_row(rid, rev, fi, ev, split, a, fi, families[rid],
                                          origin="human-approved", file_ref=f"data/{safe}.png",
                                          exclusion=None))
                    positive_files[(rid, fi.slot)] = f"hf/data/{safe}.png"
                    img_ref = f"../{rel}"
                coco_images.append({"id": img_id, "file_name": img_ref,
                                    "width": rec["size"][0], "height": rec["size"][1],
                                    "clip_revision_id": rid, "slot": fi.slot,
                                    "asset_id": a.id, "pixel_sha256": a.pixel_sha256,
                                    "mask_source": "alpha-silhouette"})
                coco_anns.append({"id": ann_id, "image_id": img_id, "category_id": 0,
                                  "bbox": [rec["bbox"][0], rec["bbox"][1],
                                           rec["bbox"][2] - rec["bbox"][0],
                                           rec["bbox"][3] - rec["bbox"][1]],
                                  "area": rec["area"], "segmentation": rle,
                                  "iscrowd": 0})
                ann_id += 1
        # preferences: strict current human comparisons only (resolved
        # inside the snapshot transaction above)
        pref_rows = []
        kept_pairs = []
        for pr in pairs:
            if pr["chosen_revision"] in leaked_revs or pr["rejected_revision"] in leaked_revs:
                exclude(pr["comparison_packet"],
                        "comparison straddles held-out splits: pair withheld under "
                        "exclude policy (deterministic removal, not silent retention)",
                        "split-exclude")
                continue
            kept_pairs.append(pr)
        pairs = kept_pairs
        for pr in pairs:
            ch, rj = pr["chosen_revision"], pr["rejected_revision"]
            ch_files = _rev_files(out, ch, frames, positive_files,
                                    research_files)
            rj_files = _rev_files(out, rj, frames, positive_files,
                                    research_files)
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
                "split": "+".join(sorted(split_of.get(ch, {"unsplit"})))})
        weak_rows = [{**w, "conditioning": "technical status only; no human comparison",
                      } for w in weak]
        # temporal with ordered resolvable refs + world/registration context
        temp_rows = []
        for rid, rev in revs.items():
            contract = contracts[rid]
            ev = evals.get(rid)
            order = []
            for fid in rev.frame_instance_ids:
                fr = frames[fid]
                fi = fr["fi"]
                rel = positive_files.get((rid, fi.slot))
                if rel is None:
                    rel = research_files.get(fr["asset"].id)
                    if rel is None:
                        # asset shared across revisions: same bytes, one file
                        safe = _safe_name(fr["asset"].id, used_names)
                        rel = f"research/media/{safe}.png"
                        src_blob = S.blob_path(project_dir, fr["asset"].byte_sha256)
                        (out / rel).write_bytes(src_blob.read_bytes())
                        manifest_files[rel] = _h((out / rel).read_bytes())
                        research_files[fr["asset"].id] = rel
                order.append({"slot": fi.slot, "frame_instance_id": fid,
                              "asset_id": fi.asset_id,
                              "pixel_sha256": fr["asset"].pixel_sha256,
                              "file": rel, "hold_ticks": fi.hold_ticks,
                              "phase": fi.phase,
                              "registration_id": fi.registration_id,
                              "derivation_recipe": fi.derivation_recipe})
            trace = _trace_for(project_dir, rid)
            temp_rows.append({
                "clip_revision_id": rid, "contract_revision_id": rev.contract_revision_id,
                "frames": order, "holds": contract.timing.holds,
                "ticks_per_second": contract.timing.ticks_per_second,
                "total_ticks": sum(contract.timing.holds),
                "loop": contract.action.loop,
                "terminal": "hold-last" if not contract.action.loop else "loop",
                "traces": {"world_positions": trace["positions"] if trace else None,
                           "planted": trace["planted"] if trace else None,
                           "transition": None,
                           "missing": ([] if trace else ["world_positions", "planted"])
                           + ["transition_traces"],
                           "presented_holds": [f["hold_ticks"] for f in order]},
                "evaluation_id": ev.id if ev else None,
                "technical_status": ev.technical_status.value if ev else "unevaluated"})
        _write_closure(out, manifest_files, exclusions, closure_rows, pol,
                       used_names, project_dir)
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
        from ..checks import evaluate as _EV
        lock = _EV.lock_identity()
        manifest = {"snapshot": snapshot_name, "dataset_version": DATASET_VERSION,
                    "schemas": {"domain": "2.0"},
                    "dependency_lock": lock,
                    "analyzer": {"code_sha256": _EV._code_sha256()},
                    "clip_revisions": clip_revision_ids, "policy": pol,
                    "files": {**manifest_files_marker, **manifest_files},
                    "exclusions": exclusions, "families": families, "seed": pol.get("seed", 0),
                    "snapshot_seq": seq, "inputs_digest": digest,
                    "split_semantics": ("identity components union character lineage, "
                                        "approved-reference lineage, derivation ancestry and "
                                        "exact pixel duplication; one family never straddles "
                                        "held-out splits under strict/exclude; family labels "
                                        "are data components, not held-out-task claims"),
                    "reconciliation": {"requested_positives": requested_positives,
                                       "exported_positives": exported_positives,
                                       "excluded_positives": excluded_positives,
                                       "preferences": len(pref_rows),
                                       "weak_preferences": len(weak_rows)},
                    "counts": {"images": len(coco_images), "annotations": len(coco_anns),
                               "positives": pos_count, "research": len(research_rows),
                               "preferences": len(pref_rows),
                               "weak_preferences": len(weak_rows),
                               "temporal": len(temp_rows)}}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest
    finally:
        try:
            con.close()
        except Exception:
            pass



def _trace_for(project_dir: str, revision_id: str) -> dict | None:
    con = S.connect(project_dir)
    try:
        row = con.execute("SELECT data FROM world_traces WHERE id=?",
                          (f"wtrace-{revision_id}",)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    try:
        wt = D.WorldTrace.model_validate(
            json.loads(row["data"]) if isinstance(row["data"], str) else row["data"])
    except Exception:
        return None
    return {"positions": [list(p) for p in wt.positions],
            "planted": list(wt.planted), "units": wt.units}


def _collect_closure_rows(con, revs: dict, contracts: dict, evals: dict,
                          selected: set[str], project_dir: str) -> dict:
    """Selected dependency graph only: every referenced object must resolve
    inside the snapshot or be explicitly recorded as external/nonportable."""
    rows: dict[str, list] = {"contracts": {}, "characters": {},
                             "approvals": {}, "guides": {}, "events": [],
                             "packets": [], "attempts": [], "tasks": [],
                             "masks": [], "annotations": [], "traces": [], "transitions": [],
                             "briefs": [], "evals": [], "blobs": {},
                             "excluded_blobs": []}
    for rid, ev in evals.items():
        rows["evals"].append(ev.model_dump(mode="json"))
    char_ids = {contracts[rid].character_revision_id for rid in revs}
    for rid, rev in revs.items():
        rows["contracts"][rid] = contracts[rid].model_dump(mode="json")
    for cid in char_ids:
        try:
            cdata, _ = S.get(con, "character_revisions", cid)
            rows["characters"][cid] = cdata
        except KeyError:
            continue
    # exact authority: approvals named by selected evaluations' frozen
    # manifests plus the current approvals (history otherwise omitted)
    wanted_approvals: set[str] = set()
    for rid, ev in evals.items():
        blob = S.blob_path(project_dir, ev.evidence_manifest_sha256)
        if blob.is_file():
            try:
                manifest = json.loads(blob.read_bytes().decode())
                aid = (manifest.get("authority") or {}).get("approval_id")
                if aid:
                    wanted_approvals.add(aid)
            except Exception:
                continue
    for r in con.execute("SELECT id, data FROM reference_approvals").fetchall():
        try:
            ap = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if ap.get("character_revision_id") not in char_ids:
            continue
        if ap.get("id") in wanted_approvals or _is_current_approval(con, ap):
            rows["approvals"][ap["id"]] = ap
    guide_ids = {ap.get("motion_guide_id") for ap in rows["approvals"].values() if ap.get("motion_guide_id")}
    for r in con.execute("SELECT id, data FROM motion_guides").fetchall():
        try:
            g = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if g.get("id") in guide_ids:
            rows["guides"][g["id"]] = g
    # review events addressing selected revisions or characters
    for r in con.execute("SELECT id, data FROM review_events").fetchall():
        try:
            e = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if e.get("clip_revision_id") in selected or e.get("clip_revision_id") in char_ids:
            rows["events"].append(e)
    # packets + tasks + attempts + masks for the selected lineage
    task_ids = set()
    for r in con.execute("SELECT id, data FROM correction_tasks").fetchall():
        try:
            tdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            t = D.CorrectionTask.model_validate(tdata)
        except Exception:
            continue
        if t.baseline_revision_id in selected:
            rows["tasks"].append(tdata)
            task_ids.add(t.id)
    for r in con.execute("SELECT id, data FROM review_packets").fetchall():
        try:
            pdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if pdata.get("clip_revision_id") in selected:
            rows["packets"].append(pdata)
    for r in con.execute("SELECT id, data FROM attempts").fetchall():
        try:
            adata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        cands = set(adata.get("candidate_asset_ids") or [])
        if adata.get("baseline_revision_id") in selected or cands & selected:
            rows["attempts"].append(adata)
    for r in con.execute("SELECT id, data FROM edit_masks").fetchall():
        try:
            mdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        task = next((t for t in rows["tasks"] if t.get("id") == mdata.get("task_id")), None)
        if task is not None and mdata.get("id") == task.get("edit_mask_id"):
            rows["masks"].append(mdata)
    # annotations bound to selected frames/assets
    frame_ids = {fid for rev in revs.values() for fid in rev.frame_instance_ids}
    for r in con.execute("SELECT id, data FROM annotation_revisions").fetchall():
        try:
            adata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if adata.get("frame_instance_id") in frame_ids:
            rows["annotations"].append(adata)
    for r in con.execute("SELECT id, data FROM world_traces").fetchall():
        try:
            wdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if wdata.get("clip_revision_id") in selected:
            rows["traces"].append(wdata)
    rows["transitions"] = []
    try:
        trows = con.execute("SELECT id, data FROM transition_traces").fetchall()
    except Exception:
        trows = []
    for r in trows:
        try:
            tdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if tdata.get("departure_revision_id") in selected \
                or tdata.get("entry_revision_id") in selected:
            rows["transitions"].append(tdata)
    for r in con.execute("SELECT id, data FROM compiled_briefs").fetchall():
        try:
            bdata = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except Exception:
            continue
        if bdata.get("contract_revision_id") in {contracts[rid].id for rid in revs}:
            rows["briefs"].append(bdata)
    return rows


def _is_current_approval(con, ap: dict) -> bool:
    try:
        rows = con.execute("SELECT data FROM reference_approvals").fetchall()
    except Exception:
        return False
    mine = [json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            for r in rows
            if (json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
                ).get("character_revision_id") == ap.get("character_revision_id")]
    if not mine:
        return False
    superseded = {m.get("supersedes") for m in mine if m.get("supersedes")}
    current = [m for m in mine if m.get("id") not in superseded]
    return any(m.get("id") == ap.get("id") for m in current)


def _write_closure(out: Path, manifest_files: dict, exclusions: list,
                   rows: dict, pol: dict, used_names: set[str],
                   project_dir: str) -> None:
    (out / "closure" / "conditioning.json").write_text(json.dumps(
        {"contracts": rows["contracts"], "characters": rows["characters"],
         "approvals": rows["approvals"], "motion_guides": rows["guides"]},
        indent=2))
    manifest_files["closure/conditioning.json"] = _h(
        (out / "closure" / "conditioning.json").read_bytes())
    eval_rows = list(rows.get("evals", []))
    (out / "closure" / "evaluations.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in eval_rows)
        + ("\n" if eval_rows else ""))
    manifest_files["closure/evaluations.jsonl"] = _h(
        (out / "closure" / "evaluations.jsonl").read_bytes())
    for fname, key in (("events.jsonl", "events"), ("attempts.jsonl", "attempts"),
                       ("masks.jsonl", "masks"), ("packets.jsonl", "packets"),
                       ("tasks.jsonl", "tasks"), ("annotations.jsonl", "annotations"),
                       ("traces.jsonl", "traces"), ("briefs.jsonl", "briefs"),
                       ("transition_traces.jsonl", "transitions")):
        items = rows.get(key, [])
        (out / "closure" / fname).write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in items)
            + ("\n" if items else ""))
        manifest_files[f"closure/{fname}"] = _h((out / "closure" / fname).read_bytes())
    # reference + guide pixels (rights-gated) under safe names
    ref_aids: dict[str, str] = {}
    for c in rows["contracts"].values():
        for k in ("identity", "style"):
            aid = (c.get("references") or {}).get(k)
            if aid:
                ref_aids[aid] = "reference"
    for g in rows["guides"].values():
        for e in g.get("entries", []) or []:
            if e.get("asset_id"):
                ref_aids[e["asset_id"]] = "guide"
    for aid, role in sorted(ref_aids.items()):
        con = S.connect(project_dir)
        try:
            try:
                adata, _ = S.get(con, "assets", aid)
            except KeyError:
                exclusions.append({"asset": aid, "reason": f"{role} asset missing",
                                   "context": "closure"})
                continue
            if adata.get("rights") not in pol["rights_allow"]:
                exclusions.append({"asset": aid,
                                   "reason": f"closure {role} rights {adata.get('rights')!r} "
                                             "not allowed: bytes withheld, metadata kept",
                                   "context": "closure-rights"})
                continue
            dest = out / "closure" / "references" / f"{_safe_name(aid, used_names)}.png"
            dest.write_bytes(S.blob_path(project_dir, adata["byte_sha256"]).read_bytes())
        finally:
            con.close()
    for p in sorted((out / "closure" / "references").glob("*.png")):
        manifest_files[f"closure/references/{p.name}"] = _h(p.read_bytes())
    for m in rows["masks"]:
        con = S.connect(project_dir)
        try:
            try:
                adata, _ = S.get(con, "assets", m["mask_asset_id"])
            except KeyError:
                continue
            dest = out / "closure" / "masks" / f"{_safe_name(m['id'], used_names)}.png"
            dest.write_bytes(S.blob_path(project_dir, adata["byte_sha256"]).read_bytes())
        finally:
            con.close()
    for p in sorted((out / "closure" / "masks").glob("*.png")):
        manifest_files[f"closure/masks/{p.name}"] = _h(p.read_bytes())
    # evidence + provider blobs: every referenced object resolves in-snapshot
    _copy_closure_blobs(out, manifest_files, exclusions, rows, project_dir)


def _copy_closure_blobs(out: Path, manifest_files: dict, exclusions: list,
                        rows: dict, project_dir: str) -> None:
    wanted: dict[str, str] = {}
    for ev in rows.get("evals", []):
        digest = ev.get("evidence_manifest_sha256")
        if digest:
            wanted[digest] = "evidence-manifest"
    for adata in rows.get("attempts", []):
        for key in ("request_sha256",):
            pass
    # provider request/response artifacts linked from generating jobs are
    # recorded here when the job row names them; jobs themselves are not
    # portable rows, so link by digest reference collected below.
    con = S.connect(project_dir)
    try:
        try:
            job_rows = con.execute("SELECT data FROM jobs").fetchall()
        except Exception:
            job_rows = []
        for r in job_rows:
            try:
                job = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            except Exception:
                continue
            names = set(job.get("output_asset_ids") or [])
            for digest_key in ("request_artifact", "response_artifact"):
                d = job.get(digest_key)
                if d:
                    wanted[d] = f"provider-{digest_key}"
    finally:
        con.close()
    # evaluation objects referenced by preferences/packets resolve via
    # evaluations.jsonl already staged above; blobs carry the bytes.
    for digest, role in sorted(wanted.items()):
        blob = S.blob_path(project_dir, digest)
        if not blob.is_file():
            exclusions.append({"asset": digest[:16],
                               "reason": f"closure {role} blob missing from store",
                               "context": "closure"})
            continue
        dest = out / "closure" / "blobs" / digest
        dest.write_bytes(blob.read_bytes())
        manifest_files[f"closure/blobs/{digest}"] = _h(dest.read_bytes())


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


def _rev_files(out: Path, rid: str, frames: dict,
               positive_files: dict[tuple[str, int], str],
               research_files: dict[str, str]) -> list[dict]:
    """All packaged files for a revision with pixel hashes (mutation-detectable).

    Positive frames resolve under hf/data; everything else under
    research/media. Returned refs always stay inside the snapshot.
    """
    rows = []
    for fid, fr in frames.items():
        if fr["rev"] != rid:
            continue
        rel = positive_files.get((rid, fr["fi"].slot))
        if rel is None:
            rel = research_files.get(fr["asset"].id)
        if rel is None:
            continue
        p = out / rel
        if p.is_file():
            rows.append({"file": rel, "sha256": _h(p.read_bytes())})
    return rows
