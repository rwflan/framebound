# Framebound — Implementation Status (remediation pass)

Remediation authority: external `Framebound-Remediation-Plan.txt` (kept outside the repo; never committed).
Baseline: `b680d84` (audited main, 2026-10-27). `main` has not advanced since the audit; no delta to adapt to.
Prior ledger entries below are historical. The earlier "64 passing tests" and "engineering complete except
for entrant actions" claims are NOT accepted as proof; each remediation package re-proves its gate.

## Current package: R8 — release re-audit (done on branch `codex/r8-release-audit`, 2026-10-28)

Prior package entries below are point-in-time records (dated 2026-10-27/28); commands
marked historical were re-verified at each gate. This entry reconciles every deferred
item instead of assuming a later package delivered it.

### Capability matrix (designed | implemented | negative-tested | integrated | live-verified | human-reviewed)

- Safe writers (refuse/relocate, never delete user data): Y Y Y CLI+services — N/A
- Reliable verification runner (no masked exits): Y Y Y script — N/A
- Locked reproducible install: Y Y Y venv+pip-check — N/A (re-proven R8 below)
- Authority + transactions (sessions, stored approval, atomic writes, idempotency): Y Y Y CLI/MCP/API — boundary documented (filesystem access bypasses HTTP roles by design)
- Fail-closed evaluation + reproducible evidence: Y Y Y CLI/MCP/API — N/A
- Provider wire + durable controller/jobs: Y Y Y CLI/MCP/API **live: NO** (no credential; harness + `recorded-run` ready)
- Bounded repair + correction state: Y Y Y CLI/MCP/API+browser — N/A
- Training views (rights/approval/procedural policy, pixel-correct COCO, genuine pairs, portable temporal): Y Y Y CLI/API+browser(HF proved in capable env) — N/A
- Review desk (media, marking, correction, restart, comparison, resolution, export): Y Y Y browser+API (real chromium journey) — N/A
- Demo as evidence (labels, counts, flight truth, measured traces, no fake approval): Y Y Y CLI — live run NO, human review NO (pkt-run-01 UNREVIEWED)
- Docs vs reality: audited this package (README/DESIGN/MODEL_TOOLS/DATASET/PROVIDER_CONTRACTS/HACKATHON/DEMO_SCRIPT corrected; portal items stay entrant-owned)
- Public-service benchmark: Y measured (`benchmark-eval`; primitives kept separate)
- Submission/portal/receipt: entrant-only, pending (exact blocker recorded, not engineered around)

### Deferred items, reconciled (nothing assumed delivered)

- R3: SAM `include_confidence` still provisional (parser accepts both forms) — kept, documented in code.
- R3/R6: SSE fan-out still in-memory — the durable path is DB-backed `GET /api/activity` with cursor catch-up (tested across restarts); SSE kept for live ticks only.
- R5: imported-video review path (analysis-unavailable reduced coverage) not exercised — no fixtures exist; desk shows uncovered coverage honestly rather than claiming it.
- R5/R7: `world_positions`/`planted`/transition traces absent from presented traces — temporal rows list them under explicit `missing` (validator requires the disclosure).
- R4/R6: desk shows decision + coverage per packet but not the computed eligibility predicate — the endpoint exists (`GET /api/eligibility/:rev`) and export/publication consume the central rule; desk display is a small follow-up, not a gate failure.
- R5: this dev interpreter lacks `_lzma`, so `datasets` cannot import here — the validator returns an explicit capability skip; full imagefolder materialization was proven in a capable interpreter (R5 evidence) and re-proven in the R8 fresh env below.
- Live spike (Spark tool call + image + edit/patch + SAM decode with participant key), authenticated portal check, genuine human review, demo video, submission receipt: all pending on the entrant/credential, each with its exact next step in SUBMISSION_REQUIREMENTS.md. No 'engineering complete except entrant' claim is made: every independent gate above IS demonstrated.

### Fresh verification (R8 evidence, `/tmp/fb-r8-evidence/`)

- `bench-eval` (public service, 8×64×64, registration+area+cadence+provenance): technical pass; cold p50 ≈ 322 ms (fresh interpreter, n=5); warm p50 ≈ 27 ms, p95 ≈ 61 ms (n=25); incremental changed-frame p50 ≈ 37 ms (whole-revision re-evaluation, no incremental cache — reported, not hidden). Full report: `bench-eval.json`.
- Clean clone of main @ proof-SHA: `git status` clean; fresh capable venv (`python3.15`, working `_lzma`); `pip install .[test,export-validation]` + `pip check` clean; full `pytest` green incl. the live `datasets.load_dataset("imagefolder")` materialization test; `pip wheel --no-deps .` builds (packaging proof, not just checkout success); installed-package `import framebound` + `framebound doctor` + `v2-mcp` handshake; web production build; real browser/process-restart journey; moved-snapshot consumption. Logs kept in the evidence dir (environment-specific, not committed); SHAs + outcomes recorded here.
- Offline/live semantics: `verify-local` forces bogus keys present and still passes with zero egress (offline neutrality pinned by R0/R3 tests); `--live` without a key exits 2 with an explicit message. A live skip is recorded as pending, never as a pass.

### Changed capability (R8)

- `benchmark-eval` CLI + `framebound/v2/bench_eval.py` (cold/warm/incremental, hardware + checks disclosed).
- Docs corrected to match implementation (see package notes); no external handoff files committed.
- `recorded-run` CLI is the exact live-spike command (pending credential).

### Limitations / next (entrant-owned)

- Live provider spike: `MODEL_API_KEY=<participant-key> python -m framebound recorded-run …` (see PROVIDER_CONTRACTS.md). Blocker: no participant credential was ever available in this pass.
- Portal: exact fields/rules/video limit/hosting/reuse terms need the authenticated portal (SUBMISSION_REQUIREMENTS.md lists each unverified item).
- Visual decisions: pkt-run-01 (demo) + any desk packet needs a real reviewer; model cannot self-approve.
- Submission: video + form + receipt by 4 Nov 18:00 Dublin (internal target); only the entrant can complete it.

## Current package: R7 — demonstration as evidence (done on branch `codex/r7-demo-evidence`, 2026-10-28)

Acceptance gate: the suite still catches controlled faults but emits no human labels;
declared flight/support semantics exercised through presented pixels; all eight run phases
plus held-tick boundaries covered by measured (not assigned) traces; a recorded-run
harness produces reference inputs, request/response/output bytes, failures, repair
evidence, a review packet and honest unreviewed status — or a pending bundle naming the
exact blocker. All demonstrated.

### Changed capability

- `demo_character.py`: far-foot lift per phase; jump rise/apex/fall genuinely airborne
  (support pixels 0,0,0) while crouch/launch/land stay planted; run/attack/idle keep a
  planted foot in every phase per their continuous-contact schedule. `build_character`
  returns scoped counts that never double-count (22 independent clip rasters, 6 transition
  drawings, 24 presented samples) with explicit identity/style and transition overlaps.
- `demo_wp6.py`: imports as source_kind=procedural/rights=original (no more original-
  masquerade around the procedural policy); real evaluated transition contracts (all pass);
  16 measured interruption traces over every slot interior + every held-tick boundary with
  per-trace departure/entry hashes, entry-policy verification, preserved flags computed
  from pixels, and contact-continuity counts (`transition_traces.json` persisted); check
  profile documented with coverage per clip (palette/phase checks excluded for lack of
  independent guides — recorded, not silently skipped); NO scripted reviewer approval —
  packet pkt-run-01 stays UNREVIEWED with a pending-decision note; export reflects the
  unreviewed state (research, 0 positives, exclusions explain).
- `recorded_run.py` (new) + `recorded-run` CLI: one genuine generated-character workflow.
  Offline/keyless → pending bundle naming MODEL_API_KEY + prepared brief/references, zero
  network, zero invented rows. Live/fake transport → generated asset import, registered
  candidate revision, evaluation, comparison packet; failures recorded with status
  recorded-failure, never retried or cherry-picked; origin labeled live vs
  provider-simulated; acceptance always unreviewed. Spark/SAM live paths now also persist
  the redacted request artifact (R3 capture rule completed).
- `tests/test_v2_demo.py` rewritten to evidence semantics: scoped counts, evaluated
  transitions, no-approval assertion (fails on any approve event), procedural labeling,
  run-contact/jump-flight pixel truth, measured 16-trace interruption coverage, injected
  pulse fault failing `torso_span` as a labeled regression with demo totals untouched,
  offline-pending and simulated-bundle recorded-run cases.

### Failing repros fixed (reproduced before fixing)

- Scripted `Actor(type='reviewer')` self-approval + "human decision recorded" claim →
  removed; suite asserts zero approve events and UNREVIEWED status (pinned).
- One far foot grounded in every jump phase with flight waivers → genuinely airborne
  rise/apex/fall (0 support px) verified per slot (pinned).
- `preserved=True`/always-attack:0 assigned booleans + 7-tick phase gaps →
  16 measured traces over all slots + boundaries with computed flags (pinned).
- Mixed incompatible totals (24 vs 22, transitions uncounted) → scoped counts with
  explicit overlaps; injected faults kept out of demo totals (pinned).
- Procedural art as `source_kind=original` bypassing positive policy → procedural +
  rights=original; export correctly yields research-only positives=0 (pinned).

### Actual commands/results (2026-10-28, Dublin; python 3.11.4)

- `python -m pytest tests/ -q` → `156 passed, 1 skipped` (151 prior + 12 new R7 − 7 rewritten).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0 (incl. browser journey).
- Demo: clips run/jump/attack/idle all pass with coverage; transitions all pass;
  snapshot research-only (0 positives, exclusions explain; approval pending).

### Artifacts / limitations / next

- Limitations: the recorded LIVE run (origin=live) still needs an authorized participant
  credential — the harness is ready, the pending bundle names the exact blocker; genuine
  visual decisions need a real reviewer on pkt-run-01; `world_positions`/`planted` traces
  remain explicitly missing (temporal schema); docs-vs-reality audit + public-service
  benchmark + submission/portal work remain R8.
- Next: R8 — re-audit the release and handle real external blockers.

## Current package: R6 — the actual review experience (done on branch `codex/r6-review-desk`, 2026-10-28)

Acceptance gate (browser, real services/transports, disposable data): packet opens with
actual frame pixels + asset identity; pause/step/resume/speed preserve timeline continuity;
two intentionally different revisions both render with a measured pixel difference; a known
ROI + frame range is server-stored with exact geometry/category; API restart + browser reload
restore the same issue, decision context and source bytes; claim/submit via CLI then compare
+ resolve + reopen through the browser with the exact resolution event; export through the
desk, moved and consumed independently. Stalled media, missing range entries, absent issues
after restart or mismatched pixels all fail loudly. All demonstrated — `browser-journey: ok`.

### Changed capability

- `api/dto.py` (new, 20+ DTOs): the single typed contract per endpoint; wired as FastAPI
  response models (permissive extras, guaranteed fields) so the schema enforces the desk
  contract at runtime. `scripts/gen_api_types.py` (new, reproducible): emits
  `web/src/api-types.ts` (DTOs + 32-route endpoint table) with `--check` for CI.
- New endpoints: `GET /api/compare` (both immutable revisions + media URLs, evals, per-side
  holds/tps/loop; same character+action required, retiming mapped explicitly instead of
  frame-index equality), `GET /api/issues` (full detail: ROI/range/attempts/candidates/
  findings/coverage/decision/resolution), `GET /api/corrections?status=` (awaiting-comparison
  and blocked stay visible), `GET /api/packet/:id/contact-sheet` (deterministic PNG,
  content-hash header), `POST /api/packet/:id/preview` (deterministic hold-expanded mp4 via
  ffmpeg; 501 without it, never a fake video), `GET /api/activity` (DB-backed cursor
  catch-up that survives restarts), `POST|GET /api/exports` (desk-driven R5 export+validate).
  Packet frames now carry server-resolved `asset_url`s (the DTO caught the gap).
- Desk rewrite (`web/src/App.tsx`, `api.ts`, `useClock.ts`, `playback.ts`): hash routing
  (packet/compare/issues/corrections/export/activity) so reload restores context from the
  server; reviewer pair/open ceremony with session token (no self-asserted headers);
  presentation clock with monotonic accumulator (pause/resume/speed/step preserve authored
  ticks; one-shot terminal; keyboard); exact tick stepper + frame identity readout; native
  aspect ratio (no 288px distortion) with a tested `toNative` mapper (separate x/y scales,
  mirroring, clamping); preloaded media with error states and stale-callback guards; blink
  + canvas-difference compare with measured mean-abs-diff; issue detail with per-candidate
  resolve + reopen; corrections queue with all states + status filter; export builder view;
  DB-backed activity polling with persisted cursor; typed API client where errors become
  alerts, never empty success lists. No numerical quality score anywhere.
- `web/test/playback.test.mjs` + `npm run test:unit` (esbuild + node:test): slot/tick math
  mirrors `media/timeline.py`; the single-width-scale distortion is pinned wrong (5 vs 10).
- `web/e2e/journey.mjs` rewritten to the gate (setup via `web/e2e/setup.py` production
  services): asserts frame pixels/asset identity, tick continuity across pause/step/resume/
  speed, real diff %, server ROI/range/category, byte-identical assets across SIGKILL restart,
  CLI claim/submit, browser resolve with exact event, reopen visibility, desk export moved +
  independently validated. `verify-local` runs it as `browser-journey` (no more SKIP).

### Failing repros fixed (reproduced before fixing)

- Empty Compare screen → loads both revisions' media/evals/timing via `/api/compare`; proves
  both images visible + difference real (3.08% at the differing slot in the gate run) (pinned).
- Paint-counter evidence → accumulator clock + frame identity + media error states; unit tests
  pin tick math and the width-scale distortion (pinned).
- ROI/range accepted to 9000 → server bounds + `start<=end<total` validation; desk parses and
  the gate asserts stored geometry within ±2 native px (pinned).
- Reload losing context → hash routes + server-sourced issues/decisions + persisted activity
  cursor; gate kills the API process and reloads (pinned).
- In-memory SSE as only events → `/api/activity` cursor pagination, DB-backed (pinned).
- `Packet=any` bodies → generated DTOs + response models + `test_v2_api_dto.py` conformance
  (21 live assertions incl. cursor pagination and export round-trip) (pinned).

### Actual commands/results (2026-10-28, Dublin; python 3.11.4, node v22.23.4, chromium 156/headless-shell, ffmpeg 9.0.2)

- `python -m pytest tests/ -q` → `151 passed, 1 skipped` (145 prior + 5 R6 desk + 1 API-DTO file).
- `web` typecheck clean; `npm run test:unit` 3/3; production build ok (170 kB).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0, incl. `browser-journey: ok`
  (real API on :8766 + real chromium; diff 3.08%; export moved + revalidated).
- Contact-sheet bytes identical across separate app instances; preview mp4 deterministic
  across rebuilds (ffmpeg present) with command + hashes recorded.

### Artifacts / limitations / next

- Limitations: contact-sheet/preview/contact overlays for guides+masks render client-side only
  (server contact-sheet covers frames); SSE still in-memory (activity polling is the durable
  path); video preview needs ffmpeg (501 otherwise); imported-video review path not exercised
  (no fixtures); live provider spike still needs an authorized participant credential.
- Docs-vs-reality audit + benchmark of the public service remain R8's gate.
- Next: R7 — rebuild the demonstration as evidence (relabel + transition traces).

## Current package: R5 — portable training views with pixel-correct masks (done on branch `codex/r5-training-views`, 2026-10-28)

Acceptance gate: the 3x5 mask decodes pixel-exact with independently recomputed bbox/area;
unknown-rights/procedural/unreviewed/rejected targets absent from default positives with
reasons; approve->reject and human-vs-system comparisons label correctly; no pair exists
without a valid comparison or explicit weak origin; a moved snapshot loads images, masks,
references and sequences without the database or network; genuinely eligible positives
proven; legitimately empty positives succeed without invented examples. All demonstrated.

### Changed capability

- `exports/snapshot.py` (rewritten): `_rle` fixed — row-major bytes reshape to (h, w) C-order
  then `asfortranarray` for pycocotools; the old `reshape(order='F')` scramble (F09) is gone.
  Views: `hf/` positives (eligible-only imagefolder), `research/` labeled archive, `preferences.jsonl`
  (explicit human comparisons only), `weak_preferences.jsonl` (technical-ranking, labeled weak),
  `temporal.jsonl` (ordered refs, holds/timing/traces + explicit missing coverage), `closure/`
  (contracts, characters, guides, reference pixels, evaluations, attempts, events, masks).
  Policy enforced BEFORE copying: rights allow-list, procedural opt-in, per-revision eligibility
  (PASS+COMPLETE, fresh evidence, packet-bound exact approval, no blocking tasks) via R4's
  central rule; approve->reject invalidates (R4 eligibility hardened). Preferences need a
  comparison packet + reviewer approve on that packet for the chosen revision — descendant
  approval alone yields only a weak entry. Family/pixel-duplicate split validation with seed;
  one-family overlap recorded as a held-out-identity limitation, `strict` raises. Atomic
  publish (temp dir + self-check + rename); `ExportSnapshot` row persists identity/policy/
  revisions/evaluations/lock/content manifest with same-name-different-content conflict.
- `exports/validate.py` (rewritten): every COCO annotation decoded pixel-for-pixel against its
  packaged source alpha with recomputed area + bbox + re-encode round-trip (area-only check gone,
  8-image cap gone); HF positives materialized through `datasets.load_dataset("imagefolder")`
  with per-row pixel loads when the interpreter supports it, else a PIL structural fallback
  with an explicit skip (never a sys.modules lzma shim — the stub is deleted); preferences
  checked for files/hashes/distinctness/common conditioning/approval origin; temporal counts,
  timing, ordering, trace disclosure; closure parses; positives-only family/duplicate checks;
  manifest hash walk + stale/extra file detection + path-escape rejection; empty positives
  legitimate with exclusions. The `lzma` process-global stub is removed: without `_lzma` the
  validator returns a capability skip, not masqueraded success.
- Transports unchanged (export/dataset-validate CLI, devseed round-trip); `test_v2_export.py`
  updated to corrected semantics (comparison-packet approval, family exclusions, total_ticks).
- `services/eligibility.py`: later reject/needs_changes/reopen supersedes packet-bound approval.

### Failing repros fixed (reproduced before fixing)

- 3x5 asymmetric mask scrambled by `order='F'` (same area, wrong pixels) → pixel-exact now;
  the new test fails on the old encoding (pinned).
- Default export copied all 24 procedural rows into loadable ImageFolder + unknown-rights
  assets + revoked approvals → positives contain only eligible human-approved rows; everything
  else explained in `research/` + exclusions (pinned).
- Descendant approval treated as preference → no pair without an explicit comparison packet
  + decision; technical rankings kept as a separately labeled weak view (pinned).
- Area-only validator on 8 images → full pixel/bbox/area validation on every annotation (pinned).
- Pixel mutations (same dimensions) pass → hash + pixel + pair-hash checks fail (pinned).
- `requirements.lock datasets==5.1.0` vs declared range → already resolved in R0 (`>=3,<6`);
  re-verified coherent; full stack proven in a capable interpreter (below).

### Actual commands/results (2026-10-28, Dublin; python 3.11.4 dev / homebrew 3.15 capable env)

- `python -m pytest tests/ -q` → `145 passed, 1 skipped` (134 prior + 11 new R5; the skip is the
  datasets loader test, which needs `_lzma`).
- `/tmp/hbvenv/bin/python -m pytest tests/test_v2_r5_export.py tests/test_v2_export.py -q` →
  `12 + 3 passed`, including `test_datasets_imagefolder_materializes_pixels`: genuine
  `datasets.load_dataset("imagefolder")` of the moved snapshot, every positive pixel materialized.
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0 (browser journey + live spike SKIPs).
- `datasets` 5.1.0 + `pycocotools` + `numpy` verified working in the capable env; dev-interpreter
  limitation (`_lzma` absent) recorded as skip reason, not worked around.

### Artifacts / limitations / next

- Limitations: desk wiring of eligibility display (R6); demo relabel + transition traces incl.
  `world_positions`/`planted` (R7, hence traces list them missing); full docs-vs-reality audit incl.
  `docs/DATASET.md` v1/v2 reconciliation (R8); live spike still needs an authorized participant credential.
- Next: R6 — the actual review experience (comparison media, durable desk state, browser journey).

## Current package: R4 — bounded repair and complete correction state (done on branch `codex/r4-bounded-repair`, 2026-10-27)

Acceptance gate: the 1x1-ROI whole-frame probe is rejected with zero partial writes;
unclaimed/foreign-holder/wrong-token/expired-lease/stale-baseline submits refused;
protected-pixel edits fail; error/unmeasured candidates never selected; subjective fixes reach
only human comparison; idempotent retry replays, payload conflicts raise; budget blocks;
history stays visible through resolve/reopen. All demonstrated.

### Changed capability

- `domain.EditMask` (new, frozen table `edit_masks`): reviewer-approved pixel authority —
  mask asset + hash + covered slots + approval event. An issue ROI suggests scope but never
  authorizes pixels by itself.
- `CorrectionTask`: binds `baseline_evaluation_id` at `open_issue` (no evidence → no issue)
  and `edit_mask_id` on approval; `last_error` for honest failure surfaces. Old rows load.
- `services/masks.py` (new): `approve_mask` (reviewer-only, stages a real `approve_mask`
  event), `scope_slots` (range/instance/mask union), `allowed_region` (per-slot ROI ∪ mask
  raster at canvas size; hash-freshness enforced).
- `services/repair.py`: `verify_scope` (out-of-scope slots, outside-region pixel diffs,
  no-ops rejected; reports changed slots/pixels) and full-matrix `evaluate_selection`
  (contract identity + required-set + (constraint, scope) matrix equality; new violations,
  coverage reduction, unresolved/error/unmeasured targets refused; technical path needs
  candidate PASS; subjective path needs passing baseline and returns `awaiting_human_comparison`).
- `services/corrections.py`: the single gated `submit_correction` used by every transport —
  holder/token/lease/state/baseline checks before any write; pixel scope then register →
  evaluate → select → packet → task transition, each step idempotent so retries converge;
  failures land as failed `Attempt` rows (deterministic `att-{sha(task:key)}` ids give
  same-key replay vs different-payload conflict); expired leases requeue to OPEN with attempts
  intact; 3 failures → BLOCKED; `get_task` (lease validity, attempts, issue), `list_tasks`
  status filter, `reopen_issue` (resolved → REOPENED, history intact).
- `services/eligibility.py` (new): central release rule — latest eval PASS + COMPLETE,
  manifest present with unchanged candidate bytes, packet-bound reviewer approval for the
  exact revision+evaluation (packetless decisions are signal, not release), no unresolved
  blocking tasks.
- Transports: API submit rewritten to the gated use case (failures return 200 `ok:false`,
  never orphaned revisions); new `GET /api/corrections/{id}`, `POST /api/masks`,
  `POST /api/issues/{id}/reopen`, `GET /api/eligibility/{rev}` (+ provider error codes
  403/409/422/429/502/503/504 mapped); CLI `correction-submit/get`, `mask-approve`,
  `issue-reopen`, `eligibility`; MCP `correction_get/submit`, `eligibility_get`,
  `corrections_list` status filter, `repair_evaluate` now passes contract context.
  `approve_mask` is deliberately absent from MCP/CLI-orchestrator surface (reviewer-only).
- Desk journey updated to the honest flow: reviewer approves a full-frame edit mask before
  the model may swap the faulty slot; claim version read from the task (mask approval bumps it).
- `ReviewEvent.action` gains `approve_mask`; authz marks it reviewer-only; the state reducer
  ignores it for acceptance (eligibility reads packet-bound approvals instead).

### Failing repros fixed (reproduced before fixing)

- 1x1 ROI + whole-frame replacement → refused at scope with zero new rows (pinned).
- Unclaimed submit (old API accepted → 201) → refused; foreign holder, wrong token,
  expired lease (requeued, attempts kept), stale baseline/evaluation, stale version → refused (pinned).
- 1px protected-pixel change outside ROI/mask → refused (pinned).
- Dropped required check / contract mismatch / error-unmeasured target → selection refused (pinned).
- Same idempotency key replays the stored envelope (even with a stale version); different
  payload → ConflictError; crash-retry converges through idempotent steps (pinned).
- Subjective issue on passing baseline → comparison packet + AWAITING_COMPARISON; orchestrator
  cannot resolve; reviewer resolve/reopen keeps full history (pinned).

### Actual commands/results (2026-10-27, Dublin; python 3.11.4, node v22.23.4)

- `python -m pytest tests/ -q` → `134 passed` (117 prior + 17 new R4).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0 (browser journey + live spike
  recorded as SKIP, not passes).

### Artifacts / limitations / next

- Limitations: export/publication do not yet consume `release_eligibility` (R5 wires the training
  view; desk wiring lands in R6). SAM `include_confidence` still provisional; SSE still in-memory.
  The live spike (authorized participant credential) still blocks only live proof.
- Next: R5 — rebuild training views and validate semantics.

## Current package: R3 — documented provider wire + durable controller/jobs (done on branch `codex/r3-providers-jobs`, 2026-10-27)

Acceptance gate: strict fake rejects legacy payloads and accepts repaired documented payloads
with actual approved pixels transmitted; generated output becomes a registered/evaluated revision;
crash/timeout/mismatched-idempotency/duplicate/cancel/restart deterministic; restarted runs cannot
reset attempt/cost budgets; missing keys block only the live exercise. All demonstrated.

### Changed capability

- `providers/wire.py` (new): internal-vs-wire separation. Validators for image/Spark/SAM payloads
  against the rechecked documented shapes (Responses `input_text`+`input_image` with data:/https:
  `image_url` or `file_id`; message-wrapped content; flat function tools with `tool_choice: auto`;
  `previous_response_id` chaining; `image_generation_call.result` extraction; `function_call` /
  `function_call_output` call_id matching; SAM 3.1 special-token grammar `<Nf>obj<|box|><|mask|>`
  with base85 `~`/`!` payloads decoded to row-major rasters). Legacy keys (`endpoint`, `note`,
  `image_b64`, `asset_id`, `type: text`, `<bytes>` placeholders) are named violations.
- `providers/image.py`: role explanations as text + approved pixels as images; `previous_response_id`
  refine chain; `build_edit_request` bounded-patch strategy (no invented inpainting); response parsing
  requires `status: completed` + decodable `image_generation_call.result`; output materialized
  (MIME/dims/alpha verified) and stored as a blob; redacted versioned artifacts with request IDs.
- `providers/spark.py`: pixel-carrying critique requests, flat allowlisted tools
  (`get_deterministic_findings`, `get_reference_metadata`), `execute_tool_calls` with
  `check_follow_up` (mismatched call_ids refused, mirroring HTTP 400), structured-critique schema
  validation; critique stays advisory. `submit_critique` chains follow-ups via `previous_response_id`
  without auto-spending.
- `providers/sam.py`: real-bytes `build_request` (placeholders rejected), `parse_output_text` for the
  special-token lane (`no_match`/`mask`/`empty`/`corrupt` explicit), separate PNG/COCO-RLE decoders;
  legacy `decode_mask` kept only as an explicit raw-byte offline helper (rejects ambiguous `mask_rle`
  as corrupt with a pointer to the correct parser); `alpha_fallback` still labeled offline-alpha.
- `providers/base.py`: capability states `not_configured` / `unverified` / `verified` /
  `permission_denied` / `model_unavailable` / `transport_error` / `response_invalid` — key presence
  alone never reports support. `verify_capability` probe + `http_post` with mapped errors
  (401/403→permission, 404/model-400→unavailable, 429→retryable, 5xx→transport, bad JSON→invalid).
- `providers/ledger.py`: versioned envelopes (`schema_version`, provider, model, request_id,
  timestamp) with redaction (`<bytes-redacted:N>`, secret scrubbing); `load_artifact` for tests.
- `domain.Job`: durable fields with defaults (provider, targets, attempt_count, max_attempts,
  budget/cost, signatures, request/response artifacts, output assets, reconciliation/cancel flags,
  offline, updated_at); new `Run` model + `runs` table. Old rows still load.
- `services/jobs.py`: QUEUED→RUNNING(leased claim)→SUCCEEDED|FAILED|NEEDS_ATTENTION|CANCELLED.
  Submit only queues (no transmit inside submit); claim enforces leases; success imports provider
  bytes as `generated` assets; retryable failures requeue within budget; ambiguous timeouts become
  reconciliation-required (never blind retry); cancel guards terminal states; `job_reconcile`
  recovers expired leases after crashes. Attempts staged atomically (fixed mid-transaction commit).
- `services/orchestrator.py` (new): `start_run` + `run_once`/`orchestrator_send` over persisted
  state — claims outside DB locks, sends outside transactions, halts at awaiting-review/blocker/
  no-progress/budget-exhaustion, no-progress checked before any send, budgets survive restarts.
- `services/capabilities.py` (new): one audited transport×operation table; desk compare + restart
  journey honestly `unsupported` until R6.
- Transports: CLI (`job-claim/cancel/reconcile`, `orchestrator-run/send`, `capabilities`,
  `--offline`/`--max-attempts`), MCP (same + `generation_submit_offline`, `correction_claim`),
  API (`POST/GET /api/jobs`, claim/cancel/reconcile, orchestrator runs/send, capabilities;
  provider errors mapped to 403/429/502/503/504).
- Demo/tests: `demo_wp6` ledger now carries real identity/style pixels (offline, untransmitted);
  `test_v2_loop` honesty tests updated to the documented wire (roles-as-text + pixels-as-images).

### Failing repros fixed (reproduced before fixing)

- Legacy `endpoint`/`note`/`type: text`/`image_b64`/`asset_id` payloads → named wire violations (pinned).
- Asset-id-only Spark frames and `<bytes>` SAM placeholders → rejected at build (pinned).
- `mask_rle`-as-raw-pixels confusion → corrupt with parser pointer (pinned); special-token fixtures
  round-trip pixel-exact (pinned).
- Ambiguous timeout left jobs invisibly queued → reconciliation-required + expired-lease recovery (pinned).
- Same key/different payload silently reused → ConflictError (pinned); budgets reset on restart →
  persisted attempt counts + run budgets (pinned).
- Offline with key present transmitted → never sends; artifacts redacted (pinned).

### Actual commands/results (2026-10-27, Dublin; python 3.11.4, node v22.23.4)

- `python -m pytest tests/ -q` → `117 passed` (100 prior + 17 new R3).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0 (browser journey + live spike
  recorded as SKIP, not passes).

### Artifacts / limitations / next

- Limitations (carried forward): repair lease/scope gating + masks (R4); export semantics incl. COCO
  geometry (R5); desk media experience (R6); demo relabel + transition traces (R7); public-service
  benchmark (R8). `world_positions`/`planted` traces still unstored — sliding stays honestly UNMEASURED.
  SAM `include_confidence` flag is provisional (parser accepts both forms). SSE fan-out still in-memory.
  Live spike (one Spark tool call, one image request, one edit/patch, one SAM decode) needs an
  authorized participant credential — deterministic gates above do not depend on it.
- Docs rechecked 2026-10-27: image-generation reference steering + `image_generation_call.result`
  + `usage`; tool-calling Responses flat tools + `function_call`/`function_call_output` + `auto`-only
  `tool_choice`; SAM overview/segmenting/reading-segmentation (special-token line grammar, base85
  masks, empty lane = no match, `parseImageStream`/`decodeMaskToRaster` client libraries).
- Next: R4 — bounded repair and complete correction state.

## Current package: R2 — fail-closed evaluation and reproducible evidence (done on branch `codex/r2-failclosed-evidence`, 2026-10-27)

Acceptance gate: every F03/F04/F05 probe fails-or-blocks; distinct reference pixels change evidence;
tampered blobs invalidate verify; F17 measurement fixes; CLI/MCP/service parity. All demonstrated.

### Changed capability

- `checks/params.py` (new): typed param schemas for all 14 canonical checks; unknown check codes rejected
  at `contract-propose` time (CLI + service); windows bounds-checked against the contract canvas; registry
  codes unified with evaluator dispatch (`silhouette_area`, `appearance_palette`, ... — the `_drift`
  suffixed registry names that no contract used are gone).
- `checks/evaluate.py` (rewritten): explicit expected matrix (required check x applicable scope) built
  before measuring; status computed against the matrix; registration/decodability + structural sequence
  integrity are mandatory prerequisites (a truncated/padded sequence raises, never passes); missing inputs
  emit UNMEASURED with named gaps; missing dispatch items synthesize analyzer ERROR; only
  contract-declared exemptions (flight slots, occluded slots, loop flag) yield NOT_APPLICABLE.
  Single dispatch keyed exactly on registry codes.
- Evidence closure: manifest binds candidate pixel+byte hashes, per-slot reference pixel hashes (+ byte
  hashes when the service resolves stored assets), character/contract content, annotation hashes,
  registration records, timeline/trace, analyzer code digest, check config, schema versions, dependency-lock
  digest. Different reference pixels always change the evidence ID at identical slot keys.
- `services/clips.evaluate`: resolves the full stored context (frames + held timing, motion-guide
  references from the stored R1 approval, character, annotations, registrations, presented holds);
  no more unconditional empty reference map. Re-evaluation of the same context returns the stored record
  (no more duplicate-ID ConflictError); changed context mints a superseding record. Manifest stored as a
  self-consistent blob under its own hash. Presented holds detect retimed clips via locked_cadence.
- `services/clips.create/register`: identity `Registration` records per frame; typed `TransformSpec`
  is the only transform authority (budget/asymmetry checked; legacy mirror/per-pose-fit strings denied,
  symmetric-character mirrors still allowed as recorded transforms). Registration table added + frozen.
- `domain`: `AnnotationRevision` requires real geometry (points and/or mask asset) with proposal/review
  provenance; `Registration` + `TransformSpec`/`TransformOp` models; `Evaluation.supersedes`.
- `verify.py`: nonexistent project path is an error without materializing anything; blob rehash,
  canonical-pixel rehash, relationship/sequence checks, manifest presence + reference-byte freshness,
  non-human approval flagging.
- `media/canonical.py`: dimension guard before raster decode, EXIF transpose.
- F17 fixes: cumulative stance-anchor drift (100x1-unit slide fails tol 2; replant resets); optional
  `support_color` pinning for contacts; loop-seam pulse (last→first) for looped clips; adjacent phases no
  longer excluded by default; occlusion reasons generic + contract-note; multi-blob features UNMEASURED.
- Fixture repair (recorded authority, measurement unchanged): idle compass was fragmented into two blobs
  by arm/scarf overdraw in `demo_character.py`; the declared chest feature now renders after those strokes.
  The strict detector caught a real fixture flaw; the fix is to the art, not to any bound.

### Failing repros fixed (reproduced before fixing)

- Required `world_sliding` without trace → was pass with zero results; now UNMEASURED/INCOMPLETE naming
  the missing trace (pinned). Invented check code → now rejected at proposal on every transport (pinned).
- One-frame revision against an eight-frame contract → evaluator and service both refuse (pinned).
- Clean vs opaque reference pixels at identical slots → was pass/fail under one evidence ID; now distinct
  manifest hashes + distinct verdicts (pinned). Re-evaluation → stable record, single row (pinned).
- Corrupted blob / deleted manifest / missing project → verify flags; ghost path creates nothing (pinned).
- 99-unit cumulative slide with 1-unit steps → FAIL; adjacent-phase exclusion removed; seam pulse present;
  ambiguous compass blobs → UNMEASURED instead of averaged (pinned, incl. the live idle fixture).

### Actual commands/results (2026-10-27, Dublin; python 3.11.4, node v22.23.4)

- `python -m pytest tests/ -q` → `100 passed` (88 prior + 12 new R2).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0.
- Demo: run/jump/attack/idle all pass under the strict measurement (idle via genuine whole compass art).

### Artifacts / limitations / next

- Limitations (carried forward): provider wire format + durable jobs (R3); repair lease/scope gating (R4 —
  `repair_protection` with context is implemented but no transport supplies masks yet); export semantics
  incl. COCO geometry (R5); desk media experience (R6); demo relabel + transition traces (R7); benchmark of
  the public service (R8). `world_positions`/`planted` have no stored trace yet — R7 records presented
  traces; until then required sliding without a bound trace stays honestly UNMEASURED. Annotation
  consumption by checks (support evidence, protection masks) lands with R4/R6, not here.
- Next: R3 — documented provider wire encoding, real output parsing, durable controller/jobs.

## Current package: R1 — real authority and transaction layer (done on branch `codex/r1-authority-transactions`, 2026-10-27)

Acceptance gate: session-backed reviewers, stored approval authority, relationship validation, atomic
multi-record writes, payload-bound idempotency, exercised migration. All demonstrated (see commands/results).

### Changed capability

- Reviewer sessions (`services/sessions.py`): localhost pairing ceremony (`reviewer-pair` mints a single-use
  code, `reviewer-open` exchanges it for a token; only token hashes stored). API writes resolve
  `X-Session-Token` to a live session; `X-Actor-Type` is ignored entirely (self-assertion → 403, bad token →
  401). Orchestrator identity stays a label with no reviewer powers. Documented threat boundary: transport
  checks cannot restrain direct filesystem access to the owner's database.
- Stored reference authority (`services/approvals.py` + `services/briefs.py`): draft motion guides via
  orchestrator tools; reviewer-only `approve_reference` binds exact identity/style/phase asset hashes in an
  immutable `ReferenceApproval` (supersession, never edits). CLI/MCP `brief-compile` now resolve this stored
  authority and fail without a current human approval — the fabricated `approved=True/imported` and
  `guide:<id>` adapters are deleted from both transports.
- Relationship validation (`services/packets.py`): packet→revision→contract→character, evaluation→revision,
  frame→revision, ROI inside the contract canvas, frame_range inside contract ticks, decisions require stored
  evaluation for the exact revision, packet must address the decided revision, staleness resolved against
  server state (`expected_evaluation_id` vs current). Job submit resolves reference bytes from the blob store
  hash-verified; caller bytes are cross-checked, never trusted.
- Transactions (`storage.atomic` + `stage`/`stage_update`): issue+task, frame-set+revision, resolution+task
  commit as one unit; injected mid-write faults leave zero partial rows (pinned by test).
- Frozen entities expanded to assets, character/annotation revisions, frame instances, attempts, review
  events, export snapshots; mutable remain projects, correction_tasks, jobs. Migration v1→v2 exercised on a
  legacy-shaped database (data intact, version bumped).
- Idempotency: same event/packet/job id + same content returns the stored result with `deduped`; same id +
  different content is a 409 `ConflictError` (jobs compare full payload fingerprints). Process-random `hash()`
  event ids replaced with server `uuid4` ids. Typed 4xx surfaces: 403/404/409/422 + `frozen_revision`.
- Strict domain: `StrictInt` holds/ticks/dims/slots/ROI/range (audit's `['4',True,2.0]` now rejected),
  finite-float guards, hex-shape hashes, `frame_range` shape, `ReviewEvent.category` preserved end to end,
  `CorrectionTask` carries `claim_holder` + token hash (submit-time enforcement lands in R4).
- Claim binds the authenticated caller; re-claim and stale versions conflict. New `current_state` reducer
  (latest decision wins; open issues from unresolved tasks) is served on `GET /api/packet`.
- Demo note: `demo_wp6`'s scripted in-process approval still exists and is relabeled honestly only in R7; it
  passes the new validation because its packet/evaluation/revision are self-consistent, not because the
  demo is a human.

### Failing repros fixed (reproduced before fixing)

- Header `X-Actor-Type: reviewer` recorded approvals → now 403 without a session token (pinned).
- `brief-compile` with unapproved references succeeded on all transports → now `InvalidInput` on CLI/MCP
  service and MCP tool error until a human approval is stored (pinned over real MCP stdio).
- Decision naming another revision's packet accepted → now 422 (pinned; desk journey updated to the
  correct packet).
- ROI/range `[0,9000]` on a 64px canvas accepted → now 422 (pinned); category discarded → now stored and
  asserted on the open task scope.
- 7-asset/1-phase and phase-swapped revisions stored → now rejected at the boundary; failed writes leave
  zero partial rows (pinned).
- Same idempotency key + different generation payload silently reused → now 409 (pinned).
- `verify-local`'s export round-trip no longer imports test helpers (`devseed` is production code).

### Actual commands/results (2026-10-27, Dublin; python 3.11.4, node v22.23.4)

- `python -m pytest tests/ -q` → `88 passed` (76 R0 + 12 new R1).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0 (unchanged gate, R1 code underneath).
- CLI ceremony: `reviewer-pair` → code; `reviewer-open` → token; reuse → `reviewer-open refused` exit 1.
- `test_v2_desk` journeys now pair over HTTP, assert holder binding, category preservation, mismatched-packet
  422, and explicit resolve/reopen visibility.

### Artifacts / limitations / next

- Limitations (carried forward): approval/event/brief authority is enforced; provider wire format (R3),
  fail-closed evaluation (R2), bounded-repair lease/scope gating (R4), export semantics (R5), desk media
  experience (R6), and demo relabeling (R7) are untouched. `AnnotationRevision` still cannot store point
  geometry (R2). `migrate-v1` remains a dry-run report. `CharacterRevision.reference_approval` is legacy and
  unread (approvals table is authoritative). In-process direct `Actor(type="reviewer")` calls still bypass
  sessions by design (filesystem access owns the database).
- Next: R2 — fail-closed evaluation and reproducible evidence (expected-scope matrix, evidence closure,
  verify hardening, movement-measurement fixes).

## Current package: R0 — safe outputs, reliable verification, install coherence (done on branch `codex/r0-safety-verify-install`, 2026-10-27)

Acceptance gate: sentinel-preserving refusal, per-child failure exits, fresh-venv locked install, offline neutrality
with keys present. All demonstrated (see commands/results).

### Changed capability

- `framebound/v2/safe_output.py` (new) — `prepare_output_dir()`: refuses non-empty outputs (`OutputExistsError`,
  byte-identical sentinel), optional replace only for framework-marked dirs with timestamped backup instead of
  `rmtree`, refuses filesystem root/home, refuses output == project dir / project-inside-output / output already
  holding project data. Wired into v1 `build_demo`, v2 `run_demo`, `run_wp6`, `build_snapshot`, and the
  `demo`/`export` CLI commands (`--replace` flag; default refuses).
- `scripts/verify-local` — rewritten: every step captures a log and checks the real exit status (no `| tail`
  masking); unique `mktemp` work/log dirs with trap cleanup; export round-trip uses the production
  `framebound/v2/devseed.py` builder (no test imports); runs web typecheck + production build; explicit `--live`
  semantics (fails without a key; fails until a live spike runner exists in R3); honest SKIP lines for
  browser journey (R6) and live spike. A final `ALL LOCAL CHECKS PASSED` prints only when every step passed.
- `framebound/v2/devseed.py` (new) — minimal disposable desk project built from production services only.
- Offline neutrality fix (found by the new regression test, not the audit): `run_wp6` called
  `providers/image.submit` without an offline flag, so with ANY `MODEL_API_KEY`/`META_API_KEY` set it performed a
  live `urlopen` to `api.meta.ai` from the "offline" demo. `image.submit` and `spark.submit_critique` now take
  `offline=True`, and the demo/CLI pass it unconditionally (demos are offline replays; live exercise is R3 work).
- `pyproject.toml` — `datasets>=3,<4` contradicted the installed/locked `5.1.0`; relaxed to `datasets>=3,<6`.
- `requirements.lock` — replaced the partial freeze with a complete 65-pin lock produced in a fresh Python 3.11
  venv (`pip install '.[test,export-validation]'`, `pip freeze`; `pip check` clean). `framebound.egg-info/`
  build output removed from the tree.
- `framebound/v2/doctor.py` — reports node/npm versions (tested: node v22.23.4, npm 12.2.1), refreshed stale note.

### Failing repros fixed (reproduced before fixing)

- Sentinel in existing out dir + `run_wp6`/`run_demo`/`build_demo`/`build_snapshot` → old code deleted it
  (`shutil.rmtree`); new code refuses, sentinel byte-identical (pinned by 6 tests).
- `verify-local` with a fake `python` exiting 37 for unittest/pytest → old script printed success; new script
  exits non-zero with no success message (pinned by 2 tests + a no-masked-pipeline grep test).
- `MODEL_API_KEY=bogus` + blocked DNS/connect + `run_wp6` → old code attempted `api.meta.ai:443`; new code
  completes all offline paths with zero egress (pinned by test).
- `pyproject` vs lock: `datasets` pin violated the declared range; fresh-venv install conflict reproduced by
  declaration; fixed bound + fresh install proof below (pinned by lock-coherence test).

### Actual commands/results (2026-10-27, Dublin; python 3.11.4, sqlite 3.54.0, node v22.23.4, npm 12.2.1)

- `python -m pytest tests/ -q` → `76 passed` (64 pre-existing + 12 new R0 regressions).
- `sh scripts/verify-local` → `ALL LOCAL CHECKS PASSED`, exit 0 (v1 unittest, v2 pytest, v2/wp6 offline demos with
  bogus keys present, verify, devseed export round-trip with moved snapshot, web typecheck, web production build).
- `sh scripts/verify-local --live` (no key) → exit 2, `FAIL: --live requires a real MODEL_API_KEY/META_API_KEY`.
- Fresh venv: `pip install '.[test,export-validation]'` → exit 0; `pip check` → `No broken requirements found`;
  65-pin freeze adopted as `requirements.lock`.
- `python -m framebound doctor` → ok; node v22.23.4 / npm 12.2.1 reported.

### Artifacts / limitations / next

- Artifacts: `requirements.lock` (complete), `scripts/verify-local` logs are ephemeral (`mktemp`, kept only on
  failure); no committed generated output.
- Limitations (honest, carried forward): browser/process-restart journey still a SKIP until R6; live spike still
  pending until R3 (blocked on participant credentials — no secret read or copied); audit findings F03–F20 are
  untouched and scheduled in R1–R7; `run_demo`/`build_demo` take no `offline` param (they make no provider calls,
  proven by test, but have no explicit guard — R3 may add one if they ever gain provider paths).
- Next: R1 — real authority/transaction layer (typed commands, server-resolved approvals, reviewer sessions,
  relationship validation, atomic multi-record writes, immutable evidence entities, idempotency, state reducer).

# Framebound — Implementation Status (v2 greenfield)

Plan authority: `Framebound-Implementation-Plan.txt` (external handoff, kept outside the repo).
This file is the status ledger. Design intent lives in the plan; only delivered + verified behavior is recorded here.

## Current package: WP1 — schemas and durable domain (done on branch `codex/wp1-schemas-domain`, 2026-10-27)

Acceptance gate: complete valid examples, invalid-input tests, stale-write protection, asset hashing, restart recovery, untouched originals. All pass.

### Delivered

- `framebound/v2/domain.py` — strict Pydantic v2 models, schema 2.0: Project, Asset, CharacterRevision, ClipContractRevision
  (frozen timing/phase coverage, unique slots/constraints), FrameInstance, ClipRevision, AnnotationRevision, CheckResult
  (unmeasured/not_applicable/error require explicit reason), Evaluation, Attempt, ReviewPacket, ReviewEvent (revision-bound,
  ROI pixel-edge rect), CorrectionTask (open→claimed→attempting→awaiting_comparison→resolved + blocked/cancelled/reopened),
  Job (idempotency key), ExportSnapshot, ResultEnvelope. Separate Technical/Coverage/HumanAcceptance/Publication/Job/Correction states.
  Coordinate convention: native_px origin top-left, holds positive ints, half-open slot intervals, `slot_at_tick` tested at boundaries + 10k-loop wrap.
- `framebound/v2/storage.py` — SQLite WAL (`framebound.sqlite3`) + `blobs/sha256/<2>/<rest>` (atomic tmp→hash→rename) +
  `exports/` + `backups/`. Frozen tables (contracts, clip revisions, evaluations, packets) reject updates; mutable rows use
  `expected_version` preconditions → `StaleRevisionError` (409 stale_revision). `create_job_idempotent` dedupes idempotency keys.
- `framebound/v2/migration.py` — `migrate-v1` dry-run only: importable media w/ byte hashes + PNG decodability, missing refs,
  malformed contracts, unresolved rights (v1 declares none), legacy slot-only decisions marked UNTRUSTED. Never mutates source.
- `framebound/v2/schemas.py` + `schemas/v2/*.schema.json` (16 models) + `examples/v2-valid-{contract,character}.json` +
  `examples/v2-negative/*.json` (7 invalid contracts: zero/empty holds, schedule gap, duplicate slot/constraint, bad facing/units).
- `framebound/v2/doctor.py`, `verify.py` — new CLI: `doctor`, `migrate-v1 --source --dry-run [--report]`, `verify --project [--report]`.
  v1 commands untouched; v1 suite still green.
- `framebound/v2/__init__.py` (`2.0.0a1`), `tests/test_v2_domain.py` (11 tests).

### Actual commands/results (2026-10-27, Dublin; `python` = 3.11.4, sqlite 3.54.0)

- `python -m pytest tests/ -q` → `24 passed` (13 v1 + 11 v2).
- `python -m framebound doctor` → ok; pydantic/numpy/fastapi/uvicorn present; PIL/mcp/datasets/pycocotools missing (expected pre-WP3/WP5).
- `python -m framebound migrate-v1 --source /tmp/fb-wp0-baseline` → 8+ importable media, 0 missing, rights unresolved (expected), mutated false.
- `python -m framebound verify --project /tmp/fb-v2-proj` → ok, empty project.

### Artifacts / limitations / next

- Artifacts: schemas, examples, fixtures all in-repo; baseline `/tmp/fb-wp0-baseline`, verify dir outside repo (not committed).
- Limitations: no media/checks layer yet (WP2); no services/providers/orchestration (WP3); no API/web (WP4); no exports (WP5).
  PIL still missing — WP2 pins Pillow+NumPy raster. MCP SDK still missing — WP3 pins official SDK + real client handshake.
- Next: WP2 canonical media + verification framework (registration, integer timeline, coverage matrix, evidence IDs, overlays, original faults).

## Current package: WP7 — release and submission (done on branch `codex/wp7-release`, 2026-10-27)

Completion gate: P0 gates pass; portal requirements checked; remote PR merged; submission receipt verified by entrant.
Engineering complete; entrant-side steps (portal, live spike, video, receipt) remain and are tracked below.

### Delivered

- `scripts/verify-local` — one entry point, clear failure exits: v1 unittest + v2 pytest + v2/wp6 offline demos +
  `verify` + export round-trip with moved-snapshot `dataset-validate` (real loaders) + honest provider skip.
  Result here: `ALL LOCAL CHECKS PASSED` (no key → skip recorded, not a pass).
- `requirements.lock` — pip-freeze pins for the exercised set (mcp 2.3.0, Pillow 13.0.0, datasets 5.1.0, …).
- `docs/DEMO_SCRIPT.md` — 6-beat demo with badges, adapted to the (still unverified) duration limit.
- README quick-start rewritten for v2 (install → verify → demo → desk) with v1 paths preserved.
- Clean-clone proof: fresh `git clone` of `main` runs the demo suites with no local-only files.
- Release-definition assessment (plan §17):
  - [x] Fresh clone + documented deps + offline demo + explicit provider config — yes (`verify-local`, README).
  - [ ] Live model run with reference-conditioned output + repair + packet + provenance — BLOCKED (no credentials).
  - [x] Registration/phase/timing/contact/protection/evidence-freshness regressions in independent tests — yes.
  - [x] Human issue survives restart, returns with exact ROI/range/revision; replacement compared — yes (API + browser E2E).
  - [x] Technical status + unresolved coverage visible after decisions; model cannot write decisions — yes (403/409).
  - [x] Moved export loads images/masks/guides/timing; failure/repair/decision traceable — yes (`dataset-validate`).
  - [x] Labels, rights, splits, lineage accurate — yes (origins, exclusions, leakage policy).
  - [x] Performance measured with misses/limits stated — yes (cold 3.7 s / warm 3.9 s for 200×256² core raster;
    ~19 ms/frame mean; 10k-loop drift test; packet-open timing via E2E paints; browser render skips observable, ticks exact).
  - [ ] Portal requirements checked against the actual portal — ENTRANT ACTION (authenticated access required).
  - [ ] Submission receipt verified — ENTRANT ACTION (only the entrant can do this).

### Scope honesty (no full-P0 claim)

P0 ships complete EXCEPT: (1) live Meta provider proof — adapter boundary + offline artifacts + honest badges only;
(2) authenticated portal rules/video/submission — entrant-side. No reduced-coverage hiding: jump occlusion is disclosed
as partial coverage; second facing is prohibited-by-design (documented, not silently dropped); independent vs presented
pose counts reported separately (22 vs 24); procedural demo positives opt-in only.

### Next exact step

Merge this PR, then the entrant: re-check portal → live spike → video → submit → paste receipt into
`docs/SUBMISSION_REQUIREMENTS.md`. Engineering resumes only on portal-driven changes.

## Prior: WP6 — genuine character demonstration (merged as PR #9) — genuine character demonstration (done on branch `codex/wp6-character-demo`, 2026-10-27)

Acceptance gate: full workflow works on real output; no hidden auto-fitting; visual acceptance accurately reported;
live/replay badges correct. All pass.

### Delivered

- `framebound/v2/demo_character.py` — original P0 demo character **Pip the courier** (hood, teal cloak, satchel on LEFT hip,
  trailing scarf, brass compass+buckle; hand-set keyframe tables, not a sine loop): run 8, jump 6, attack 6, idle 4
  (idle_0 == idle_2 by design), 3 transitions (idle↔run, run→attack), identity/style reference sheets. 24 presented
  samples from 22 independent drawings (reported separately, never conflated).
- `framebound/v2/demo_wp6.py` + `demo --profile wp6 --offline` — full workflow on the original art: project, assets
  (`source_kind=original`), asymmetric character revision, per-clip calibrated contracts (crouch-compatible jump windows,
  `flight_slots=[2,3,4]`, declared `occluded_slots=[2,3,4]` for the cloak-covered buckle), evaluations (run/jump/attack/idle
  all `pass`; jump `partial` coverage with occlusion disclosed), departure-preserving interruption checks at 7 run ticks,
  recorded provider attempt (`not_configured`, nothing fabricated), review packet + exact-revision approval, export snapshot.
- Honest calibration trail (bounds never loosened): per-clip span calibration; jump-local reviewed windows; occlusion as
  `NOT_APPLICABLE` with reason + `required=False` so the gate honors intentional exemptions without vacuous passes; status
  logic now excludes declared flight/occlusion from the required gate but still fails closed on zero measurements.
- Authority boundaries added: `CharacterRevision.asymmetry`; `register_candidate` rejects `mirror` recipes for asymmetric
  designs (mirror stays a recorded transform) and `per-pose-fit`/`independent-fit` recipes (frozen calibration).
- Provider redaction bug fixed (`image.submit` redacts structurally instead of string-replacing empty bytes).
- Benchmark now reports cold + warm (200×256² core raster: ~3.7 s cold / ~3.9 s warm on this machine; excludes providers/video).
- `tests/test_v2_demo.py` (7 tests): counts, transitions, badges + unsent ledger, interruption math vs `select_slot`,
  mirror/fit prohibitions, decision bound to exact revision. Screenshots inspected: Pip reads as a coherent hooded courier
  (scarf/satchel/compass visible; apex vs contact distinct).

### Actual commands/results (2026-10-27, Dublin)

- `python -m pytest tests/ -q` → `64 passed` (13 v1 + 11 WP1 + 14 WP2 + 14 WP3 + 2 WP4 + 3 WP5 + 7 WP6).
- `python -m framebound demo --profile wp6 --offline --out /tmp/fb-wp6` → run/jump/attack/idle all pass;
  provider `not_configured`; badge `[replay/procedural-original]` shown in packet intent in the desk.
- Live claim status: NO live Muse Image/Spark/SAM output (no credentials) — demo is replay/procedural, badged as such
  everywhere it appears. Live spike remains the release blocker (see WP7).

### Artifacts / limitations / next

- Artifacts: character author + demo + tests in-repo; `/tmp/fb-wp6` + `/tmp/wp6.json` outside repo (not committed).
- Limitations: no live provider evidence; second facing not authored (mirror prohibited by design — correct per plan);
  compare view + video/contact-sheet preview derivatives deferred to WP7 polish; no engine adapters (P1, out of scope).
- Next: WP7 release + submission (clean-clone docs, local verify script, video, demo package, portal requirements,
  submission receipt by the entrant).

## Prior: WP5 — portable training snapshots (merged as PR #8) — portable training snapshots (done on branch `codex/wp5-training-snapshots`, 2026-10-27)

Acceptance gate: moved snapshot loads with standard loaders; labels/preferences checked; hashes and duration match;
exclusions visible. All pass.

### Delivered

- `framebound/v2/exports/snapshot.py` — frozen explicit selection (revision IDs + their evaluations at export time);
  COCO (`images` + `annotations`: bbox from silhouette, RLE via pycocotools, `mask.encode`);
  HF imagefolder (`data/*.png` + `metadata.jsonl`: character/clip/slot/hold/phase, technical status, issue codes,
  human decision, metrics, `label_origin`, derivation recipe, source drawing, split); `preferences.jsonl` (prompt,
  conditioning, chosen+revision, rejected+revision, named issue + reason); `temporal.jsonl` (frames, holds, loop,
  duration ticks, evaluation id); dataset card (`hf/README.md` with label semantics); `manifest.json` (files+hashes,
  policy, schemas, dep lock `export-validation-1`, exclusions with reasons, counts).
- Honest labels: `human-approved` (pass + approval event for the EXACT revision), `weak-negative` (failed frames, never
  positives), `procedural-test` (fixtures: regressions/demos; excluded from positives by default, opt-in only with labels
  intact), `derived` (recipe recorded). Preference pairs require an approved PASSING descendant fix for the same slot —
  otherwise withheld with reason. Split leakage (same source drawing in train+test): `strict` fails, default excludes
  test frames with reason. Rights outside policy excluded with reason.
- `framebound/v2/exports/validate.py` — rehashes every file; COCO loads via real `pycocotools` API + mask round-trip
  (decode→encode area equality); imagefolder loads via real `datasets.load_dataset`; preferences resolve + name real
  issues; durations equal hold sums; splits disjoint. Returns `{ok, issues, counts, exclusions, loaders}`.
- CLI: `export --project --snapshot --out --revisions [--policy]` + `dataset-validate --snapshot` (exit 1 on failure).
- Provenance fix (this package): v2 tests now import synthetic fixtures with `source_kind="procedural"` — earlier
  tests imported them as `original`, which would have mislabeled fixtures as originals.
- `tests/test_v2_export.py` (3 tests): full round-trip after `shutil.move` (COCO + datasets + prefs + durations);
  strict split raises; default exclusions visible + every metadata row carries `label_origin`.
- Pinned: `datasets>=3,<4`, `pycocotools>=2.0.8` in `export-validation` extra. Env note: pyenv 3.11.4 lacks `_lzma`;
  validation shims `lzma` in-test only (`open` raises if xz is ever actually used — imagefolder PNGs never touch it);
  COCO path unshimmed. `dep_lock_id` is the literal `export-validation-1` until lockfiles land in WP7.

### Actual commands/results (2026-10-27, Dublin)

- `python -m pytest tests/ -q` → `57 passed` (13 v1 + 11 WP1 + 14 WP2 + 14 WP3 + 2 WP4 + 3 WP5).
- Manual: `export` → exclusions list split-leakage + procedural-positive gates; `dataset-validate` on moved snapshot →
  `ok: true` with real loader counts.

### Artifacts / limitations / next

- Artifacts: exports code + tests in-repo; snapshots under `/tmp` (not committed).
- Limitations: evaluations snapshotted by latest-at-export (documented; a fixed DB snapshot is WP7 hardening); brief
  prompts reconstructed minimally (full brief bundles persist via WP3 ledger, not yet linked into prefs — recorded gap);
  no held-out critic experiment (P1, correctly out of scope).
- Next: WP6 genuine character demonstration (original run/jump/attack, transitions, provider ledger, stress benchmark).

## Prior: WP3 — tools, providers and bounded loop (merged as PR #6) — tools, providers and bounded loop (merged as PR #6) — tools, providers and bounded loop (done on branch `codex/wp3-tools-providers-loop`, 2026-10-27)

Acceptance gate: real client MCP handshake; references reach image model; outputs stored; masks decoded if available;
bounded repair and no-regression policy work. All pass.

### Delivered

- `framebound/v2/services/` — one shared application layer (CLI/MCP transports never reimplement policy):
  projects, assets, contracts (missing-authority inventory), clips (create + persisted evaluate + candidate registration as child
  revisions with frozen recipes; per-pose-fit blocked), repair (3-attempt budget, no-progress signatures, regression/coverage selection,
  subjective `awaiting_human_comparison` path), packets (stale-evidence rejection), jobs (idempotent submit/get/cancel),
  corrections (open/claim with lease expiry). `authz.require_reviewer`: ALL review writes reviewer-only (orchestrator attempts → 403-class
  `forbidden`); `errors` carry stable codes (`invalid_input`, `stale_revision`, `unsupported`, `rate_limited`, `provider_timeout`,
  `cancelled`, `forbidden`) with retryability.
- `framebound/v2/briefs/compiler.py` — typed bundles with conditioning SHA-256: approved identity + style (approval records required,
  rejected candidates forbidden), independent phase authority (frame never its own guide), neighbor context from accepted revisions only,
  preservation rules + forbidden list. Sole-reference and rejected-input briefs raise `invalid_input`.
- `framebound/v2/providers/` — `base.discover` (`not_configured` without key, never invents success) + bounded transient retry with backoff;
  `image` builds reference-conditioned Responses requests carrying ACTUAL role-labeled reference bytes/hashes (v1's text-only gap closed),
  persists redacted request artifacts, returns `not_configured` offline; `spark` advisory critique (never gates); `sam` Responses-shape builder +
  special-token mask decoder with explicit outcomes (no_match/corrupt/misaligned/empty/full/mask); alpha fallback stays labeled
  `offline-alpha`, never SAM. `ledger` persists every request/response artifact + cost; estimates marked.
- `framebound/v2/orchestration/loop.py` — `BoundedLoop`: stops at `awaiting_review`, 3-attempt budget per target, no-progress signatures stop
  blind retry, cost ceiling field, no concurrent same-revision mutation by construction.
- `framebound/v2/mcp/server.py` — official MCP SDK 2.3.0 (`MCPServer`, `run_stdio_async`), 14 tools over the same service functions;
  CLI `v2-mcp --project` serves stdio. `tests/test_v2_loop.py::RealMCPHandshake` runs a REAL client (`stdio_client` + `ClientSession`)
  in-subprocess: lists tools, calls `doctor` + `project_get`.
- CLI: `asset-import`, `contract-propose`, `clip-create`, `clip-evaluate`, `brief-compile`, `job-submit`, `job-get`,
  `candidate-register`, `packet-create`, `corrections-list` (v2 repair flows via MCP `repair_plan`/`repair_evaluate`; v1 names untouched).
- Pinned: `mcp==2.3.0` (exercised), `Pillow>=13,<14`, `pydantic>=2.12,<3`, `numpy`, `fastapi`, `uvicorn`; `datasets`+`pycocotools` in
  `export-validation` extra (WP5). `dep_lock_id` still `dev-no-lock` until WP5 lockfile.
- `tests/test_v2_loop.py` (14 tests): authz split, brief authority ×3, provider honesty ×4 (incl. SAM outcome matrix), repair budget/
  regression/subjective/no-progress, loop stop/budget, live MCP handshake.

### Actual commands/results (2026-10-27, Dublin; `python` 3.11.4)

- `python -m pytest tests/ -q` → `52 passed` (13 v1 + 11 WP1 + 14 WP2 + 14 WP3).
- Live provider evidence: still blocked (no `MODEL_API_KEY`); `generation_submit` returns persisted `not_configured` artifact —
  recorded as capability result, not success. SAM decode paths unit-tested; live mask spike needs key (WP6).

### Artifacts / limitations / next

- Artifacts: service/provider/orchestration/mcp code in-repo; offline request fixtures already in `fixtures/provider-spike/`.
- Limitations: no HTTP API + event stream yet (WP4); no review desk UI (WP4); export snapshots (WP5); no genuine character art (WP6);
  `brief_compile` MCP/CLI approvals currently `imported` (explicit human approval events arrive with WP4 review writes).
- Next: WP4 review desk + human round-trip (FastAPI routes, React desk, packet renderer, ROI/range issues, correction leases,
  before/after, restart journey).

## Prior: WP4 — review desk and human round-trip (merged as PR #7) — review desk and human round-trip (done on branch `codex/wp4-review-desk`, 2026-10-27)

Acceptance gate: full browser restart journey passes; human decisions cannot be written by model tools;
subjective correction supported. All pass.

### Delivered

- `framebound/v2/api/app.py` — FastAPI review API (12 routes) over the same services: project/packets/packet
  (frozen revision+evaluation+frames+contract), asset-by-ID PNG (no path traversal; 410 on missing blob),
  corrections queue (model-readable), reviewer-only issue/decision/resolve writes (403 for orchestrator via service
  authz), claim/submit (orchestrator OK; submit builds child revision + evaluation + comparison packet and moves the
  task to `awaiting_comparison`), SSE `/api/events`. 409 `stale_revision` on outdated decision views; 404 unknown IDs.
  Static mount serves `web/dist` last so `/` never shadows `/api`. CLI: `serve --project DIR [--host 127.0.0.1]`
  (v1 `--contract` path untouched).
- `web/` — React 18 + TS + Vite desk: inbox (packets, blockers, coverage gaps), packet view (intent strip, 288px stage,
  true-speed rAF playback from integer holds with paint counter, frame strip/timeline, findings + coverage, ROI drag →
  native px, frame-range issues, Approve/Reject/Needs-work bound to the exact revision), compare view (side/blink/diff
  at identical timing), corrections queue. OpenAPI generated client types (`src/api-types.ts` via openapi-typescript 7;
  `npm run typecheck` + `npm run build` green).
- Playback honesty: presentation speed never rewrites holds; tick-step on exact integers; dropped paints observable via counter.
- `tests/test_v2_desk.py` (2 tests): reviewer marks ROI issue 3–5 → open task in model queue; orchestrator decision → 403;
  stale `expected_revision_id` → 409; NEW app instance over same dir (restart) preserves issue/task/media byte-identical;
  claim → submit replacement → comparison packet with passing evaluation; unrelated approval leaves task open;
  explicit `resolve_issue` closes it; clean-baseline subjective issue path.
- `web/e2e/journey.mjs` + Playwright chromium headless shell: inbox → packet → paints advance 24→46 → ROI drag →
  issue submit → correction task → reload → packet+desk reloaded. Exit 0, 4 screenshots in `/tmp/fb-e2e-shots` (outside repo).

### Actual commands/results (2026-10-27, Dublin)

- `python -m pytest tests/ -q` → `54 passed` (13 v1 + 11 WP1 + 14 WP2 + 14 WP3 + 2 WP4).
- `npm run typecheck` → clean; `npm run build` → `dist/` 156K.
- Browser E2E (chromium headless shell, API+desk on :8766): `{"inbox": 1, "paints_advance": "paints 24 → 46",
  "issue": "correction task task-evt-…", "after_reload": "packet + desk reloaded"}`. Screenshots inspected: stage,
  findings, strip, decisions render without overlap.

### Artifacts / limitations / next

- Artifacts: API + desk + e2e script in-repo; screenshots + server log + seeded projects in `/tmp` (not committed).
  `package-lock.json` intentionally committed for pinned frontend deps.
- Limitations: single local reviewer identity (`X-Actor-Type` header; no real auth — local-only, hosted demo must be
  read-only replay per plan); compare view loads revision IDs without packet media cross-check (WP5 export hardening);
  no export button yet (WP5); no video/contact-sheet preview derivatives yet (WP6 demo needs).
- Next: WP5 portable training snapshots (exports, loaders, split/rights policies, dataset card, loader smoke tests).

## Prior: WP2 — canonical media and verification (merged as PR #5) — canonical media and verification (merged as PR #5) — canonical media and verification (done on branch `codex/wp2-media-checks`, 2026-10-27)

Acceptance gate: clean and negative fixtures behave correctly; per-tick sliding and loop/one-shot cases tested; stale evidence rejected. All pass.

### Delivered

- `framebound/v2/media/` — canonical import (sRGB straight-alpha RGBA8, transparent-RGB normalized once at import, byte+pixel hashes,
  bomb/malformed/traversal guards), frozen registration (uniform family scale, integer translation default, recorded recipe, no per-pose fit),
  integer timeline (`select_slot` half-open intervals, `render_trace`, 10k-loop drift test), diagnostic overlays (review derivatives only).
- `framebound/v2/checks/` — registry with declared applicability/inputs/units/limits/blind-spots; raster primitives (alpha, silhouette,
  occupancy descriptor + signed horizontal-asymmetry term, quantized palette, feature points); 14 registered checks:
  native_registration, silhouette area/width/height, phase_correspondence (adjacent-slot exclusion: smooth motion is not ambiguity),
  declared_contacts, world_sliding (per-tick planted drift; catches held-drawing slide that static windows miss),
  visible_span, local_pulse, appearance_palette, locked_cadence, loop_seam (seam-vs-own-steps ratio, never identical-pose demand),
  repair_protection (exact RGBA outside support + protected regions), provenance_coverage.
- `framebound/v2/checks/evaluate.py` — evidence manifest (contract, char revision, input hashes, refs, recipes, timeline, analyzer `v2-checks-1`,
  dep lock, settings, schemas; no timestamps) → `evidence_manifest_sha256`; fail/incomplete/error/pass + complete/partial/unsupported.
- `framebound/v2/checks/fixtures.py` — independent Pillow procedural runner (8 genuinely distinct poses: 2x-frequency bob + offset arm pump),
  faults: torso pulse, wrong phase, blank, resized canvas, clipped toe, palette recolor, missing feature. Labeled test-only, never accepted art.
- Calibration honesty (no loosened bounds): asymmetry term + adjacency exclusion + seam ratio came from diagnosing genuine aliasing;
  palette `max_drift` 0.06 frozen between clean 0.0 and full-shirt recolor 0.109; palette fault fixture re-phased to isolate color.
- CLI: `demo --profile v2 --offline`, `benchmark --fixture stress-200`. v1 commands untouched.
- `tests/test_v2_verify.py` (14 tests): clean pass/complete; pulse caught while height constant; wrong phase; blank→error; resized→registration fail;
  missing feature→unmeasured + never pass; empty refs→incomplete + coverage gap; static-pass/world-slide-fail pair; hold boundaries + 10k loops;
  one-shot seam N/A; mirror double-flip + ROI remap; protection in/outside support; stale evidence hash change; repair no-regression.

### Actual commands/results (2026-10-27, Dublin; `python` 3.11.4, Pillow 13.0.0)

- `python -m pytest tests/ -q` → `38 passed` (13 v1 + 11 WP1 + 14 WP2).
- `python -m framebound demo --profile v2 --offline --out /tmp/fb-v2-demo` → clean `pass`/complete, faulty `fail`
  (`look`, `phase`, `torso_span`), repair selected, ~16 ms/frame at 64x64 core raster (not a P0 claim).
- `python -m framebound benchmark` → 200 frames at 256x256 in ~4.1 s (~20.7 ms/frame core raster, excludes providers/video).

### Artifacts / limitations / next

- Artifacts: fixtures generated under `/tmp` (outside repo); `framebound/v2/media`, `checks`, `demo` in-repo.
- Limitations: references keyed in-memory (no asset-ID resolution yet — WP3 services); no annotation/mask revisions wired (alpha only, SAM pending);
  no persisted evaluation store writes from CLI; dependency lock-in is `dev-no-lock` until WP3 pins.
- Next: WP3 tools, providers, bounded loop (services, MCP SDK handshake, reference-conditioned image adapter, SAM decode, 3-attempt repair policy).

## Prior: WP0 — baseline and integration spike (merged to `main` as PR #3) — baseline and integration spike (in progress, branch `codex/wp0-baseline-spike`)

Acceptance gate: existing tests recorded; actual available endpoints/outputs established or explicit access blocker documented; no fabricated live claim.

### Baseline (commit `4bfd799`, 2026-10-27, Europe/Dublin)

- Command: `python -m unittest discover -s tests` → `Ran 13 tests ... OK` (3.6 s).
- Command: `python -m framebound demo --out /tmp/fb-wp0-baseline` → clean `pass`, faulty `fail` with 5 error codes
  (`appearance_palette_drift`, `missing_support_contact`, `phase_correspondence`, `surface_span_drift`, `surface_span_pulse`);
  `repair_selected_for_review: true`; ~34 ms/frame on this machine (prototype pure-Python 96×96 canvas, not a P0 result).
- Prototype layout: `framebound/` v1 modules (`checks`, `audit`, `brief`, `repair`, `review`, `dataset`, `demo`, `meta_api`, `pngcodec`, `mcp_server`, `cli`)
  + `tests/test_framebound.py` (13 tests) + `docs/{DESIGN,HACKATHON,MODEL_TOOLS,DATASET}.md`. No `framebound/v2/`, no `schemas/`, no `web/`, no SQLite store.
- `.gitignore` already excludes `build/`, `*.db`, `dataset-export/` — no checked-in user data found; repo tree has no `*.png` sources, no sqlite/db files.
- Environment: Python 3.15.1; `pydantic 2.12.5`, `numpy 2.4.2`, `fastapi 0.128.7`, `pytest 9.0.2` present.
  Missing for v2 (to pin in WP1/WP3): `pillow`, `uvicorn`, official MCP SDK, `pycocotools`, `datasets`, `ffprobe`/`ffmpeg`, React/Vite toolchain.
  No `MODEL_API_KEY` / `META_API_KEY` in environment — live provider calls are blocked; offline behavior only.

### Reusable original material (all v1, must be re-tested independently before carry-over)

- `framebound/knowledge.json` — failure taxonomy vocabulary (phase-order, clock-drift, body-volume, size-pulse, ...). Retain as aliased check-spec source only.
- `framebound/demo.py` + procedural runner — deterministic clean/fault/repair synthetic regressions; candidate for `tests/fixtures/` with explicit provenance labels.
- `framebound/checks.py` pure calculations (silhouette, palette, components, phase descriptors, support spans) — salvage candidates after removing self-reference/defaults.
- `framebound/brief.py` role + hash binding idea — keep concept, replace path authority with asset IDs.
- `framebound/audit.py` reproducibility principle — keep, replace partial hashing with full evaluation manifest.
- `framebound/repair.py` protected-pixel check — keep concept, replace error-count objective with target/no-regression policy.
- Do NOT carry: `pngcodec.py` (production media), `meta_api.py` adapters (unverified), `review.py` slot model, `dataset.py` exporter, dependency-free constraint, `mcp_server.py` hand-rolled framing.

### Integration spike outcome (2026-10-27, no key, offline only)

- Meta current overview documents `https://api.meta.ai/v1`, bearer auth via `MODEL_API_KEY`, Spark `muse-spark-1.3`, Muse Image `muse-image-1.0`, SAM `sam-3.1`. Details in `docs/PROVIDER_CONTRACTS.md`.
- v1 `meta_api.py` gaps confirmed by code inspection (not live-tested): image request is text-only (`prompt` + `size`, no reference pixels);
  SAM sends a local path string to `/chat/completions` and never decodes special-token masks; generated bytes are never materialized/verified.
  No live spike possible without credentials — recorded as explicit access blocker, not as success.
- Redacted offline fixtures saved under `fixtures/provider-spike/` (request shapes only, key redacted, `sent: false`).
- Dependency decision (preliminary, to pin in WP1): Pillow+NumPy raster, Pydantic v2 schemas, FastAPI/Uvicorn HTTP, SQLite+WAL, official MCP SDK over stdio,
  React+TS+Vite desk with OpenAPI-generated types, FFmpeg preview derivatives, `pycocotools`+`datasets` in export-validation extra, pytest + browser journey.

### Hackathon requirements (authenticated portal NOT accessible this pass)

- Public event page confirms: Indie developer track (creativity, technical ambition, working execution), Build for Your World theme,
  Muse Spark / Muse Wonder / Muse Image / SAM 3.1 / Meta open-weight models listed, submissions 4 Nov 2026 9:00 PM ET
  (= 5 Nov 02:00 Europe/Dublin), judging 4–8 Nov, finals 9 Nov. Internal target: 4 Nov 18:00 Dublin.
- Details/rules pages redirect to login; scoring weights, video length, hosting/code rules, reuse disclosure, submission fields, model-use minimum
  all UNVERIFIED. Prototype's 30/25/20/25 rubric must not be treated as verified. Recorded in `docs/SUBMISSION_REQUIREMENTS.md` with check date.
- Next: entrant must re-check with authenticated session before disclosure/publish/submit decisions.

### Artifacts this package

- `docs/IMPLEMENTATION_STATUS.md` (this file), `docs/SUBMISSION_REQUIREMENTS.md`, `docs/PROVIDER_CONTRACTS.md`
- `fixtures/provider-spike/{spark-critique,image-generation,image-edit,sam-segmentation}.json` (offline request shapes, redacted)
- Baseline `/tmp/fb-wp0-baseline` (outside repo, not committed)

### Limitations

- No live Meta call made (no key). No authenticated portal check. No v2 code yet. Performance numbers above are v1 prototype only.

### Next exact step

- Finish WP0: commit docs+fixtures on `codex/wp0-baseline-spike`, open remote PR, merge to `main`, then start WP1 (`framebound/v2/domain`, `storage`, `schemas`, migration dry-run).
