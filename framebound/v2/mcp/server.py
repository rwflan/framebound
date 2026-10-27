"""MCP stdio server over the v2 application services (pinned SDK mcp==2.3.0)."""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

TOOLS = ["doctor", "project_get", "asset_import", "contract_propose",
         "clip_create_revision", "clip_evaluate", "brief_compile",
         "generation_submit", "generation_submit_offline", "job_get",
         "job_claim", "job_cancel", "job_reconcile", "orchestrator_run",
         "capabilities", "correction_claim", "candidate_register",
         "repair_plan", "repair_evaluate", "review_packet_create", "corrections_list"]


def build_server(project_dir: str) -> MCPServer:
    server = MCPServer(name="framebound-v2", version="2.0.0a1")

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
                          offline: bool = False) -> dict:
        from ..services import jobs
        return jobs.submit_generation(project_dir, brief, references, idempotency_key,
                                      offline=bool(offline)).model_dump()

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
        finally:
            con.close()
        return R.evaluate_selection(base, cand, targets, subjective=subjective)

    @server.tool(name="review_packet_create", description="Curate a review packet for a revision+evaluation")
    def review_packet_create(packet_id: str, revision_id: str, evaluation_id: str,
                             intent: str) -> dict:
        from ..services import packets
        return packets.create_packet(project_dir, packet_id, revision_id,
                                     evaluation_id, intent).model_dump()

    @server.tool(name="corrections_list", description="List open correction tasks (model work queue)")
    def corrections_list() -> dict:
        from ..services import corrections
        return corrections.list_open(project_dir)

    return server
