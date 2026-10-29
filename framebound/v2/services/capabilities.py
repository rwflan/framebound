"""Single machine-readable capability truth: transport x operation.

Consumed by API/desk/CLI/docs. Historical ledgers stay historical; this table
describes the current implementation only. Columns: transport, operation,
status (supported/provisional/unsupported), and a note with artifact or
pending-reason links.
"""
from __future__ import annotations

ROWS = [
    ('cli', 'project-create/character-propose/guide-propose', 'supported', 'public immutable setup; identical replay'),
    ('mcp', 'project_create/character_propose/guide_propose', 'supported', 'same validated creation services'),
    ('desk', 'references', 'supported', 'stored proposals, phase pixels and reviewer-only approval'),
    ('cli/mcp/api','animation compile/start/step/get','supported','reviewed controls, actual native operators, scoped specialist jobs and restart-safe grants'),
    ('cli/api','provider grants/receipts','supported','operator-only issue/revoke/reconcile; no blind retry after ambiguity'),
    ('desk/api','reference revocation','supported','reviewer event blocks new work and current release; history retained'),
    # (transport, operation, status, note)
    ("cli", "asset-import", "supported", "hash-verified import"),
    ("cli", "contract-propose", "supported", "typed validation, unknown checks rejected"),
    ("cli", "clip-create", "supported", "sequence-validated create"),
    ("cli", "clip-evaluate", "supported", "fail-closed matrix + shared evidence verifier"),
    ("cli", "brief-compile", "supported", "frozen CompiledBrief; approval + phase pixels"),
    ("cli", "job-submit", "supported", "idempotent queue; frozen request; offline immutable"),
    ("cli", "job-get", "supported", "persisted read incl. fencing/origin/attempts"),
    ("cli", "job-claim", "supported", "QUEUED-only fenced claim; expired leases reconcile"),
    ("cli", "job-cancel", "supported", "guarded terminal transitions"),
    ("cli", "job-reconcile", "supported", "expired-lease recovery, no auto-reclaim"),
    ("cli", "orchestrator-run", "supported", "durable worker entry point"),
    ("cli", "orchestrator-send", "supported", "stored-request send; brief optional+fingerprinted"),
    ("cli", "world-trace-record", "supported", "frozen per-tick grounding"),
    ("cli", "candidate-register", "supported", "composed bound + pixel-verified translation"),
    ("cli", "packet-create", "supported", "evidence-bound packets"),
    ("cli", "corrections-list", "supported", "open queue"),
    ("cli", "reviewer-revoke", "unsupported", "session revocation is available through the operator API"),
    ("cli", "reference-approve", "supported", "reviewer session required"),
    ("cli", "export/dataset-validate", "supported", "selected closure; pre-publish validation"),
    ("cli", "correction-submit/get", "supported", "crash-safe publish + identical replay envelope"),
    ("cli", "mask-approve", "supported", "reviewer session required"),
    ("cli", "issue-reopen/eligibility", "supported", "ordered reducer + lineage-aware release"),
    ("cli", "recorded-run", "supported", "persistent optional image/edit/SAM probe; no critic gate; live observation pending"),
    ("cli", "benchmark-eval", "supported", "small + 200-frame workloads; playback timing separate"),
    ("mcp", "doctor/project_get", "supported", "parity with CLI reads"),
    ("mcp", "asset/contract/clip/evaluate/brief", "supported", "same services as CLI"),
    ("mcp", "generation_submit", "supported", "queues; offline explicit; compiled brief required"),
    ("mcp", "job_get/job_claim/job_cancel", "supported", "fenced lifecycle"),
    ("mcp", "orchestrator_run/step/send", "supported", "bounded worker via controller"),
    ("mcp", "world_trace_record", "supported", "same service as CLI"),
    ("mcp", "candidate_register/repair_plan/repair_evaluate", "supported", "scope+matrix gating"),
    ("mcp", "correction_claim/correction_get/correction_submit", "supported", "crash-safe submit"),
    ("mcp", "eligibility_get", "supported", "central release rule"),
    ("mcp", "review_packet_create/corrections_list", "supported", "parity with CLI"),
    ("api", "local browser review", "supported", "automatic same-origin HttpOnly session; loopback only"),
    ("api", "project/packets/packet/asset", "supported", "reads; desk media served"),
    ("api", "issues/decisions/resolve", "supported", "reviewer enforced; strict candidate+packet resolve"),
    ("api", "corrections claim/submit", "supported", "crash-safe gated register"),
    ("api", "masks/reopen/eligibility", "supported", "ordered reducer; lineage-aware release"),
    ("api", "world-trace", "supported", "frozen grounding endpoint"),
    ("api", "jobs submit/get/claim/cancel/reconcile", "supported", "durable controller"),
    ("api", "orchestrator run/send", "supported", "authorize+single-dispatch+reconcile"),
    ("api", "export/validate", "supported", "selected closure; semantic pre-publish gate"),
    ("api", "build-identity", "supported", "packaged lock digest + desk presence"),
    ("api", "events SSE", "provisional", "in-memory fan-out; restarts lose backlog"),
    ("desk", "playback/compare/issues/corrections/export", "supported", "browser journey green incl. restart"),
    ("desk", "status", "supported", "capability truth + pending model work"),
    ("desk", "reviewer login", "supported", "operator-code only; no browser minting"),
    ("providers", "spark-critique", "deprecated", "retired from active workflow; historical wire validation only; not a readiness gate; core makes zero general-purpose model calls"),
    ("providers", "image-generation/edit", "supported", "single dispatch; edit chains; origin labeled"),
    ("providers", "sam-segmentation", "supported", "status-gated outcomes; proposals materialized"),
    ("providers", "live-spike", "provisional", "persistent configuration and grants implemented; participant live observation pending"),
]


def table() -> dict:
    return {"schema_version": "2.0",
            "rows": [{"transport": t, "operation": o, "status": s, "note": n}
                     for (t, o, s, n) in ROWS],
            'evidence':EVIDENCE}


# This is checked-in release evidence, not a claim that the current process ran tests.
# Reviewer fixtures demonstrate boundaries; they never claim entrant art acceptance.
EVIDENCE=[
    {'capability':'native automatic repair','designed':True,'implemented':True,'negative_tested':True,'public_integrated':True,'live_observed':None,'human_reviewed':None,
     'receipts':['tests/test_automatic_execution.py','web/e2e/journey.mjs']},
    {'capability':'scoped image repair and optional SAM','designed':True,'implemented':True,'negative_tested':True,'public_integrated':True,'live_observed':False,'human_reviewed':False,
     'receipts':['tests/test_scoped_specialist_repair.py','tests/test_segmentation_controller.py','tests/test_specialist_resume.py']},
    {'capability':'provider dispatch grants and reconciliation','designed':True,'implemented':True,'negative_tested':True,'public_integrated':True,'live_observed':False,'human_reviewed':None,
     'receipts':['tests/test_dispatch_reservations.py','tests/test_provider_recovery.py','tests/test_public_transport_contracts.py']},
    {'capability':'persistent review and portable training consumption','designed':True,'implemented':True,'negative_tested':True,'public_integrated':True,'live_observed':None,'human_reviewed':False,
     'receipts':['tests/test_snapshot_publication.py','web/e2e/journey.mjs']},
    {'capability':'participant live art and hackathon submission','designed':True,'implemented':False,'negative_tested':False,'public_integrated':False,'live_observed':False,'human_reviewed':False,
     'receipts':['docs/SUBMISSION_REQUIREMENTS.md']},
]
