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
        from .services import briefs as B
        return B.compile_reference_brief(args.project, args.contract_id, int(args.slot))
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
    if cmd == "reviewer-pair":
        from .services import sessions as SN
        return SN.pair_reviewer(args.project, args.reviewer_id)
    if cmd == "reviewer-open":
        from .services import sessions as SN
        from .services.errors import AuthorizationError, InvalidInput
        try:
            return SN.open_session(args.project, args.code)
        except (AuthorizationError, InvalidInput) as e:
            raise SystemExit(f"reviewer-open refused: {e}")
    if cmd == "guide-propose":
        import json as _json
        from .services import approvals as A
        from .services.authz import Actor as _Actor
        guide = _json.loads(open(args.guide).read())
        return A.propose_motion_guide(args.project, _Actor(type="orchestrator",
                                      id=getattr(args, "actor_id", "cli")),
                                      guide).model_dump()
    if cmd == "reference-approve":
        from .services import approvals as A
        from .services.authz import Actor as _Actor
        from .services import sessions as SN
        token = getattr(args, "session_token", None) or ""
        import os as _os
        token = token or _os.environ.get("FRAMEBOUND_REVIEWER_TOKEN", "")
        reviewer = SN.resolve_session(args.project, token)
        if reviewer is None:
            raise SystemExit("reviewer session required: set --session-token or "
                             "FRAMEBOUND_REVIEWER_TOKEN from `reviewer-open`")
        return A.approve_reference(args.project, _Actor(type="reviewer", id=reviewer),
                                   args.character, args.guide,
                                   getattr(args, "event_id", None)).model_dump()
    raise ValueError(f"unknown v2 command {cmd}")
