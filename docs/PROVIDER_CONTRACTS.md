# Provider contracts — spike 2026-10-27 (offline, no key)

Environment: no `MODEL_API_KEY`/`META_API_KEY` set. All calls below ran offline and sent nothing.
`sent: false` fixtures under `fixtures/provider-spike/` capture exact request shapes only.

## Researched starting points (verify with participant account before building UX)

- Base URL: `https://api.meta.ai/v1`, bearer auth through `MODEL_API_KEY`. Source: https://dev.meta.ai/docs/overview
- Spark `muse-spark-1.3`: structured tool loop; local tool execution is the application's responsibility
  (https://dev.meta.ai/docs/tool-calling); structured output for contracts/critics where supported, still validated server-side
  (https://dev.meta.ai/docs/structured-output); model page https://dev.meta.ai/models/muse-spark.
- Muse Image `muse-image-1.0`: reference-conditioned Responses flow + edits endpoint;
  `size` controls aspect ratio, NOT guaranteed exact pixels; select returned image items by type; archive bytes immediately, not signed URLs;
  internal search controls should be disabled for reproducible original-character work where supported.
  Source: https://dev.meta.ai/docs/image-generation
- SAM 3.1: Responses with real image/video content; special-token box/mask output requiring decoding; store mask bytes, prompt,
  coordinate mapping, model identity, request ID, confidence. Source: https://dev.meta.ai/docs/media-segmentation
- MCP SDK catalog: https://modelcontextprotocol.io/docs/sdk (pin a tested release in WP3; no protocol hand-rolling).

## v1 prototype gaps (code inspection, `framebound/meta_api.py`)

1. `generate_image()`: sends `{model, prompt, size: 1024x1024}` to `/images/generations` — text-only, carries NO bound reference pixels/IDs,
   no negotiated output encoding/alpha, no response-item type selection, no byte persistence.
2. `segment()`: sends `{model, image: <local path string>, prompt}` to `/chat/completions` — never transmits image bytes,
   never decodes special-token masks; offline fallback returns an alpha-derived mask labeled `offline-alpha` (honest label, not SAM output).
3. `vision_critique()`: chat-completions shape is plausible but unexercised; advisory-only contract is correct and must be kept.
4. No ledger: request/response artifacts, reference role+hash capture, cost/usage recording, idempotency keys, timeout reconciliation — all absent.

## Offline fixtures (this spike, redacted, `sent: false`)

- `fixtures/provider-spike/spark-critique.json` — Spark chat-completions critique request shape (contract summary + fault codes + image parts).
- `fixtures/provider-spike/image-generation.json` — Muse Image generation request shape as v1 sends it (deficient: no references).
- `fixtures/provider-spike/image-edit.json` — intended edit/mask shape to confirm in live spike (unimplemented in v1).
- `fixtures/provider-spike/sam-segmentation.json` — intended SAM Responses shape to confirm in live spike (v1 sends wrong shape).

## Status 2026-10-28: deterministic gates done (R3); live spike pending credentials

Transport, parsing, and controller work below is implemented and contract-tested
(`providers/wire.py`, durable jobs, orchestrator; 17 R3 regressions). What remains
is the authorized live exercise — it needs a participant credential, which was never
available in this pass. The harness is ready:

```sh
# one recorded run: references + request/response bytes + registered revision +
# evaluation + comparison packet, or an honest pending bundle without a key
MODEL_API_KEY=<participant-key> python -m framebound recorded-run --project proj \
  --contract c-01 --slot 0 --baseline clip-01 --new-id gen-01 --out live-run.json
```

## Rules for the live spike (requires key + participant account)

- Save ONE redacted request/response per flow: Spark tool call, image request with ≥2 role-labeled references, image edit, SAM decode to aligned mask.
- Pin SDK/parser versions; record docs URLs + date. No-key result is `unsupported/not_configured`; offline procedural and recorded-replay stay distinct.
- Retry only bounded transient failures with backoff; record cost/usage when returned, mark estimates as estimates.
- Never label alpha fallback as SAM output. SAM failure surfaces as unsupported/failed coverage, never silently replaced.
- Live availability is reported separately from engineering completeness: a live skip
  leaves live proof pending, never "engineering complete".
