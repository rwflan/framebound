"""Thin CLI dispatch over application services (no policy reimplemented here)."""
from __future__ import annotations

import json


def dispatch(args) -> dict:
    cmd = args.cmd
    if cmd=='animation-quality-benchmark':
        from ..v3.benchmark import run
        return run(args.manifest)
    if cmd in {'agent-export-preview','agent-export-build'}:
        from pathlib import Path
        from ..v3.services import exports
        selection=json.loads(Path(args.selection).read_text())
        return exports.plan(args.project,selection) if cmd=='agent-export-preview' else exports.build(args.project,selection)
    if cmd == 'agent-satisfaction-record':
        from pathlib import Path
        from ..v3.services import interventions as I
        from .services.authz import Actor
        return I.agent_satisfied(args.project,Actor(type='orchestrator',id='cli-parent-agent'),args.run_id,**json.loads(Path(args.action).read_text()))
    if cmd in {'agent-handoff-get','agent-intervention-get','agent-intervention-mark','agent-intervention-resolve','agent-intervention-reopen','agent-decision'}:
        import os
        from pathlib import Path
        from ..v3.services import interventions as I
        from .services import sessions
        from .services.authz import Actor
        from .services.errors import AuthorizationError
        if cmd == 'agent-handoff-get':
            return I.handoff(args.project,args.feedback_id)
        if cmd == 'agent-intervention-get':
            return I.get(args.project,args.intervention_id)
        token=args.session_token or os.environ.get('FRAMEBOUND_REVIEWER_TOKEN','')
        reviewer=sessions.resolve_session(args.project,token)
        if reviewer is None:
            raise AuthorizationError('reviewer session required; provide --session-token or FRAMEBOUND_REVIEWER_TOKEN')
        actor=Actor(type='reviewer',id=reviewer)
        payload=json.loads(Path(args.action).read_text())
        if cmd == 'agent-intervention-mark':return I.mark(args.project,actor,args.run_id,payload)
        if cmd == 'agent-decision':return I.decision(args.project,actor,args.run_id,payload)
        return I.resolve(args.project,actor,args.intervention_id,payload,reopen=cmd=='agent-intervention-reopen')
    if cmd == 'agent-revision-get':
        from ..v3.services import loop
        return loop.revision_get(args.project, args.revision_id)
    if cmd.startswith('agent-run-'):
        from ..v3.services import loop
        from pathlib import Path
        if cmd == 'agent-run-eligibility':
            return loop.eligibility(args.project, args.run_id)
        if cmd == 'agent-run-cancel':
            return loop.cancel(args.project, args.run_id, args.reason)
        if cmd == 'agent-run-start':
            return loop.start(args.project, args.task_id, args.run_id)
        if cmd == 'agent-run-get':
            return loop.get(args.project, args.run_id)
        if cmd == 'agent-run-submit':
            return loop.submit(args.project, **json.loads(Path(args.submission).read_text()))
    if cmd.startswith('task-'):
        from ..v3.services import tasks
        if cmd == 'task-create':
            from pathlib import Path
            return tasks.create(args.project, json.loads(Path(args.spec).read_text()))
        if cmd == 'task-get':
            return tasks.get(args.project, args.task_id)
        if cmd == 'task-compile-inputs':
            return tasks.compile_inputs(args.project, args.task_id)
        if cmd == 'task-migration-report':
            return tasks.migration_report(args.project)
    if cmd == 'provider-grant':
        import os
        from .services import provider_grants
        return provider_grants.issue(args.project,json.loads(open(args.grant).read()),
            args.operator_secret or os.environ.get('FRAMEBOUND_OPERATOR_SECRET',''))
    if cmd == 'project-create':
        from .services import projects
        return projects.create_project(args.project, {'id': args.project_id,
                    'name': args.name or args.project_id}).model_dump()
    if cmd == 'character-propose':
        from .services import characters
        return characters.propose_character(args.project, json.loads(open(args.character).read())).model_dump()
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
            provider_settings=json.loads(getattr(args,'provider_settings','{}')),
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
        # No caller brief needed: the frozen job row owns the request. A
        # supplied file must fingerprint-match the submission exactly.
        brief = None
        if getattr(args, "brief", None):
            brief = json.loads(open(args.brief).read())
        return O.orchestrator_send(args.project, args.run_id, args.job_id, brief,
                                   worker_id=getattr(args, "worker_id", "cli"),
                                   fencing_token=getattr(args, "fencing_token", None),
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
                             "FRAMEBOUND_REVIEWER_TOKEN")
        return A.approve_reference(args.project, _Actor(type="reviewer", id=reviewer),
                                   args.character, args.guide,
                                   getattr(args, "event_id", None)).model_dump()
    if cmd=='provider-reconcile':
        from .services.provider_recovery import reconcile
        import os
        return reconcile(args.project,args.job_id,json.loads(open(args.receipt).read()),args.operator_secret or os.environ.get('FRAMEBOUND_OPERATOR_SECRET',''))
    if cmd=='provider-grant-get':
        from .services.provider_grants import get_grant
        return get_grant(args.project,args.grant_id)
    if cmd=='provider-grant-revoke':
        from .services.provider_grants import revoke
        import os
        return revoke(args.project,args.grant_id,int(args.expected_version),args.operator_secret or os.environ.get('FRAMEBOUND_OPERATOR_SECRET',''))
    if cmd.startswith('animation-'):
        from .services import auto_repair as A
        if cmd=='animation-compile':return A.compile_plan(args.project,args.contract_id)
        if cmd=='animation-run':return A.run_automatic(args.project,args.revision_id,args.idempotency_key,provider_settings=json.loads(args.provider_settings),offline=not args.live)
        if cmd=='animation-start':return A.start_run(args.project,args.revision_id,args.idempotency_key,provider_settings=json.loads(args.provider_settings),offline=not args.live)
        if cmd=='animation-step':return A.step_run(args.project,args.run_id)
        if cmd=='animation-get':return A.get_run(args.project,args.run_id)
    if cmd=='source-calibrate':
        from .services.animation_context import calibrate_source
        return calibrate_source(args.project,args.contract_id,args.source_asset_id,args.output_asset_id).model_dump()
    raise ValueError(f"unknown v2 command {cmd}")
