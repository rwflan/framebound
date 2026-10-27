"""Thin CLI dispatch over application services (no policy reimplemented here)."""
from __future__ import annotations

import json


def dispatch(args) -> dict:
    cmd = args.cmd
    if cmd == "asset-import":
        from .services import assets
        return assets.import_asset(args.project, args.src, args.asset_id).model_dump()
    if cmd == "contract-propose":
        from .services import contracts
        return contracts.propose_contract(args.project, json.loads(open(args.contract).read())).model_dump()
    if cmd == "clip-create":
        from .services import clips
        return clips.create_revision(args.project, args.contract_id, args.revision_id,
                                     args.frames.split(","), args.phases.split(",")).model_dump()
    if cmd == "clip-evaluate":
        from .services import clips
        return clips.evaluate(args.project, args.revision_id).model_dump()
    if cmd == "brief-compile":
        import sqlite3  # noqa: F401 (kept for future direct reads)
        from . import domain as D
        from . import storage as S
        from .briefs import compile_brief
        con = S.connect(args.project)
        try:
            cdata, _ = S.get(con, "contract_revisions", args.contract_id)
            contract = D.ClipContractRevision.model_validate_json(json.dumps(cdata))
            assets, approvals = {}, {}
            for role in ("identity", "style"):
                aid = contract.references[role]
                adata, _ = S.get(con, "assets", aid)
                assets[aid] = D.Asset.model_validate_json(json.dumps(adata))
                approvals[aid] = {"approved": True, "event_id": "imported"}
            b = compile_brief(contract, int(args.slot), assets, approvals,
                              {e.motion_reference_id: f"guide:{e.motion_reference_id}"
                               for e in contract.phase_schedule})
        finally:
            con.close()
        return {"conditioning_sha256": b.conditioning_sha256, "brief": b.bundle}
    if cmd == "job-submit":
        from .services import jobs
        brief = json.loads(open(args.brief).read())
        refs = brief.get("_reference_blobs", [])
        return jobs.submit_generation(args.project, brief, refs, args.idempotency_key).model_dump()
    if cmd == "job-get":
        from .services import jobs
        return jobs.job_get(args.project, args.job_id)
    if cmd == "candidate-register":
        from .services import clips
        slot_assets = {int(k): v for k, v in
                       (kv.split("=") for kv in args.slots.split(","))} if args.slots else {}
        return clips.register_candidate(args.project, args.baseline, args.new_id,
                                        slot_assets, args.recipe).model_dump()
    if cmd == "packet-create":
        from .services import packets
        return packets.create_packet(args.project, args.packet_id, args.revision_id,
                                     args.evaluation_id, args.intent or "review").model_dump()
    if cmd == "corrections-list":
        from .services import corrections
        return corrections.list_open(args.project)
    raise ValueError(f"unknown v2 command {cmd}")
