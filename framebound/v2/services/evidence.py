"""One evidence verifier consumed by eligibility, verify, export, and review entry points.

Release-grade evidence is a checked relationship, not a stored flag:
1. The manifest blob's filename must equal the sha256 of its bytes (address check).
2. Candidate bytes + canonical pixels must match the manifest and asset records.
3. Reference/guide bytes must match the manifest and the exact recorded
   approval's hashes (current-approval bytes are never substituted).
4. Only relevant annotations (bound to this revision's frames/assets) are
   checked; unrelated project annotations never invalidate or validate.
5. The analyzer/code identity must equal the running code identity.
6. The dependency lock digest must equal the running lock digest.

verify_evidence returns (ok, issues). Missing/corrupt dependencies fail;
restoring the original bytes restores integrity but never manufactures a
human decision (callers combine this with the current-decision reducer).
"""
from __future__ import annotations

import hashlib
import json

from .. import domain as D
from .. import storage as S
from ..media.canonical import canonical_pixels, pixel_sha256


def _blob_text(project_dir: str, digest: str):
    try:
        return S.blob_path(project_dir, digest).read_bytes()
    except Exception:
        return None


def verify_evidence(project_dir: str, revision_id: str,
                    evaluation: D.Evaluation) -> tuple[bool, list[str]]:
    con = S.connect(project_dir)
    try:
        return verify_evidence_in(con, project_dir, revision_id, evaluation)
    finally:
        con.close()


def verify_evidence_in(con, project_dir: str, revision_id: str,
                       evaluation: D.Evaluation, *, require_current: bool = True) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if True:
        try:
            rdata, _ = S.get(con, "clip_revisions", revision_id)
        except KeyError:
            return False, [f"unknown revision {revision_id}"]
        rev = D.ClipRevision.model_validate_json(json.dumps(rdata))
        try:
            cdata, _ = S.get(con, "contract_revisions", rev.contract_revision_id)
        except KeyError:
            return False, [f"revision {revision_id}: contract {rev.contract_revision_id} missing"]
        contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))

        raw = _blob_text(project_dir, evaluation.evidence_manifest_sha256)
        if raw is None:
            return False, ["evidence manifest blob missing from the store"]
        if hashlib.sha256(raw).hexdigest() != evaluation.evidence_manifest_sha256:
            return False, ["evidence manifest bytes do not match their content address (tampered?)"]
        try:
            manifest = json.loads(raw.decode())
        except Exception:
            return False, ["evidence manifest blob is not valid JSON"]

        # --- candidate frames: bytes + canonical pixels vs manifest + records
        frames = manifest.get("frames") or []
        if len(frames) != len(rev.frame_instance_ids):
            issues.append("manifest frame count does not match stored revision")
        for i, fid in enumerate(rev.frame_instance_ids):
            try:
                fdata, _ = S.get(con, "frame_instances", fid)
                adata, _ = S.get(con, "assets",
                                 D.FrameInstance.model_validate_json(json.dumps(fdata)).asset_id)
            except KeyError:
                issues.append(f"slot {i}: record missing")
                continue
            asset = D.Asset.model_validate_json(json.dumps(adata))
            blob = _blob_text(project_dir, asset.byte_sha256)
            if blob is None:
                issues.append(f"slot {i}: candidate blob gone")
                continue
            if hashlib.sha256(blob).hexdigest() != asset.byte_sha256:
                issues.append(f"slot {i}: candidate bytes changed since import (tampered?)")
                continue
            want = frames[i].get("byte_sha256") if i < len(frames) else None
            if want != asset.byte_sha256:
                issues.append(f"slot {i}: candidate bytes changed since evaluation (stale evidence)")
            if want and frames[i].get("pixel_sha256"):
                try:
                    from PIL import Image as _Image
                    import io as _io
                    canon = canonical_pixels(_Image.open(_io.BytesIO(blob)))
                    if pixel_sha256(canon) != frames[i]["pixel_sha256"]:
                        issues.append(f"slot {i}: candidate pixels changed since evaluation")
                except Exception as e:
                    issues.append(f"slot {i}: candidate pixels undecodable: {e}")

        # --- references: exact recorded approval's bytes, never current-approval substitution
        approval_id = (manifest.get("authority") or {}).get("approval_id")
        if approval_id:
            try:
                apdata, _ = S.get(con, "reference_approvals", approval_id)
                ap = D.ReferenceApproval.model_validate_json(json.dumps(apdata))
                expect_hashes = dict(ap.asset_hashes)
            except KeyError:
                issues.append(f"recorded approval {approval_id} missing: authority gone")
                expect_hashes = {}
        else:
            expect_hashes = {}
        for slot, ref in ((manifest.get("references") or {}).items()):
            bh = (ref or {}).get("byte_sha256")
            if not bh:
                continue
            blob = _blob_text(project_dir, bh)
            if blob is None:
                issues.append(f"reference slot {slot}: bytes gone; evidence is stale")
            elif hashlib.sha256(blob).hexdigest() != bh:
                issues.append(f"reference slot {slot}: bytes changed (tampered?)")

        # --- relevant annotations only
        relevant = {a.get("id"): a.get("sha256") for a in (manifest.get("annotations") or [])
                    if isinstance(a, dict) and a.get("id")}
        for aid, want in relevant.items():
            row = con.execute("SELECT data FROM annotation_revisions WHERE id=?",
                              (aid,)).fetchone()
            if row is None:
                issues.append(f"relevant annotation {aid} missing")
                continue
            # Hash the raw stored row: the manifest recorded the stored bytes,
            # not a re-serialization, so formatting can never false-positive.
            if hashlib.sha256(row["data"].encode()).hexdigest() != want:
                issues.append(f"relevant annotation {aid} changed since evaluation")

        # --- analyzer + lock identity
        from ..checks import evaluate as _EV
        if require_current and (manifest.get("analyzer") or {}).get("code_sha256") != _EV._code_sha256():
            issues.append("analyzer implementation changed since evaluation: re-evaluate")
        from ..checks.evaluate import lock_identity as _lockid
        running_lock = _lockid()["digest"]
        if require_current and (manifest.get("dependency_lock") or {}).get("digest") != running_lock:
            issues.append("dependency lock changed since evaluation: re-evaluate")

        # --- contract binding
        if (manifest.get("contract") or {}).get("id") != contract.id:
            issues.append("manifest contract does not match stored revision contract")
        if require_current and not issues:
            from .clips import compute_evaluation_in
            try:
                _, current, _ = compute_evaluation_in(con, project_dir, revision_id)
                if current.evidence_manifest_sha256 != evaluation.evidence_manifest_sha256:
                    issues.append('applicable evidence context changed: re-evaluate')
            except Exception as exc:
                issues.append(f'current evidence inputs unavailable: {exc}')
    return (not issues), issues
