"""Single machine-readable capability truth: transport x operation.

Consumed by API/desk/CLI/docs. Historical ledgers stay historical; this table
describes the current implementation only. Columns: transport, operation,
status (supported/provisional/unsupported), and a note with artifact or
pending-reason links.
"""
from __future__ import annotations

ROWS = [
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
    ("cli", "reviewer-pair/open", "supported", "operator-secret ceremony; atomic single-use"),
    ("cli", "reviewer-revoke", "supported", "operator revokes session tokens"),
    ("cli", "reference-approve", "supported", "reviewer session required"),
    ("cli", "export/dataset-validate", "supported", "selected closure; pre-publish validation"),
    ("cli", "correction-submit/get", "supported", "crash-safe publish + identical replay envelope"),
    ("cli", "mask-approve", "supported", "reviewer session required"),
    ("cli", "issue-reopen/eligibility", "supported", "ordered reducer + lineage-aware release"),
    ("cli", "recorded-run", "deprecated", "four-capability bundle retired from active workflow; use deterministic offline check/repair + explicit image/edit/sam providers"),
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
    ("api", "reviewer pair/open/revoke", "supported", "operator-gated pair; atomic open; revoke"),
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
    ("providers", "live-spike", "unsupported", "no authorized credentials configured; runner ready, pending key+ceiling+human approval"),
]


def table() -> dict:
    return {"schema_version": "2.0",
            "rows": [{"transport": t, "operation": o, "status": s, "note": n}
                     for (t, o, s, n) in ROWS]}
