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
