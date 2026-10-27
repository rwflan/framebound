# Framebound — Implementation Status (remediation pass)

Remediation authority: external `Framebound-Remediation-Plan.txt` (kept outside the repo; never committed).
Baseline: `b680d84` (audited main, 2026-10-27). `main` has not advanced since the audit; no delta to adapt to.
Prior ledger entries below are historical. The earlier "64 passing tests" and "engineering complete except
for entrant actions" claims are NOT accepted as proof; each remediation package re-proves its gate.

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
