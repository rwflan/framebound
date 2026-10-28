# Model-facing tools

The primary consumer is the orchestrating model. Humans use the review desk; models use these. All commands take and return JSON.

## CLI

```sh
python -m framebound check --contract project/contract.json [--report out.json] [--anchors anchors.json]
python -m framebound brief --contract project/contract.json --slot 2 --out build/brief
python -m framebound preflight --contract project/contract.json --manifest candidates.json [--report out.json]
python -m framebound repair-plan --report report.json --out plan.json
python -m framebound repair-evaluate --contract project/contract.json --manifest repairs.json --out decision.json
python -m framebound record-failure --contract project/contract.json --slot 2 --code surface_span_drift --symptom "..." --expected "..." --out case.json
python -m framebound export-dataset --contract project/contract.json --out build/dataset
python -m framebound serve --contract project/contract.json --port 8765
python -m framebound mcp
```

Exit codes: `check`/`preflight` return 1 on any error-severity issue; `repair-evaluate` returns 0 only when a batch is `selected_for_review`.

## MCP

`framebound mcp` serves line-delimited JSON-RPC on stdio: `check_clip`, `compile_brief`, `preflight_candidate`, `plan_repair`, `evaluate_repair`, `export_dataset`, `list_corrections`. Tool errors are returned as data, not crashes.

## Intended orchestration loop

1. `compile_brief` for the slot. Generate with Muse Image using the brief; keep the request/response ledger.
2. `preflight_candidate`. On failure, read issue codes — do not retry blind.
3. `plan_repair` from the report; regenerate only the bounded region; `evaluate_repair`.
4. When `selected_for_review` is true, stop. Human review is next; poll `list_corrections` (or `GET /api/corrections`) for marked issues.
5. Apply corrections the same way: brief, generate, preflight. Never promote art yourself; approval is a recorded human decision.
6. `export_dataset` at milestones so passes, failures, repairs, and decisions accumulate as training data.

## Rules the tools enforce on the model

- A previous edit is never the sole generation reference.
- Rejected paths are forbidden inputs.
- No per-pose canvas fitting.
- Declared-but-unmeasurable anatomy is a warning to surface, not a pass to claim.
- A technical pass is not approval. Do not report art as accepted.

## v2 services (remediation pass, schema 2.0)

Same pattern — JSON in/out, thin transports over shared services (`framebound/v2/`).
Transports must not reimplement policy; CLI/MCP/API parity is audited in
`services/capabilities.py` (`capabilities` command).

```sh
python -m framebound asset-import --project proj --src img.png --asset-id a-01
python -m framebound contract-propose --project proj --contract contract.json
python -m framebound clip-create --project proj --contract-id c-01 --revision-id clip-01 --frames a,b,c --phases p0,p1,p2
python -m framebound clip-evaluate --project proj --revision-id clip-01
python -m framebound brief-compile --project proj --contract-id c-01 --slot 2   # needs stored human approval
python -m framebound job-submit --project proj --brief brief.json --idempotency-key k1 [--offline]
python -m framebound job-get --project proj --job-id job-xxx
python -m framebound job-claim --project proj --job-id job-xxx --worker-id w --expected-version 1  # returns fencing token
python -m framebound orchestrator-run --project proj --jobs job-xxx
python -m framebound orchestrator-send --project proj --run-id run-xxx --job-id job-xxx --worker-id w --fencing-token tok  # brief optional: stored request is authoritative
python -m framebound correction-submit --project proj --task-id t --claim-token tok --new-id r2 --slots 3=a --recipe "repair:bounded-patch" --baseline-evaluation ev --idempotency-key k2
python -m framebound mask-approve --project proj --issue evt --mask-asset m --slots 3   # reviewer session required
python -m framebound export --project proj --snapshot s1 --out build/s1 --revisions clip-01
python -m framebound dataset-validate --snapshot build/s1
python -m framebound recorded-run --project proj --contract c-01 --slot 0 --baseline clip-01 --new-id gen-01 --out run.json --offline  # DEPRECATED historical bundle (Stage A retired the Spark-critique gate); new work uses offline check/repair + explicit image/edit/sam providers
FRAMEBOUND_OPERATOR_SECRET=... python -m framebound reviewer-pair --project proj --reviewer-id human-1   # operator console only; desk login redeems the printed code (browsers never pair)
python -m framebound v2-mcp --project proj     # MCP stdio, official SDK (mcp==2.3.0), real handshake tested
python -m framebound serve --project proj --port 8765   # FastAPI review desk + typed DTOs (api/dto.py)
python -m framebound benchmark-eval --report bench.json   # public-service latency (cold/warm/incremental)
```

Rules the v2 tools enforce on the model (tested at the transport boundary):
unknown check codes are rejected at proposal; missing required inputs/authority can
never yield pass; evidence binds real pixels + code; reviewer identity comes from
operator-issued sessions, never headers or anonymous pairing; generation briefs must
reference a frozen compiled brief and transmit phase-guide pixels; offline jobs can
never flip live at send; one dispatch per reservation with fencing; ambiguous outcomes
reconcile instead of retrying; repairs obey ROI/mask scope, composed transform bounds
with pixel proof, leases, matrix equivalence and no-regression selection; failures land
as attempts, never orphaned revisions; exports publish only selected, rights-checked,
split-safe closures that the validator accepts from a moved directory.
