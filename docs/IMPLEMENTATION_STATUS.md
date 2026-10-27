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

## Current package: WP5 — portable training snapshots (done on branch `codex/wp5-training-snapshots`, 2026-10-27)

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
