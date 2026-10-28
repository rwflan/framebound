"""DEPRECATED (Stage A corrected handoff): four-capability recorded workflow.

Retired from the active workflow and completion gates. Historical bundles remain
readable; new automatic work uses the deterministic offline check/repair path plus
explicit image/edit/segmentation providers through the durable controller.
The Spark critique capability is advisory-only and never a readiness gate.

Four-capability recorded workflow through the real durable controller (historical).

Unlike the procedural replay (demo_wp6), this path exercises the actual
provider stack bound to stored human approval: a Spark tool-loop critique,
reference-conditioned image generation, an actual image edit chained from
the generation response, and SAM segmentation — each through the real
controller/adapter path with its own request/response IDs, verified
artifacts, dependencies, status, and usage. Without credentials it records
a pending bundle naming the blocker — it never fabricates output, approval,
or a live loop. Human acceptance stays UNREVIEWED until a real reviewer acts.

Restart/idempotency: per-capability idempotency keys make a re-run with the
same key return the same bundle (no second spend). Post-provider import
failure preserves the paid response and retries without another provider
call. A skipped capability can never yield an overall pass.
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
            "compiled_brief_id": compiled["compiled_brief_id"],
            "reference_meta": refs}


def _inputs_digest(contract_id: str, slot: int, baseline_revision_id: str,
                   new_revision_id: str, idempotency_key: str) -> str:
    return hashlib.sha256(json.dumps({
        "contract_id": contract_id, "slot": slot,
        "baseline_revision_id": baseline_revision_id,
        "new_revision_id": new_revision_id,
        "idempotency_key": idempotency_key}, sort_keys=True).encode()).hexdigest()


def _write_bundle(out_path: Path, bundle: dict) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2) + "\n")
    return bundle


def _read_bundle(out_path: Path) -> dict | None:
    try:
        return json.loads(Path(out_path).read_text())
    except Exception:
        return None


def _check_baseline_contract(project_dir: str, contract_id: str,
                             baseline_revision_id: str) -> None:
    """The baseline must belong to the supplied contract; else the run's
    comparisons and conditioning would silently mix lineages."""
    from .services.errors import InvalidInput
    con = S.connect(project_dir)
    try:
        try:
            rdata, _ = S.get(con, "clip_revisions", baseline_revision_id)
        except KeyError:
            raise InvalidInput(f"unknown baseline revision {baseline_revision_id}")
        if rdata["contract_revision_id"] != contract_id:
            raise InvalidInput(
                f"baseline {baseline_revision_id} belongs to contract "
                f"{rdata['contract_revision_id']}, not {contract_id}: refusing a "
                "cross-contract recorded run")
    finally:
        con.close()


def _materialize_generated(project_dir: str, out_bytes: bytes, asset_id: str,
                           output_mime: str, w: int, h: int,
                           *, origin: str | None = None, parent_asset_id: str | None = None,
                           source_job_id: str | None = None) -> D.Asset:
    from .media.canonical import load_native_image,canonical_pixels,pixel_sha256
    image=load_native_image(out_bytes)
    if parent_asset_id:
        from .services.provenance import write_derived
        return write_derived(project_dir,asset_id,image,[parent_asset_id],
                             {'operator':'alias','source_job_id':source_job_id})
    con=S.connect(project_dir)
    try:
        rights='unknown'
        if source_job_id:
            job=S.get(con,'jobs',source_job_id)[0]
            grant=job.get('provider_settings',{}).get('grant_id')
            if grant:rights=S.get(con,'provider_grants',grant)[0].get('output_rights','unknown')
        asset=D.Asset(id=asset_id,byte_sha256=S.store_blob(project_dir,out_bytes),
            pixel_sha256=pixel_sha256(canonical_pixels(image)),mime='image/png',width=image.width,height=image.height,
            source_kind='generated',rights=rights,origin=origin or 'unknown',source_job_id=source_job_id,
            lineage=f'recorded-run:{origin}' if origin else '')
        with S.atomic(con):S.stage_identical(con,asset)
        return asset
    finally:con.close()


def _controller_send(project_dir: str, brief: dict, idem: str, *,
                     transport=None, timeout: float = 120.0,
                     provider_settings: dict | None = None,
                     offline: bool = False) -> dict:
    """One generation through the real durable controller (submit/claim/send).

    Already-succeeded jobs reuse their stored output without another dispatch;
    post-provider import failure retries from the paid response, never a new
    provider call.
    """
    from .services import jobs as J
    from .services import orchestrator as O
    from .providers import ledger as _ledger
    # Stage E: queued model/settings are immutable. Edit-chain settings are
    # frozen at submit time, never mutated after queueing.
    import os
    settings=dict(provider_settings or {})
    if os.environ.get('FRAMEBOUND_PROVIDER_GRANT'):
        settings.setdefault('grant_id',os.environ['FRAMEBOUND_PROVIDER_GRANT'])
    env = J.submit_generation(project_dir, brief, [], idem, offline=offline,
                              provider_settings=settings or None)
    job_id = env.artifacts[0]["id"]
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
    finally:
        con.close()
    if data["status"] == "succeeded" and data.get("output_asset_ids"):
        aid = data["output_asset_ids"][-1]
        try:
            con = S.connect(project_dir)
            try:
                adata, _ = S.get(con, "assets", aid)
            finally:
                con.close()
            raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
        except Exception:
            # Post-provider import failure recovery: the paid response bytes
            # live in the blob store under the response artifact's digest, so
            # a crashed import retries from those bytes without a new spend.
            from .providers import ledger as _ledger
            resp = _ledger.load_artifact(project_dir, data["response_artifact"])
            blob_digest = (resp.get("payload") or {}).get("output_blob")
            if not blob_digest:
                raise
            raw = S.blob_path(project_dir, blob_digest).read_bytes()
            asset = _materialize_generated(
                project_dir, raw, aid, "image/png", 0, 0,
                origin=data.get("origin"),source_job_id=data["id"])
            adata = {"byte_sha256": asset.byte_sha256,
                     "mime": asset.mime, "width": asset.width,
                     "height": asset.height}
        resp = {}
        if data.get("response_artifact"):
            from .providers import ledger as _ledger
            try:
                resp = _ledger.load_artifact(project_dir, data["response_artifact"])
            except Exception:
                resp = {}
        payload = resp.get("payload", {}) if isinstance(resp, dict) else {}
        return {"job_id": job_id, "reused": True,
                "output_bytes": raw, "output_asset_id": aid,
                "output_mime": adata.get("mime", "image/png"),
                "output_size": [adata.get("width"), adata.get("height")],
                "response_id": payload.get("response_id") or payload.get("request_id"),
                "response_artifact": data.get("response_artifact"),
                "request_artifact": data.get("request_artifact"),
                "usage": {}, "origin": data.get("origin", "unknown")}
    run = O.start_run(project_dir, [job_id])
    step = O.run_once(project_dir, run["run_id"], worker_id="recorded-run")
    if step["action"] != "send_ready":
        raise RuntimeError(f"controller refused the recorded job: {step}")
    out = O.orchestrator_send(project_dir, run["run_id"], job_id,
                              worker_id="recorded-run",
                              fencing_token=step["fencing_token"],
                              transport=transport, timeout=timeout)
    if out["action"] != "succeeded":
        raise RuntimeError(f"controller send did not succeed: {out}")
    con = S.connect(project_dir)
    try:
        data, _ = S.get(con, "jobs", job_id)
    finally:
        con.close()
    aid = data["output_asset_ids"][-1]
    con = S.connect(project_dir)
    try:
        adata, _ = S.get(con, "assets", aid)
    finally:
        con.close()
    raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
    return {"job_id": job_id, "reused": False,
            "output_bytes": raw, "output_asset_id": aid,
            "output_mime": adata.get("mime", "image/png"),
            "output_size": [adata.get("width"), adata.get("height")],
            "response_id": out.get("response_id"),
            "response_artifact": data.get("response_artifact"),
            "request_artifact": data.get("request_artifact"),
            "usage": data.get("cost_actual"), "origin": data.get("origin", "unknown"),
            "reserved": data.get("reserved_cost")}


def _capability_spark(project_dir: str, contract_summary: str, frame_blobs: list[dict],
                      idem: str, *, transport=None, timeout: float = 120.0) -> dict:
    """Capability 1: real bounded Spark tool loop with a terminal critique."""
    from .providers import spark as _spark
    try:
        res = _spark.submit_critique(
            contract_summary, [], frame_blobs, project_dir,
            transport=transport, timeout=timeout, max_turns=3,
            handlers={"get_deterministic_findings": lambda revision_id: {"note":
                      "recorded-run wiring: deterministic findings come from the "
                      "stored evaluation, not the model"},
                      "get_reference_metadata": lambda asset_id: {"asset_id": asset_id}})
    except Exception as e:
        return {"capability": "spark-critique", "status": "failed",
                "failure": f"{type(e).__name__}: {e}"}
    return {"capability": "spark-critique", "status": "recorded",
            "request_artifact": res.get("request_artifact"),
            "response_artifact": res.get("response_artifact"),
            "response_id": res.get("response_id"),
            "turns": res.get("turns"), "halted_on_turn_budget": res.get("halted_on_turn_budget"),
            "critique": res.get("critique"), "origin": res.get("origin")}


def _capability_sam(project_dir: str, image_bytes: bytes, prompt: str,
                    source_width: int, source_height: int, gen_asset: D.Asset,
                    contract_view: str, proposal_prefix: str, *,
                    transport=None, timeout: float = 120.0,
                    compiled_brief: dict | None = None, idempotency_key: str | None = None) -> dict:
    """Capability 4: real SAM segmentation; proposals materialized as stored
    rows carrying the exact source pixel hash (never a bare raster)."""
    from .providers import sam as _sam
    if compiled_brief is not None:
        from .services import jobs as J,orchestrator as O
        import os
        settings={'provider':'sam','source_asset_id':gen_asset.id,'prompt':prompt}
        if os.environ.get('FRAMEBOUND_PROVIDER_GRANT'):settings['grant_id']=os.environ['FRAMEBOUND_PROVIDER_GRANT']
        env=J.submit_generation(project_dir,compiled_brief,[],idempotency_key or f'{proposal_prefix}-sam',provider_settings=settings)
        jid=env.artifacts[0]['id'];job=J.job_get(project_dir,jid)['job']
        if job['status']=='queued':
            run=O.start_run(project_dir,[jid]);step=O.run_once(project_dir,run['run_id'],worker_id='recorded-sam')
            if step['action']=='send_ready':
                O.orchestrator_send(project_dir,run['run_id'],jid,worker_id='recorded-sam',
                    fencing_token=step['fencing_token'],transport=transport,timeout=timeout)
            job=J.job_get(project_dir,jid)['job']
        con=S.connect(project_dir)
        try:
            proposals=[]
            for aid,ann in zip(job['output_asset_ids'],job.get('output_annotation_ids',[])):
                asset=S.get(con,'assets',aid)[0]
                proposals.append({'asset_id':aid,'annotation_id':ann,'pixel_sha256':asset['pixel_sha256']})
        finally:con.close()
        return {'capability':'sam-segmentation','status':'recorded' if job['status']=='succeeded' and job.get('provider_outcome')=='mask' else 'failed',
                'job_id':jid,'outcome':job.get('provider_outcome'),'reason':job.get('error'),
                'request_artifact':job.get('request_artifact'),'response_artifact':job.get('response_artifact'),
                'response_id':job.get('provider_response_id'),'origin':job['origin'],
                'proposals':proposals,'record_count':len(proposals)}
    try:
        res = _sam.submit(base64.b64encode(image_bytes).decode(), prompt, project_dir,
                          transport=transport, timeout=timeout,
                          source_width=source_width, source_height=source_height)
    except Exception as e:
        return {"capability": "sam-segmentation", "status": "failed",
                "failure": f"{type(e).__name__}: {e}"}
    if res.get("mode") != "live":
        return {"capability": "sam-segmentation", "status": "blocked",
                "note": res.get("note", "SAM not configured")}
    if res.get('outcome') != 'mask':
        return {'capability':'sam-segmentation','status':'failed','outcome':res.get('outcome'),
                'reason':res.get('reason'),'request_artifact':res.get('request_artifact'),
                'response_artifact':res.get('response_artifact'),'origin':res.get('origin')}
    proposals: list[dict] = []
    for rec in res.get("records", []):
        raster = bytes(rec["mask"]["raster"])
        w, h = rec["mask"]["width"], rec["mask"]["height"]
        # Stage B: materialize through the shared media path. Mask rasters are
        # 0/1; encode as 0/255 grayscale so the approved-mask reader (>127)
        # observes foreground, and hash canonical RGBA pixels (not PNG bytes).
        from PIL import Image as _Image
        from .media.canonical import canonical_pixels, pixel_sha256 as _pxh
        img = _Image.new("L", (w, h))
        img.putdata([255 if v else 0 for v in raster])
        rgba = img.convert("RGBA")
        canon = canonical_pixels(rgba)
        import io as _io
        buf = _io.BytesIO()
        rgba.save(buf, format="PNG")
        raw = buf.getvalue()
        digest = S.store_blob(project_dir, raw)
        aid = f"{proposal_prefix}-sam-{rec['frame']}-{rec['object_id']}"
        asset = D.Asset(id=aid, byte_sha256=digest,
                        pixel_sha256=_pxh(canon), mime="image/png", width=w, height=h,
                        source_kind="derived", lineage=f"sam:{res.get('response_id')}",
                        rights=gen_asset.rights, eligible_roles=[],parent_asset_ids=[gen_asset.id],
                        origin=res.get('origin','unknown'),derivation={'operator':'segmentation'})
        con = S.connect(project_dir)
        try:
            try:
                S.insert(con, asset)
            except S.ConflictError:
                pass
            ann = D.AnnotationRevision(
                id=f"{aid}-ann", source_asset_id=gen_asset.id,
                source_pixel_sha256=gen_asset.pixel_sha256 or gen_asset.byte_sha256,
                view=contract_view, frame_instance_id=None,
                mask_asset_id=aid, annotator_type="model_proposed",
                role="support")
            try:
                S.insert(con, ann)
            except S.ConflictError:
                pass
        finally:
            con.close()
        proposals.append({"asset_id": aid, "annotation_id": ann.id,
                          "frame": rec["frame"], "object_id": rec["object_id"],
                          "box": rec["box"],
                          "foreground": rec["mask"]["foreground"]})
    return {"capability": "sam-segmentation", "status": "recorded",
            "request_artifact": res.get("request_artifact"),
            "response_artifact": res.get("response_artifact"),
            "response_id": res.get("response_id"), "outcome": res.get("outcome"),
            "reason": res.get("reason"), "record_count": len(res.get("records", [])),
            "proposals": proposals, "origin": res.get("origin")}


def run_recorded(project_dir: str, out_path: str, *, contract_id: str, slot: int,
                 baseline_revision_id: str, new_revision_id: str,
                 offline: bool = True, transport=None,
                 idempotency_key: str = "recorded-run-1",
                 spark_transport=None, sam_transport=None,
                 timeout: float = 120.0, include_spark: bool = False) -> dict:
    """Execute the recorded provider workflow through the controller (DEPRECATED).

    Capabilities: Spark tool-loop critique, reference-conditioned generation,
    an actual chained image edit, and SAM segmentation — each with its own
    request/response IDs, verified artifacts, dependencies, status, and usage.
    Idempotent: retrying with the same key and inputs returns the stored
    bundle without another dispatch. A skipped/failed capability can never
    yield an overall recorded pass.
    """
    from .services import clips, packets
    from .services.authz import Actor as _Actor  # noqa: F401 (documents the caller boundary)
    from .services.errors import InvalidInput
    digest = _inputs_digest(contract_id, slot, baseline_revision_id,
                            new_revision_id, idempotency_key)
    prior = _read_bundle(Path(out_path))
    if prior and prior.get("inputs_digest") == digest and prior.get("status") in (
            "recorded", "recorded-failure", "blocked"):
        return prior
    if Path(out_path).exists():
        raise S.ConflictError(
            f"refusing to overwrite {out_path} with different inputs: recorded "
            "bundles are non-destructive (use a new idempotency key)")
    prepared = prepare(project_dir, contract_id, slot)
    try:
        _check_baseline_contract(project_dir, contract_id, baseline_revision_id)
    except InvalidInput as e:
        return _write_bundle(Path(out_path), {
            "origin": "blocked", "status": "recorded-failure",
            "failure": str(e), "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "inputs_digest": digest, "idempotency_key": idempotency_key})
    from .providers import base as _base
    live_key = bool(_base._key())
    capabilities: list[dict] = []
    if offline or (transport is None and spark_transport is None
                   and sam_transport is None and not live_key):
        return _write_bundle(Path(out_path), {
            "origin": "blocked", "status": "blocked",
            "blocker": "no live provider call: offline mode or MODEL_API_KEY absent; "
                       "configure an authorized participant credential for the live spike",
            "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "capabilities": [],
            "inputs_digest": digest, "idempotency_key": idempotency_key,
            "note": "procedural replay stays in demo_wp6; this bundle claims no output"})
    origin = "provider-simulated" if any(t is not None for t in
                                         (transport, spark_transport, sam_transport)) else "live"
    con = S.connect(project_dir)
    try:
        cdata, _ = S.get(con, "contract_revisions", contract_id)
        rdata, _ = S.get(con, "clip_revisions", baseline_revision_id)
        fdata, _ = S.get(con, "frame_instances", rdata["frame_instance_ids"][slot])
        adata, _ = S.get(con, "assets", fdata["asset_id"])
        base_raw = S.blob_path(project_dir, adata["byte_sha256"]).read_bytes()
        canvas = (cdata["canvas"]["width"], cdata["canvas"]["height"])
        view = cdata["action"]["view"]
    finally:
        con.close()
    contract_summary = f"{contract_id} slot {slot} ({canvas[0]}x{canvas[1]} {view})"
    frame_blobs = [{"slot": slot, "asset_id": fdata["asset_id"], "mime": "image/png",
                    "bytes_b64": base64.b64encode(base_raw).decode()}]
    # Capability 1 (DEPRECATED advisory-only): Spark critique loop.
    # Never gates the bundle verdict; recorded only when explicitly requested.
    if include_spark or spark_transport is not None:
        import warnings as _warnings
        _warnings.warn("recorded-run spark capability is retired; advisory only", DeprecationWarning, stacklevel=2)
        capabilities.append(_capability_spark(
            project_dir, contract_summary, frame_blobs, f"{idempotency_key}-spark",
            transport=spark_transport if spark_transport is not None else transport,
            timeout=timeout))
    else:
        capabilities.append({"capability": "spark-critique", "status": "skipped-retired",
                             "note": "retired from active workflow; advisory only, never a gate"})
    # Capability 2: reference-conditioned generation through the controller.
    try:
        gen = _controller_send(project_dir, prepared["brief"], f"{idempotency_key}-gen",
                               transport=transport, timeout=timeout)
    except Exception as e:
        capabilities.append({"capability": "image-generation", "status": "failed",
                             "failure": f"{type(e).__name__}: {e}"})
        return _write_bundle(Path(out_path), {
            "origin": origin, "status": "recorded-failure",
            "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "capabilities": capabilities,
            "inputs_digest": digest, "idempotency_key": idempotency_key,
            "note": "generation failed; recorded, not retried, not cherry-picked"})
    gen_asset = _materialize_generated(
        project_dir, gen["output_bytes"], f"{new_revision_id}-gen",
        gen["output_mime"], gen["output_size"][0], gen["output_size"][1],
        origin=gen.get("origin", origin),parent_asset_id=gen["output_asset_id"],source_job_id=gen["job_id"])
    if (gen_asset.width, gen_asset.height) != canvas:
        return _write_bundle(Path(out_path), {
            "origin": origin, "status": "recorded-failure",
            "failure": f"generated {(gen_asset.width, gen_asset.height)} != frozen "
                       f"canvas {canvas}: undeclared fitting refused",
            "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "capabilities": capabilities + [{"capability": "image-generation",
                                             "status": "failed",
                                             "failure": "canvas mismatch"}],
            "inputs_digest": digest, "idempotency_key": idempotency_key})
    capabilities.append({"capability": "image-generation", "status": "recorded",
                         "job_id": gen["job_id"], "reused": gen["reused"],
                         "request_artifact": gen["request_artifact"],
                         "response_artifact": gen["response_artifact"],
                         "response_id": gen["response_id"],
                         "output_asset_id": gen_asset.id, "usage": gen["usage"],
                         "origin": gen["origin"]})
    # Capability 3: an actual edit chained from the generation response.
    try:
        edit = _controller_send(
            project_dir, prepared["brief"], f"{idempotency_key}-edit",
            transport=transport, timeout=timeout,
            provider_settings={"previous_response_id": gen["response_id"],
                               "edit_instruction": "bounded patch: keep canvas, "
                               "calibration and protected regions; adjust the "
                               "faulted phase within the approved scope"})
        edit_asset = _materialize_generated(
            project_dir, edit["output_bytes"], f"{new_revision_id}-edit",
            edit["output_mime"], edit["output_size"][0], edit["output_size"][1],
            origin=edit.get("origin", origin),parent_asset_id=edit["output_asset_id"],source_job_id=edit["job_id"])
        if (edit_asset.width, edit_asset.height) != canvas:
            raise RuntimeError(f"edit {(edit_asset.width, edit_asset.height)} != canvas")
        capabilities.append({"capability": "image-edit", "status": "recorded",
                             "job_id": edit["job_id"], "reused": edit["reused"],
                             "request_artifact": edit["request_artifact"],
                             "response_artifact": edit["response_artifact"],
                             "response_id": edit["response_id"],
                             "previous_response_id": gen["response_id"],
                             "output_asset_id": edit_asset.id,
                             "usage": edit["usage"], "origin": edit["origin"]})
        edit_bytes, edit_dim = edit["output_bytes"], edit["output_size"]
    except Exception as e:
        capabilities.append({"capability": "image-edit", "status": "failed",
                             "failure": f"{type(e).__name__}: {e}"})
        edit_asset, edit_bytes = None, None
    # Register + evaluate the generated revision (edit is auxiliary evidence).
    try:
        env = clips.register_candidate(project_dir, baseline_revision_id, new_revision_id,
                                       {slot: gen_asset.id}, f"recorded-run:{origin}")
        ev = clips.evaluate(project_dir, new_revision_id)
        pkt = packets.create_packet(project_dir, f"pkt-{new_revision_id}", new_revision_id,
                                    ev.artifacts[0]["id"],
                                    f"recorded {origin} run for {contract_id} slot {slot}",
                                    comparison_revision_id=baseline_revision_id)
        reg = {"revision_id": new_revision_id, "evaluation_id": ev.artifacts[0]["id"],
               "technical_status": ev.technical_status.value,
               "packet_id": pkt.artifacts[0]["id"], "status": "recorded"}
    except Exception as e:
        return _write_bundle(Path(out_path), {
            "origin": origin, "status": "recorded-failure",
            "failure": f"post-provider import/registration failed (paid response "
                       f"preserved, retry without a new call): {type(e).__name__}: {e}",
            "contract_id": contract_id, "slot": slot,
            "baseline_revision_id": baseline_revision_id,
            "prepared": prepared, "acceptance": "unreviewed",
            "capabilities": capabilities,
            "generation": {"output_asset_id": gen_asset.id,
                           "request_artifact": gen["request_artifact"],
                           "response_artifact": gen["response_artifact"]},
            "inputs_digest": digest, "idempotency_key": idempotency_key,
            "note": "truthful partial bundle: spend happened, import did not"})
    # Capability 4: SAM segmentation of the generated pixels.
    sam_cap = _capability_sam(project_dir, gen["output_bytes"], "figure",
                              canvas[0], canvas[1], gen_asset, view,
                              f"{new_revision_id}-prop",
                              transport=sam_transport if sam_transport is not None
                              else transport, timeout=timeout,compiled_brief=prepared['brief'],
                              idempotency_key=f'{idempotency_key}-sam')
    capabilities.append(sam_cap)
    # Stage A corrected handoff: spark-critique is advisory-only and never gates.
    failed = [c for c in capabilities if c.get("capability") != "spark-critique" and c.get("status") != "recorded"]
    status = "recorded" if not failed and ev.technical_status == D.TechnicalStatus.PASS \
        else "recorded-failure"
    bundle = {
        "origin": origin,
        "status": status,
        "contract_id": contract_id, "slot": slot,
        "baseline_revision_id": baseline_revision_id,
        "reference_inputs": prepared["reference_meta"],
        "conditioning_sha256": prepared["conditioning_sha256"],
        "approval_id": prepared["approval_id"],
        "generation": {"output_asset_id": gen_asset.id,
                       "output_byte_sha256": gen_asset.byte_sha256,
                       "output_size": [gen_asset.width, gen_asset.height],
                       "request_artifact": gen["request_artifact"],
                       "response_artifact": gen["response_artifact"],
                       "response_id": gen["response_id"]},
        "edit": ({"output_asset_id": edit_asset.id,
                  "request_artifact": edit["request_artifact"],
                  "response_artifact": edit["response_artifact"],
                  "response_id": edit["response_id"]} if edit_asset else None),
        "registration": reg,
        "capabilities": capabilities,
        "acceptance": "unreviewed",
        "inputs_digest": digest, "idempotency_key": idempotency_key,
        "note": "human acceptance requires an actual authorized reviewer decision; "
                "simulated origins are ineligible for real positives"}
    out = _write_bundle(Path(out_path), bundle)
    try:
        Path(str(out_path) + ".output.png").write_bytes(gen["output_bytes"])
        if edit_bytes:
            Path(str(out_path) + ".edit.png").write_bytes(edit_bytes)
    except Exception:
        pass
    return out
