"""One original generated-character workflow with approved references.

Unlike the procedural replay (demo_wp6), this path produces a real provider
result bound to stored human approval: reference inputs, request/response
artifacts, output bytes, a registered/evaluated revision, a review packet and
honest status. Without credentials it records a pending artifact that names
the blocker and the prepared inputs — it never fabricates output, approval,
or a live loop. Human acceptance stays UNREVIEWED until a real reviewer acts.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from . import domain as D
from . import storage as S


def prepare(project_dir: str, contract_id: str, slot: int) -> dict:
    """Compile the generation brief against stored human approval.

    Fails without a current human reference approval — same gate as every
    other transport. Returns the brief plus reference metadata (no pixels
    inline; pixels resolve server-side at send time).
    """
    from .services import briefs as B
    compiled = B.compile_reference_brief(project_dir, contract_id, slot)
    brief = compiled["brief"]
    refs = [{"asset_id": i.get("asset_id"), "byte_sha256": i.get("byte_sha256"),
             "role": i.get("role")}
            for i in brief.get("inputs", []) if i.get("asset_id")]
    return {"brief": brief, "conditioning_sha256": compiled["conditioning_sha256"],
            "approval_id": compiled["approval_id"],
            "motion_guide_id": compiled["motion_guide_id"],
            "reference_meta": refs}


def _write_bundle(out_path: Path, bundle: dict) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2) + "\n")
    return bundle


def run_recorded(project_dir: str, out_path: str, *, contract_id: str, slot: int,
                 baseline_revision_id: str, new_revision_id: str,
                 offline: bool = True, transport=None,
                 idempotency_key: str = "recorded-run-1") -> dict:
    """Execute one recorded generation: live, simulated, or blocked-pending.

    - offline=True (or no key): writes a pending bundle naming the blocker.
    - transport given (tests): full bundle labeled origin=provider-simulated.
    - real key + transport None: one live call, origin=live.
    The generated asset becomes a registered/evaluated revision with a
    comparison packet; failures are recorded, not retried blindly.
    """
    from .providers import image as img
    from .services import clips, jobs, packets
    from .services.authz import Actor as _Actor  # noqa: F401 (documents the caller boundary)
    prepared = prepare(project_dir, contract_id, slot)
    from .providers import base as _base
    if offline or (transport is None and not _base._key()):
        return _write_bundle(Path(out_path), {
            "origin": "blocked", "status": "blocked",
            "blocker": "no live provider call: offline mode or MODEL_API_KEY absent; "
                       "configure an authorized participant credential for the live spike",
            "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "note": "procedural replay stays in demo_wp6; this bundle claims no output"})
    resolved = jobs._resolve_references(project_dir, prepared["brief"], [])
    origin = "provider-simulated" if transport is not None else "live"
    try:
        res = img.submit(prepared["brief"], resolved, project_dir, idempotency_key,
                         offline=False, transport=transport)
    except Exception as e:
        return _write_bundle(Path(out_path), {
            "origin": origin, "status": "recorded-failure",
            "failure": f"{type(e).__name__}: {e}",
            "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "note": "provider call failed; recorded, not retried, not cherry-picked"})
    out_bytes = res["output_bytes"]
    raw_digest = S.store_blob(project_dir, out_bytes)
    from .media.canonical import canonical_pixels, pixel_sha256
    from PIL import Image as _Image
    import io as _io
    im = _Image.open(_io.BytesIO(out_bytes))
    im.load()
    w, h = im.size
    aid = f"{new_revision_id}-gen"
    asset = D.Asset(id=aid, byte_sha256=raw_digest,
                    pixel_sha256=pixel_sha256(canonical_pixels(im.convert("RGBA"))),
                    mime=res.get("output_mime", "image/png"), width=w, height=h,
                    source_kind="generated", rights="original", eligible_roles=[])
    con = S.connect(project_dir)
    try:
        S.insert(con, asset)
    except S.ConflictError:
        pass
    finally:
        con.close()
    env = clips.register_candidate(project_dir, baseline_revision_id, new_revision_id,
                                   {slot: aid}, f"recorded-run:{origin}")
    ev = clips.evaluate(project_dir, new_revision_id)
    pkt = packets.create_packet(project_dir, f"pkt-{new_revision_id}", new_revision_id,
                                ev.artifacts[0]["id"],
                                f"recorded {origin} run for {contract_id} slot {slot}",
                                comparison_revision_id=baseline_revision_id)
    bundle = {
        "origin": origin,
        "status": "recorded" if ev.technical_status == D.TechnicalStatus.PASS else "recorded-failure",
        "contract_id": contract_id, "slot": slot,
        "baseline_revision_id": baseline_revision_id,
        "reference_inputs": prepared["reference_meta"],
        "conditioning_sha256": prepared["conditioning_sha256"],
        "approval_id": prepared["approval_id"],
        "request_artifact": res.get("request_artifact"),
        "response_artifact": res.get("response_artifact"),
        "response_id": res.get("response_id"),
        "output_asset_id": aid,
        "output_byte_sha256": raw_digest,
        "output_size": res.get("output_size"),
        "revision_id": new_revision_id,
        "evaluation_id": ev.artifacts[0]["id"],
        "technical_status": ev.technical_status.value,
        "packet_id": pkt.artifacts[0]["id"],
        "acceptance": "unreviewed",
        "note": "human acceptance requires an actual authorized reviewer decision"}
    out = _write_bundle(Path(out_path), bundle)
    Path(str(out_path) + ".output.png").write_bytes(out_bytes)
    return out
