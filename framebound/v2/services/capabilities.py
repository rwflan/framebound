"""One audited capability table: transport x operation, no equivalence inflation."""
from __future__ import annotations

ROWS = [
    # (transport, operation, status, note)
    ("cli", "asset-import", "supported", "hash-verified import"),
    ("cli", "contract-propose", "supported", "typed validation, unknown checks rejected"),
    ("cli", "clip-create", "supported", "sequence-validated create"),
    ("cli", "clip-evaluate", "supported", "fail-closed matrix + evidence closure"),
    ("cli", "brief-compile", "supported", "stored human approval required"),
    ("cli", "job-submit", "supported", "idempotent queue; offline flag honored"),
    ("cli", "job-get", "supported", "persisted read"),
    ("cli", "job-claim", "supported", "leased claim"),
    ("cli", "job-cancel", "supported", "guarded terminal transitions"),
    ("cli", "job-reconcile", "supported", "expired-lease recovery"),
    ("cli", "orchestrator-run", "supported", "durable worker entry point"),
    ("cli", "candidate-register", "supported", "typed transform authority only"),
    ("cli", "packet-create", "supported", "evidence-bound packets"),
    ("cli", "corrections-list", "supported", "open queue"),
    ("cli", "reviewer-pair/open", "supported", "session bootstrap"),
    ("cli", "reference-approve", "supported", "reviewer session required"),
    ("cli", "export/dataset-validate", "supported", "R5 semantics pending re-audit"),
    ("mcp", "doctor/project_get", "supported", "parity with CLI reads"),
    ("mcp", "asset/contract/clip/evaluate/brief", "supported", "same services as CLI"),
    ("mcp", "generation_submit", "supported", "queues; offline honored via explicit param"),
    ("mcp", "job_get/job_claim/job_cancel", "supported", "durable lifecycle"),
    ("mcp", "orchestrator_run", "supported", "same durable entry point"),
    ("mcp", "candidate_register/repair_plan/repair_evaluate", "supported", "R4 gating lands next"),
    ("mcp", "correction_claim/correction_get/correction_submit", "supported", "holder-bound lease + gated scope/matrix submit (R4)"),
    ("mcp", "eligibility_get", "supported", "central release rule (R4)"),
    ("cli", "correction-submit/get", "supported", "gated submit + explicit status (R4)"),
    ("cli", "mask-approve", "supported", "reviewer session required (R4)"),
    ("cli", "issue-reopen/eligibility", "supported", "visible reopen + central rule (R4)"),
    ("api", "corrections submit (gated)", "supported", "holder+token+lease+scope+matrix; failures are attempts (R4)"),
    ("api", "masks/reopen/eligibility", "supported", "reviewer mask approval + visible reopen (R4)"),
    ("desk", "eligibility display", "provisional", "endpoint exists; desk wiring lands in R6"),
    ("mcp", "review_packet_create/corrections_list", "supported", "parity with CLI"),
    ("api", "reviewer pair/open", "supported", "session bootstrap"),
    ("api", "project/packets/packet/asset", "supported", "reads"),
    ("api", "issues/decisions/resolve", "supported", "reviewer-session enforced"),
    ("api", "corrections claim/submit", "supported", "lease + gated register (R4)"),
    ("api", "jobs submit/get/cancel", "supported", "added in R3"),
    ("api", "orchestrator run", "supported", "added in R3"),
    ("api", "events SSE", "provisional", "in-memory fan-out; restarts lose backlog (R6)"),
    ("desk", "compare", "unsupported", "empty screen until R6"),
    ("desk", "issue geometry survive restart", "unsupported", "until R6 journey lands"),
]


def table() -> dict:
    return {"schema_version": "2.0",
            "rows": [{"transport": t, "operation": o, "status": s, "note": n}
                     for (t, o, s, n) in ROWS]}
