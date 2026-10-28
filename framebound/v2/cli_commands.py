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
        return jobs.submit_generation(
            args.project, brief, refs, args.idempotency_key,
            offline=bool(getattr(args, "offline", False)),
            max_attempts=int(getattr(args, "max_attempts", 3))).model_dump()
    if cmd == "job-get":
        from .services import jobs
        return jobs.job_get(args.project, args.job_id)
    if cmd == "job-claim":
        from .services import jobs
        return jobs.job_claim(args.project, args.job_id,
                              getattr(args, "worker_id", "cli"),
                              expected_version=int(args.expected_version))
    if cmd == "job-cancel":
        from .services import jobs
        return jobs.job_cancel(args.project, args.job_id, int(args.expected_version))
    if cmd == "job-reconcile":
        from .services import jobs
        return jobs.job_reconcile(args.project)
    if cmd == "orchestrator-run":
        from .services import orchestrator as O
        return O.start_run(args.project, (args.jobs or "").split(",") if args.jobs else [],
                           max_attempts=int(getattr(args, "max_attempts", 3)))
    if cmd == "orchestrator-send":
        from .services import orchestrator as O
        brief = json.loads(open(args.brief).read())
        refs = brief.get("_reference_blobs", [])
        _ = refs  # bytes always re-resolve server-side; caller blobs never trusted
        return O.orchestrator_send(args.project, args.run_id, args.job_id, brief,
                                   worker_id=getattr(args, "worker_id", "cli"),
                                   offline=bool(getattr(args, "offline", False)))
    if cmd == "world-trace-record":
        from .services import clips as _CL
        import json as _json
        return _CL.record_world_trace(
            args.project, args.revision_id,
            _json.loads(args.positions), _json.loads(args.planted)).model_dump()
    if cmd == "capabilities":
        from .services import capabilities as C
        return C.table()
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
    if cmd == "corrections-list-open":
        from .services import corrections
        return corrections.list_tasks(args.project, ["open", "reopened"])
    if cmd == "correction-claim":
        from .services import corrections
        from .services.authz import Actor as _Actor
        return corrections.claim(args.project, _Actor(type="orchestrator",
                                id=getattr(args, "actor_id", "cli-worker")),
                                args.task_id, int(args.expected_version),
                                lease_minutes=int(getattr(args, "lease_minutes", 30)))
    if cmd == "correction-get":
        from .services import corrections
        return corrections.get_task(args.project, args.task_id)
    if cmd == "correction-submit":
        import json as _json
        from .services import corrections
        slot_assets = {int(k): v for k, v in
                       (kv.split("=") for kv in args.slots.split(","))} if args.slots else {}
        return corrections.submit_correction(
            args.project, __import__("framebound.v2.services.authz", fromlist=["Actor"]).Actor(
                type="orchestrator", id=getattr(args, "actor_id", "cli")),
            args.task_id, claim_token=args.claim_token,
            expected_version=int(getattr(args, "expected_version", 1)),
            new_revision_id=args.new_id, slot_asset_ids=slot_assets,
            recipe=args.recipe,
            transform=_json.loads(args.transform) if getattr(args, "transform", None) else None,
            baseline_evaluation_id=args.baseline_evaluation,
            idempotency_key=args.idempotency_key)
    if cmd == "mask-approve":
        from .services import masks as M
        from .services.authz import Actor as _Actor
        from .services import sessions as SN
        import os as _os
        token = getattr(args, "session_token", None) or _os.environ.get("FRAMEBOUND_REVIEWER_TOKEN", "")
        reviewer = SN.resolve_session(args.project, token)
        if reviewer is None:
            raise SystemExit("reviewer session required: set --session-token or FRAMEBOUND_REVIEWER_TOKEN")
        slots = [int(s) for s in args.slots.split(",")] if args.slots else []
        return json.loads(M.approve_mask(args.project, _Actor(type="reviewer", id=reviewer),
                                         args.issue, args.mask_asset, slots).model_dump_json())
    if cmd == "issue-reopen":
        from .services import corrections
        from .services.authz import Actor as _Actor
        from .services import sessions as SN
        import os as _os
        token = getattr(args, "session_token", None) or _os.environ.get("FRAMEBOUND_REVIEWER_TOKEN", "")
        reviewer = SN.resolve_session(args.project, token)
        if reviewer is None:
            raise SystemExit("reviewer session required: set --session-token or FRAMEBOUND_REVIEWER_TOKEN")
        return corrections.reopen_issue(args.project, _Actor(type="reviewer", id=reviewer),
                                        args.issue, getattr(args, "note", ""))
    if cmd == "eligibility":
        from .services import eligibility as E
        return E.release_eligibility(args.project, args.revision_id)
    if cmd == "reviewer-pair":
        from .services import sessions as SN
        import os as _os
        return SN.pair_reviewer(
            args.project, args.reviewer_id,
            operator_credential=getattr(args, "operator_secret", None)
            or _os.environ.get("FRAMEBOUND_OPERATOR_SECRET", ""))
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
