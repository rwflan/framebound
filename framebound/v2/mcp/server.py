"""MCP stdio server over the v2 application services (pinned SDK mcp==2.3.0)."""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

def build_server(project_dir: str) -> MCPServer:
    server = MCPServer(name="framebound-v2", version="2.0.0a1")

    @server.tool(name='task_create', description='Register an immutable v3 task without a motion guide or reviewer approval')
    def task_create(spec: dict) -> dict:
        from ...v3.services import tasks
        return tasks.create(project_dir, spec)

    @server.tool(name='task_get', description='Fetch a frozen task and negotiated capability gaps')
    def task_get(task_id: str) -> dict:
        from ...v3.services import tasks
        return tasks.get(project_dir, task_id)

    @server.tool(name='task_compile_inputs', description='Compile intent and optional inputs for external generation; does not authorize provider spending')
    def task_compile_inputs(task_id: str) -> dict:
        from ...v3.services import tasks
        return tasks.compile_inputs(project_dir, task_id)

    @server.tool(name='animation_compile', description='Compile frozen human-approved controls and bounded repair policy')
    def animation_compile(contract_id: str) -> dict:
        from ..services.auto_repair import compile_plan
        return compile_plan(project_dir,contract_id)

    @server.tool(name='animation_start', description='Start resumable automatic native animation work')
    def animation_start(revision_id: str, idempotency_key: str | None = None, provider_settings: dict | None = None, offline: bool = True) -> dict:
        from ..services.auto_repair import start_run
        return start_run(project_dir,revision_id,idempotency_key,provider_settings=provider_settings,offline=offline)

    @server.tool(name='animation_step', description='Execute one bounded repair step with persisted attempts')
    def animation_step(run_id: str) -> dict:
        from ..services.auto_repair import step_run
        return step_run(project_dir,run_id)

    @server.tool(name='animation_get', description='Read automatic work and its measured internal progress')
    def animation_get(run_id: str) -> dict:
        from ..services.auto_repair import get_run
        return get_run(project_dir,run_id)

    @server.tool(name='source_calibrate', description='Materialize the approved fixed family calibration')
    def source_calibrate(contract_id: str, source_asset_id: str, output_asset_id: str) -> dict:
        from ..services.animation_context import calibrate_source
        return calibrate_source(project_dir,contract_id,source_asset_id,output_asset_id).model_dump()

    @server.tool(name='project_create', description='Create or resume a project with identical inputs')
    def project_create(project_id: str, name: str = '') -> dict:
        from ..services import projects
        return projects.create_project(project_dir, {'id':project_id, 'name':name or project_id}).model_dump()

    @server.tool(name='character_propose', description='Propose stored character identity/style and native calibration')
    def character_propose(character: dict) -> dict:
        from ..services import characters
        return characters.propose_character(project_dir, character).model_dump()

    @server.tool(name='guide_propose', description='Propose independent phase guides; does not approve them')
    def guide_propose(guide: dict) -> dict:
        from ..services import approvals
        from ..services.authz import Actor
        return approvals.propose_motion_guide(project_dir, Actor(type='orchestrator',id='mcp'), guide).model_dump()

    @server.tool(name="doctor", description="Offline runtime and dependency check")
    def doctor() -> dict:
        from ..doctor import run_doctor
        return run_doctor()

    @server.tool(name="project_get", description="Project metadata, IDs, capabilities, state summary")
    def project_get() -> dict:
        from ..services import projects
        return {"project_dir": project_dir, "summary": projects.get_summary(project_dir)}

    @server.tool(name="asset_import", description="Import an authorized image asset by path")
    def asset_import(src: str, asset_id: str, source_kind: str = "original",
                     rights: str = "original") -> dict:
        from ..services import assets
        return assets.import_asset(project_dir, src, asset_id, source_kind, rights).model_dump()

    @server.tool(name="contract_propose", description="Validate + store a clip contract revision")
    def contract_propose(contract: dict) -> dict:
        from ..services import contracts
        return contracts.propose_contract(project_dir, contract).model_dump()

    @server.tool(name="clip_create_revision", description="Create a clip revision from stored frame assets")
    def clip_create_revision(contract_id: str, revision_id: str, frame_asset_ids: list[str],
                             phase_names: list[str]) -> dict:
        from ..services import clips
        return clips.create_revision(project_dir, contract_id, revision_id,
                                     frame_asset_ids, phase_names).model_dump()

    @server.tool(name="clip_evaluate", description="Evaluate a stored clip revision; returns envelope with coverage")
    def clip_evaluate(revision_id: str) -> dict:
        from ..services import clips
        return clips.evaluate(project_dir, revision_id).model_dump()

    @server.tool(name="brief_compile", description="Compile a typed conditioning bundle for one slot "
                        "(requires a stored human reference approval; fails without one)")
    def brief_compile(contract_id: str, slot: int) -> dict:
        from ..services import briefs as B
        return B.compile_reference_brief(project_dir, contract_id, int(slot))

    @server.tool(name="generation_submit", description="Submit a reference-conditioned generation job (idempotent)")
    def generation_submit(brief: dict, references: list[dict], idempotency_key: str,
                          offline: bool = False, provider_settings: dict | None = None) -> dict:
        from ..services import jobs
        return jobs.submit_generation(project_dir, brief, references, idempotency_key,
                                      offline=bool(offline),provider_settings=provider_settings).model_dump()

    @server.tool(name="job_get", description="Read a persisted job by id")
    def job_get(job_id: str) -> dict:
        from ..services import jobs
        return jobs.job_get(project_dir, job_id)

    @server.tool(name="job_claim", description="Claim a queued job with a worker lease")
    def job_claim(job_id: str, worker_id: str, expected_version: int) -> dict:
        from ..services import jobs
        return jobs.job_claim(project_dir, job_id, worker_id,
                              expected_version=int(expected_version))

    @server.tool(name="job_cancel", description="Cancel a non-terminal job (guarded)")
    def job_cancel(job_id: str, expected_version: int) -> dict:
        from ..services import jobs
        return jobs.job_cancel(project_dir, job_id, int(expected_version))

    @server.tool(name="job_reconcile", description="Recover expired-lease RUNNING jobs")
    def job_reconcile() -> dict:
        from ..services import jobs
        return jobs.job_reconcile(project_dir)

    @server.tool(name="orchestrator_run", description="Start a durable orchestrator run")
    def orchestrator_run(job_ids: list[str], max_attempts: int = 3) -> dict:
        from ..services import orchestrator as O
        return O.start_run(project_dir, list(job_ids or []), max_attempts=int(max_attempts))

    @server.tool(name="orchestrator_step", description="Claim the run's next job; resume from stored state")
    def orchestrator_step(run_id: str, worker_id: str) -> dict:
        from ..services import orchestrator as O
        return O.run_once(project_dir, run_id, worker_id=worker_id)

    @server.tool(name="orchestrator_send", description="Authorized send-complete for a claimed job (stored request)")
    def orchestrator_send(run_id: str, job_id: str, worker_id: str,
                          fencing_token: str, brief: dict | None = None,
                          offline: bool = False) -> dict:
        from ..services import orchestrator as O
        return O.orchestrator_send(project_dir, run_id, job_id, brief,
                                   worker_id=worker_id, fencing_token=fencing_token,
                                   offline=bool(offline))

    @server.tool(name="capabilities", description="Audited transport x operation table")
    def capabilities() -> dict:
        from ..services import capabilities as C
        return C.table()

    @server.tool(name="correction_claim", description="Claim an open correction task")
    def correction_claim(task_id: str, expected_version: int) -> dict:
        from ..services import authz as _az, corrections as C
        # MCP acts as the orchestrator principal; leases bind the holder id.
        return C.claim(project_dir, _az.Actor(type="orchestrator", id="mcp-worker"),
                       task_id, int(expected_version))

    @server.tool(name="generation_submit_offline", description="Queue a generation job without transmitting")
    def generation_submit_offline(brief: dict, references: list[dict],
                                  idempotency_key: str) -> dict:
        from ..services import jobs
        return jobs.submit_generation(project_dir, brief, references,
                                      idempotency_key, offline=True).model_dump()

    @server.tool(name="candidate_register", description="Register replacement assets as a child revision")
    def candidate_register(baseline_revision_id: str, new_revision_id: str,
                           slot_assets: dict[str, str], recipe: str) -> dict:
        from ..services import clips
        return clips.register_candidate(project_dir, baseline_revision_id, new_revision_id,
                                        {int(k): v for k, v in slot_assets.items()}, recipe).model_dump()

    @server.tool(name="repair_plan", description="Bounded repair task for named targets (3-attempt budget)")
    def repair_plan(baseline_evaluation_id: str, targets: list[str], mask_id: str,
                    attempt_count: int = 0) -> dict:
        import json as _json
        from .. import domain as D
        from .. import storage as S
        from ..services import repair as R
        con = S.connect(project_dir)
        try:
            edata, _ = S.get(con, "evaluations", baseline_evaluation_id)
            ev = D.Evaluation.model_validate_json(_json.dumps(edata))
        finally:
            con.close()
        return R.plan(ev, targets, mask_id, [], attempt_count)

    @server.tool(name="repair_evaluate", description="No-regression selection between baseline + candidate evaluations")
    def repair_evaluate(baseline_evaluation_id: str, candidate_evaluation_id: str,
                        targets: list[str], subjective: bool = False) -> dict:
        import json as _json
        from .. import domain as D
        from .. import storage as S
        from ..services import repair as R
        con = S.connect(project_dir)
        try:
            bdata, _ = S.get(con, "evaluations", baseline_evaluation_id)
            cdata, _ = S.get(con, "evaluations", candidate_evaluation_id)
            base = D.Evaluation.model_validate_json(_json.dumps(bdata))
            cand = D.Evaluation.model_validate_json(_json.dumps(cdata))
            from ..services import packets as _P
            _, base_contract = _P._resolve_revision(con, base.clip_revision_id)
            _, cand_contract = _P._resolve_revision(con, cand.clip_revision_id)
        finally:
            con.close()
        return R.evaluate_selection(base, cand, targets, subjective=subjective,
                                    baseline_contract=base_contract,
                                    candidate_contract=cand_contract)

    @server.tool(name="review_packet_create", description="Curate a review packet for a revision+evaluation")
    def review_packet_create(packet_id: str, revision_id: str, evaluation_id: str,
                             intent: str, comparison_revision_id: str | None = None) -> dict:
        from ..services import packets
        return packets.create_packet(project_dir, packet_id, revision_id,
                                     evaluation_id, intent,comparison_revision_id).model_dump()

    @server.tool(name="corrections_list", description="List correction tasks (model work queue)")
    def corrections_list(status: str = "open") -> dict:
        from ..services import corrections
        if status == "open":
            return corrections.list_open(project_dir)
        if status == "all":
            return corrections.list_tasks(project_dir)
        return corrections.list_tasks(project_dir, [s.strip() for s in status.split(",")])

    @server.tool(name="correction_get", description="Explicit correction task status + lease + attempts")
    def correction_get(task_id: str) -> dict:
        from ..services import corrections
        return corrections.get_task(project_dir, task_id)

    @server.tool(name="correction_submit", description="Gated repair submit (holder+token+lease+scope+matrix)")
    def correction_submit(task_id: str, claim_token: str, new_revision_id: str,
                          slot_assets: dict[str, str], recipe: str,
                          baseline_evaluation_id: str, idempotency_key: str,
                          expected_version: int = 1, transform: dict | None = None) -> dict:
        from ..services import authz as _az, corrections as C
        # MCP acts as the orchestrator worker; holder binding is checked inside.
        return C.submit_correction(project_dir, _az.Actor(type="orchestrator", id="mcp-worker"),
                                   task_id, claim_token=claim_token,
                                   expected_version=int(expected_version),
                                   new_revision_id=new_revision_id,
                                   slot_asset_ids={int(k): v for k, v in slot_assets.items()},
                                   recipe=recipe, transform=transform,
                                   baseline_evaluation_id=baseline_evaluation_id,
                                   idempotency_key=idempotency_key)

    @server.tool(name="world_trace_record", description="Store frozen per-tick world grounding for a revision")
    def world_trace_record(revision_id: str, positions: list[list[float]],
                           planted: list[bool]) -> dict:
        from ..services import clips
        return clips.record_world_trace(project_dir, revision_id, positions,
                                        planted).model_dump()

    @server.tool(name="eligibility_get", description="Release eligibility for a revision")
    def eligibility_get(revision_id: str) -> dict:
        from ..services import eligibility as E
        return E.release_eligibility(project_dir, revision_id)

    return server
