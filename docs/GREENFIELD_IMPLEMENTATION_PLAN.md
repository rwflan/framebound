# Framebound: greenfield implementation plan

Implementation handoff for Muse Spark 1.3 · 27 October 2026

**Status:** proposed design. This document specifies the replacement product; it does not claim these capabilities exist. The checked-in Python package is an initial prototype. Use this plan as the authority for future implementation, and keep implementation status separate from design intent.

## 1. Decision and product contract

Build a model-facing framework for authoring, checking, repairing, reviewing, and exporting consistent 2D animation. Build a web application as its persistent review surface. The orchestrating model uses typed tools; the person watches evidence, marks problems, and makes visual decisions.

Start a new core behind explicit versioned schemas. Preserve useful algorithms, original procedural fixtures, and the failure taxonomy from the prototype after testing them independently. Do not preserve the dependency-free constraint, homemade media stack, current persistence model, or speculative provider adapters just to avoid rewriting them. Do not delete existing user files, historical evidence, or the working prototype before the replacement passes migration gates.

The framework should make constraints executable before generation, catch measurable regressions before requesting human attention, and retain useful supervision from every attempt. Its long-term success is that models trained on its outputs require less correction and eventually less external enforcement.

“Real time” has two distinct meanings here:

1. **Required:** animation intended for interactive playback; exact timing, contacts, action transitions, and interruption behavior must work at runtime speeds. Local checking should be incremental and responsive while the model works.
2. **Future capability:** generation of unseen frames during gameplay. Do not promise this in the hackathon. Remote image generation and multimodal critique sit outside the playback loop. Ship verified cached animation plus a small playback harness first.

Use one illustrated character in a side-view action setting for the first complete workflow. The schema must support other subjects, styles, and views without requiring a human skeleton. Pixel art and illustrated raster art need different rendering and tolerance profiles. This is a reusable framework demonstrated on a narrow case, rather than a game-specific art script.

### Required user journey

The developer tells a model: “Create this character’s run, jump, and attack using these approved references.” The model proposes a constraint contract, obtains reference approval where necessary, generates candidates, runs preflight, inspects precise failures, and repairs within a bounded budget. The web desk receives a curated packet. The developer watches true-speed playback, marks a torso pulse over several frames, and submits a correction. The model receives the exact affected revision, attempts a bounded fix, and returns a before/after packet. The developer’s decision becomes a versioned label. A portable export includes source media, conditioning, measurements, defects, repairs, timing, and decisions.

### Non-negotiable invariants

- Native scale, canvas, coordinate system, timing, approved references, and permitted transformations are explicit contracts.
- A candidate cannot become its own identity or motion authority. Original references remain available throughout generation and repair.
- A detector’s proposal is distinct from an approved annotation. A model’s critique is distinct from measured evidence.
- Technical eligibility, measurement coverage, human acceptance, and publication state are separate values.
- Missing evidence cannot become a pass. Unknown physical anatomy remains unknown.
- Changing pixels, masks, timing, registration, contract, or analyzer invalidates dependent evidence.
- A model may propose contract changes but cannot silently loosen frozen bounds, replace approved masters, or write human decisions.
- Every review action addresses an immutable revision. Approval never follows a frame index onto different pixels.
- Original media and events are immutable. Repairs create candidates and child revisions.
- Retained failures are valid negative evidence, not automatically permitted generation references or positive training targets.
- Exports carry label origin and lineage. Procedural samples, derived frames, and human-approved independent drawings are distinguishable.

## 2. Hackathon constraints and positioning

The verified public event page identifies the **Indie developer** track with creativity, technical ambition, and working execution as its focus. **Build for Your World** asks for a problem the builder knows firsthand. Position Framebound around the practical burden of checking a solo developer’s animation library, with a concrete demonstration of reduced repetitive review. The event lists Muse Spark, Muse Wonder, Muse Image, SAM 3.1, and Meta open-weight models among its tools. See the [official event page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon).

The public schedule lists submissions on **4 November 2026 at 9:00 PM ET**, equivalent to **5 November at 02:00 in Europe/Dublin**; judging runs 4–8 November and finals are 9 November. Set an internal submission target of **4 November at 18:00 Dublin time** to leave time for packaging and portal problems. Recheck the [official schedule](https://cerebralvalley.ai/e/meta-ai-developer-hackathon) before submitting.

The supplied [details page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details) redirected to login during research. The public waiver also did not expose readable rules. Accordingly, these items remain **unverified**: final scoring weights, demo-video length, required hosting/public-code arrangements, reuse/disclosure rules for pre-existing work, exact submission fields, and any required model-use minimum. The prototype’s 30/25/20/25 rubric must not be treated as verified. Its equal-weight application-selection criteria are also not the final project rubric.

At implementation start, inspect the participant’s authenticated rules and submission portal, or obtain the missing requirements from the organizer. Record the outcome in `docs/SUBMISSION_REQUIREMENTS.md`, using source links and the date checked. Do not let this prevent independent engineering work. Resolve it before choosing what to disclose, publish, or submit. Preserve the honest distinction between pre-existing foundation and work completed during the event; do not infer permission to reuse material from a public marketing page.

### What the demonstration must establish

| Claim | Concrete evidence to produce |
|---|---|
| Solves an indie workflow problem | One character, multiple actions, defects that are visible in playback, and a marked issue that returns as a correction task |
| Uses Meta meaningfully | A recorded Spark tool loop, reference-conditioned Muse Image output, and actual SAM segmentation where applicable; display provider provenance |
| Checks more than style | Catch a local size pulse, wrong phase/contact, timing error, and collateral repair |
| Saves review effort | Count machine-detected defects, unresolved coverage, human packets, and time spent; label exploratory measurements honestly |
| Produces reusable training material | Load the export in standard libraries; show original conditioning, reliable labels, and a repair pair with valid provenance |
| Works under API failure | A visibly labeled replay of a genuine recorded run plus a procedural offline regression demo |

These are product demonstration targets, not claims about mandatory event submission requirements. A fully live run is preferred; replay must never be represented as live model execution.

## 3. Existing-project assessment and carry-over

The initial repository contains the Python package, documentation, procedural demo builder, failure taxonomy, and thirteen unit tests. No checked-in real-character corpus or production media store was found. All thirteen tests passed during this planning pass. That is evidence about the prototype’s current tests, not validation of provider interoperability, dataset compatibility, artistic quality, or performance.

| Existing material | Decision | Required treatment |
|---|---|---|
| `framebound/knowledge.json` | Retain the general failure vocabulary | Convert rules into versioned check specifications with applicability, limitations, fixtures, and repair hints; preserve IDs through an alias map |
| `checks.py` | Salvage selected pure calculations | Re-test silhouette, palette, connected components, phase descriptors, and support spans; remove implicit self-reference and undocumented global defaults |
| `demo.py`, useful test cases | Retain as synthetic regressions | Give each original procedural asset explicit provenance; separate deliberately bad outputs from accepted art |
| `brief.py` | Preserve reference roles and hash binding | Replace path-based authority and optional hashes with verified asset IDs, approved roles, and complete typed conditioning |
| `audit.py` | Preserve reproducibility principle | Replace partial hash collection with a complete evaluation manifest including annotation, registration, mask, dependency, and settings versions |
| `repair.py` | Preserve protected-pixel checking | Replace global error-count improvement with explicit target resolution, no regressions, and separate subjective-correction handling |
| `review.py` | Replace implementation | Its decisions and issues address slots, and a decision updates issues for that slot together. Add revision-bound events, separate issue resolution, spatial/time annotations, and durable packets |
| `dataset.py` | Replace exporter | Current preferences can choose a phase reference without an explicit human comparison; media paths are not fully portable; frame status can omit clip-wide failures; independent loader checks are absent |
| `meta_api.py` | Replace adapters | Text-only image requests omit bound reference pixels; SAM receives a local path via a text endpoint; generated bytes are not materialized and verified. None of this proves a working live path |
| `pngcodec.py` | Retire from production media handling | Use maintained image tooling with explicit color and alpha policies; preserve small algorithm fixtures if useful |
| `mcp_server.py`, CLI | Preserve the tool-first direction | Use a maintained MCP SDK and one application-service layer shared by CLI, API, and MCP |
| Existing docs | Keep as prototype history until replaced | Add clear links to the replacement plan; rewrite them against delivered behavior as milestones land |

Do not carry over undocumented timing or performance claims. Re-measure on the actual implementation and state hardware, resolution, workload, cache state, and included operations.

### Migration procedure

1. Record the current commit, run the existing tests, and inventory local project/media/database directories without mutating them.
2. Develop on a dedicated branch. Keep the v1 entry point available while v2 is built in `framebound/v2/`.
3. Implement an idempotent `framebound migrate-v1 --dry-run` that reports importable media, missing references, malformed contracts, unresolved rights, and old review decisions.
4. Import media by content hash. Convert only fields whose meaning is known. Historical slot-only decisions remain untrusted historical events unless a matching media revision can be proven; do not grant new approvals.
5. Original files and the old database remain intact. Produce a migration receipt and backup location, then test opening the imported project after restart.
6. Switch the default entry point only after the complete offline workflow and migration checks pass. Remove obsolete internals in a later PR; the Git history remains recoverable.

## 4. Scope and delivery tiers

### P0: hackathon complete workflow

- One local project with one original character, approved identity/style references, and one complete run cycle of 8–12 independently authored poses.
- Basic jump and attack clips of 4–8 poses each; one explicitly declared facing initially. A second facing is only an exact mirror if the design permits it.
- Three explicit transitions: idle→run, run→idle, and run→attack. An interruption test must preserve the displayed departure sample and follow the declared entry rule.
- Versioned contracts, media registration, deterministic checks, an explicit coverage matrix, and structured reports.
- A bounded Spark orchestration loop with a real reference-conditioned Muse Image adapter, plus SAM mask ingestion and provenance for at least one representative case if access is available.
- Native playback, still images, video review, contact sheets, before/after comparison, and durable review packets in the web desk.
- Human ROI/frame-range issues → correction queue → model attempt → new packet → human decision, across server/browser restarts.
- Standard image/segmentation exports, validated temporal records, correction/preference records with honest label semantics, a dataset card, and actual loader smoke tests.
- Original procedural clean/fault/repair cases and a 200-frame stress fixture. Report independent pose count separately from presented sample count.
- A recorded genuine model run and a clean-clone setup path.

Minimum live-provider evidence is Spark orchestration plus a persisted Muse Image result with actual reference inputs. SAM failure must be visible as unsupported/failed coverage, never replaced by alpha while claiming SAM use. If SAM access blocks the deadline, ship the adapter boundary and alpha-based checks honestly and narrow the demo claim.

### P1: after the complete workflow works

Multi-character libraries; eight-direction profiles; richer pose/part annotations; OpenRaster/layer kit import; sprite-sheet/atlas round-trip; engine trace adapters; contact/attachment constraints on props; richer video input; a small held-out critic-training experiment; more styles and non-humanoid fixtures.

### P2: longer-term research

Streaming runtime enforcement, learned correspondence/identity critics, model-assisted motion proposals, active learning, large datasets, and provider-specific fine-tuning integrations. Evaluate these against measured review reduction and held-out generalization.

Do not build a drawing editor, timeline authoring suite, general game engine, hosted multi-tenant platform, distributed task cluster, or bespoke model trainer for P0. Keep dependencies useful and few; do not invent a generic plugin platform before a second implementation needs it.

## 5. Architecture

Use a local-first Python service with a TypeScript review client. Maintain one set of application services; transports and UI adapters cannot reimplement policy.

```text
Spark or another orchestrator
        │ typed tools: MCP / CLI / HTTP
        ▼
Application services ── immutable assets + revisions + events ── SQLite
        │                         │                              + local blobs
        ├── contract + brief compiler
        ├── provider jobs: image / segmentation / critique
        ├── registration + verification + bounded repair
        ├── review packets + correction queue
        └── export + independent validation
                         │
                 HTTP API + event stream
                         │
                 persistent web review desk
```

### Concrete stack

- Python 3.11+; Pydantic for strict models and JSON Schema; NumPy/Pillow for raster work; FastAPI/Uvicorn for HTTP; SQLite with migrations and WAL for metadata.
- A persisted `jobs` table and one worker process. Job leases, cancellation, restart recovery, and a bounded provider concurrency setting are enough initially. Avoid Redis/Celery in P0.
- Official Python MCP SDK for stdio, with the same schemas/service functions as HTTP. Pin a tested release and exercise a real client handshake. The [MCP SDK catalog](https://modelcontextprotocol.io/docs/sdk) identifies maintained SDKs; use it instead of implementing protocol framing from memory.
- React, TypeScript, and Vite for the desk. Generate client types from the service’s OpenAPI schema. Use CSS tokens and a small component set; no UI framework is required.
- FFmpeg/ffprobe for preview video and timestamp inspection. Preserve RGBA PNG sequences as the authoritative drawings. Video is a review derivative.
- `pycocotools` and Hugging Face `datasets` in an export-validation extra. Pin dependency versions in lockfiles after compatibility checks.
- pytest for service/core tests and browser automation for the correction/restart journey. Make current versions explicit when implementing; no unverified version numbers in this plan.

### Target layout

```text
framebound/v2/
  domain/          # models, state transitions, coverage and authority policy
  services/        # common use cases; transaction boundaries
  storage/         # SQLite migrations, repositories, blob store
  media/           # import, registration, masks, timelines, rendering
  checks/          # registry and deterministic check implementations
  briefs/          # generation/repair conditioning compiler
  providers/       # Meta adapters, recording/replay, capability discovery
  orchestration/   # bounded tool loop and persistent run state
  exports/         # snapshots, formats, dataset validation
  api/             # HTTP routes, event stream, review-only permissions
  mcp/             # SDK adapter
  cli.py
web/               # React review desk; generated API types
schemas/           # exported versioned schemas and example instances
examples/original-character/
tests/{unit,integration,fixtures}/
tests/e2e/
docs/{IMPLEMENTATION_STATUS,SUBMISSION_REQUIREMENTS,PROVIDER_CONTRACTS}.md
```

Store runtime data outside source code in a configured project directory:

```text
project/
  framebound.sqlite3
  blobs/sha256/<prefix>/<digest>
  exports/<snapshot-id>/
  backups/
```

Blob paths are internal. External tools use asset IDs. Reject arbitrary server file paths, traversal, invalid media, excessive pixel counts, and out-of-project references. Bind localhost by default. A hosted demo can be read-only replay; any remotely exposed write/provider endpoints need authentication before use. API keys stay server-side and are absent from stored/exported request headers.

## 6. Domain model and lifecycle

### Core entities

| Entity | Essential fields and meaning |
|---|---|
| Project | ID, name, schema version, owner, creation time, rights policy |
| Asset | ID, byte hash, decoded-pixel hash when applicable, MIME, dimensions, color/alpha policy, source kind, lineage, rights, eligible reference roles |
| CharacterRevision | Identity/style reference asset IDs, approved view set, scale ruler, native canvas, palette/part definitions, asymmetry constraints, human reference approval |
| ClipContractRevision | Action intent, phases, timing, contacts, root policy, constraints, required checks, annotations, permitted transforms, reference revisions |
| ClipRevision | Contract revision, ordered frame instances, parent revision, origin run, source prompt/conditioning IDs |
| FrameInstance | Stable instance ID, asset ID, phase, hold ticks, registration ID, source-drawing ID, derivation recipe, optional part masks and anchors |
| PlaybackTrace | Exact revision, tick rate, rendered sample sequence, roots, facing, attachment transforms, action events, trace origin/version |
| AnnotationRevision | Source asset/pixel hashes, view, coordinate space, visibility, annotator type, reviewer, confidence/proposal status, supersession |
| Evaluation | Complete evidence manifest, analyzer identity, per-check results, coverage, status, metrics, overlay artifacts, dependencies |
| Attempt | Baseline revision, brief, provider request/response artifacts, candidate assets, costs, repair mask, targeted issues, result |
| ReviewPacket | Frozen revision/evaluation IDs, intent, clips/images/contact sheets/overlays, prioritized issues, unresolved coverage, comparison revision |
| ReviewEvent | Actor, decision/issue action, exact packet/revision/frame-instance or range, ROI, timestamp, supersedes-event ID |
| CorrectionTask | Source issue event, baseline revision/evidence, desired outcome, scope, claim/lease, attempts, resolution event |
| ExportSnapshot | Frozen selection, policy, schemas, dependency versions, splits, byte manifest, validation report |

Avoid making the same field mean a source drawing, a slot in a sequence, and a displayed sample. One drawing can appear several times; one frame instance can be held for several ticks. A derived sample is not an independently generated drawing.

### Separate states

```text
technical_status: pass | fail | incomplete | error
coverage_status: complete | partial | unsupported
human_acceptance: unreviewed | needs_changes | approved | rejected
publication_status: draft | candidate | released
job_status: queued | running | succeeded | failed | cancelled | needs_attention
```

Check results additionally use `pass | fail | unmeasured | not_applicable | error`. Every `unmeasured` and `not_applicable` result needs an explicit reason and applicability rule. A required unmeasured check yields `incomplete`; a violated required bound yields `fail`; corrupt input or analyzer failure yields `error`. No required checks configured means `incomplete`, not a vacuous pass. Known optional occlusion can leave technical status passing with partial coverage, visibly disclosed.

Reference approval is an explicit human action or a verified import of an existing approval. During bootstrap, a model may propose a character sheet and motion guides; the desk supports “Approve reference set” for the exact revision. A clean drawing is not required for every future phase: guides may be approved rough line art, authored pose metadata, contact schedules, or approved earlier motion. They must have independent authority. The frame under test never supplies its own expected result.

A technical pass makes a packet eligible for review; optional unresolved coverage remains prominent. Failed material can still be opened for diagnosis and rejection. An artistic approval cannot release material that fails the configured technical publication gate. Artistic approval alone does not resolve each issue. Issue resolution is a separate event tied to the replacement revision.

Correction lifecycle: `open → claimed → attempting → awaiting_comparison → resolved`, with explicit `blocked`, `cancelled`, and `reopened` events. A lease expiry returns an unfinished claim to the queue without discarding attempts. Release requires current technical eligibility, human approval for the exact revision, and no unresolved blocking issues. A rejected comparison leaves the issue open; an unrelated approval cannot close it.

### Concurrency and durability

Use revision/ETag preconditions on writes. A stale review tab or repair submission receives `409 stale_revision` with the current ID; it cannot overwrite a newer state. Review events and correction tasks commit in one transaction. API calls carry idempotency keys. Repeating a request returns the same result. After a crash, a lease expires and the worker reconciles the provider attempt before retrying; do not blindly purchase a second image after an ambiguous timeout.

Append-only events retain previous approvals and rejections. Materialized status can be rebuilt. File writes go to a temporary file, are hashed, and are atomically renamed before metadata commits; missing/corrupt blobs yield explicit errors. Export uses a fixed database snapshot, not a moving “latest” view.

## 7. Contract and coordinate conventions

Freeze one shared native canvas per character/view profile. Reference images may arrive at higher resolution: register them once using a declared ruler/anchor and one uniform source-to-native scale for that source family. Freeze and record that transform. Do not independently fit each pose to its bounding box, stretch a limb, or resize a candidate until it passes.

- Native image coordinates: origin top-left, x right, y down; pixel-edge rectangles `[left, top, right, bottom)`; point coordinates are continuous pixel coordinates with centers at `n + 0.5`.
- Each registration declares source crop, uniform scale, translation, sampling method, alpha policy, and source hash. Integer translation is the default for pixel art. Illustrated art may use declared subpixel translation with fixed resampling.
- Native-to-stage transformation is separate: mirror around the declared pivot, apply character display scale, add root translation. Define the matrix order in code and test both facings.
- Store root trajectories and units explicitly. An in-place clip has different expectations from a root-motion clip. Effects, weapons, hair, and cloth must not silently determine body scale.
- Frame holds are positive integers at a declared tick rate, initially 60 Hz. Slot `i` covers the half-open interval `[sum(holds[:i]), sum(holds[:i+1]))`. Loop modulo applies only to looped clips; one-shots stop/transition as declared.
- An annotation identifies its coordinate space and transform. ROIs drawn in a zoomed viewer map back to native pixels; letterboxing, device pixel ratio, and mirroring must be accounted for.

Canonical decoded pixels use sRGB, straight-alpha RGBA8 with a documented color-profile conversion. Preserve original bytes alongside canonical pixels. Define whether fully transparent RGB is normalized before hashing; apply that rule once at import, never opportunistically during repair. Record decoder/version and orientation handling. The byte hash proves the original file; the pixel hash identifies the canonical raster. Reject decompression bombs and malformed dimensions before allocating large buffers.

The reference clock selects slots from cumulative integer holds using monotonic elapsed time and a documented conversion to ticks. Playback speed affects the presentation clock, not authored holds. Tick-step operates on exact integers. Compare the browser/harness selection against an independent expected schedule at boundaries, under variable paint rates, after pause/resume, and after a long tab suspension. Do not use chained per-frame timers that accumulate rounding drift.

### Contract shape to implement

The following is a compact structural example with symbolic IDs, not a runnable input. WP1 must add complete valid examples and negative schema fixtures.

```json
{
  "schema_version": "2.0",
  "character_revision_id": "char-rev-01",
  "action": {"name": "run", "view": "side", "facing": "right", "loop": true},
  "canvas": {"width": 256, "height": 256, "units": "native_px"},
  "timing": {"ticks_per_second": 60, "holds": [4, 4, 4, 4, 4, 4, 4, 4]},
  "root_policy": {"mode": "in_place", "ground_y": 236},
  "references": {
    "identity": "asset-identity",
    "style": "asset-style",
    "motion_guide_revision_id": "motion-guide-01"
  },
  "phase_schedule": [
    {"slot": 0, "phase": "A_contact", "motion_reference_id": "pose-A-contact"},
    {"slot": 1, "phase": "A_compression", "motion_reference_id": "pose-A-compression"},
    {"slot": 2, "phase": "A_passing", "motion_reference_id": "pose-A-passing"},
    {"slot": 3, "phase": "A_flight", "motion_reference_id": "pose-A-flight"},
    {"slot": 4, "phase": "B_contact", "motion_reference_id": "pose-B-contact"},
    {"slot": 5, "phase": "B_compression", "motion_reference_id": "pose-B-compression"},
    {"slot": 6, "phase": "B_passing", "motion_reference_id": "pose-B-passing"},
    {"slot": 7, "phase": "B_flight", "motion_reference_id": "pose-B-flight"}
  ],
  "constraints": [
    {"id": "registration", "check": "native_registration", "required": true},
    {"id": "support", "check": "declared_contacts", "required": true,
     "annotation_revision_id": "contacts-01", "max_error_px": 1.0},
    {"id": "local_body", "check": "visible_span", "required": false,
     "annotation_revision_id": "features-01", "reference_revision_id": "span-bounds-01"}
  ],
  "allowed_transforms": {"per_pose_scale": false, "rigid_translation_budget_px": 2},
  "transition_contract_ids": ["idle-run-01", "run-idle-01", "run-attack-01"]
}
```

Thresholds shown here are fixture examples, not universal anatomical tolerances. Calibrate on original clean examples, add plausible negative examples, review false positives, then freeze bounds before evaluating held-out attempts. Any later change creates a new contract with a reason and re-runs old regressions.

## 8. Verification framework

Each check declares: stable code, schema version, dependencies, applicability, required inputs, method, units, limits, severity, coverage, known blind spots, overlay renderer, repair hints, and positive/negative fixtures. Return measured values and target intervals, not only a score. Invalid inputs must stop downstream measurements that assume those inputs are valid.

A result identifies the constraint ID, frame/context scope, outcome, observed value, units, expected interval, evidence/annotation/mask IDs, and reason for any missing measurement. Keep perceptual/model observations in a separate result type with source and uncertainty. Merge them for review display without turning a model's confidence into deterministic certainty.

### Check families

| Family | P0 method | Limits and handling |
|---|---|---|
| Integrity and registration | Verify hashes, native dimensions, frozen transforms, margins, nonempty alpha/mask, media decode | Blank or malformed media cannot pass later shape checks |
| Source-sheet ownership | Explicit cell/crop assignments and component inventory; detect clipping and unexplained islands | Connectivity cannot detect an attached extra limb; record approved tiny exclusions rather than dropping components silently |
| Shape and size | Same-view, same-phase reference silhouette area/extent, body-part masks where available, local declared visible spans | Whole-frame height/area cannot prove limb volume or anatomy; cape/weapon motion can legitimately change bounds |
| Appearance | Masked part-level palette comparison, declared costume features, identity/style references | Global histogram misses swapped colors and identity drift. Part masks can themselves fail. Semantic critique remains advisory |
| Phase and action | Registered occupancy/edge descriptors against independent phase guides; declared event/phase order; duplicate/stalled-pose checks | Unlike phases can share silhouettes. Never choose the expected pose from the candidate batch itself |
| Contact and attachment | Reviewed sole/palm/prop points or masks in declared windows; support role schedule | A visible span is evidence of image-plane support, not world-space non-sliding |
| Temporal consistency | Hold schedule, tick boundaries, loop seam, local feature pulse, adjacent pose deltas | High motion is not automatically bad; smear frames and intentional squash/stretch require explicit exemptions |
| Runtime trace | Per-tick root/contact transforms, transition selection, interruption trace, both declared facings | Only certify the supplied harness/adapter trace; do not imply arbitrary engines have been validated |
| Repair protection | Exact decoded RGBA equality outside edit support and in protected regions; frozen base and recipe | Compare pixels, not PNG file bytes. Treat mask/filter halos explicitly |
| Provenance and coverage | Reference eligibility, annotation freshness, complete required check matrix | A correct-looking result with missing authority is incomplete |

### Important algorithms and boundaries

**Visible spans:** measure approved visible feature pairs only within reviewed search regions. Compare to a same-view, compatible-pose bound. Stable costume features may provide a torso-scale proxy; they are not skeleton joints. Missing or ambiguous required features yield `unmeasured`, block the required coverage gate, and create a diagnostic. Known occlusion needs its own applicability annotation. Do not compare a foreshortened attack torso to standing frontal anatomy.

**Phase correspondence:** compute a descriptor in a declared registered region; report expected-phase distance, best alternative distance, and their gap. Thresholds flag a likely wrong phase, not a universal motion judgment. Include a clean crouch/attack and silhouette-alias case to prevent overclaiming.

**World contacts:** transform the visible support point into stage/world units for every presented tick. A planted point should stay within its declared world tolerance while the root moves. Include the interior of held drawings: a fixed foot drawing plus translating root can slide even if the image passes a sole-window check. Distinguish in-place treadmill preview from a world-grounded trajectory. Flight phases have no planted-foot requirement.

**Loop and transition coverage:** wraparound comparisons apply only to loops. One-shot terminal holds and next-state handoffs need explicit rules. Enumerate legal state transitions and report missing tested entries. Interrupt at each relevant run phase; do not reset to an arbitrary standing drawing to conceal a discontinuity. Keep action/gameplay events separate from presentation retiming.

**Mirroring:** an exact whole-drawing mirror is a recorded transform, not a new drawing. Remap pivots, points, ROIs, attachments, contact labels, and asymmetrical features correctly. If costume/weapon design is asymmetric, require authored facing references instead.

**Derived motion:** record every transform or compositing recipe. Repeated holds, local paint interpolation, and rigid translations are different origins from independently drawn poses. A subtle idle can legitimately preserve its silhouette; it should not be judged against a locomotion motion-amplitude rule. If the declared intent requires breathing or weight transfer, test that intent and have the human assess naturalness. Do not “fix” a body-size error by introducing undeclared warping.

### Coverage and evidence

Reports show a per-frame/per-context matrix: measured required, measured optional, intentionally occluded, unsupported, stale, and failed. Keep coverage percentages scoped to explicit check sets; never advertise “100% animation correctness.” Include view/action coverage and independent drawing counts.

An evaluation ID hashes canonical contract JSON, character revision, all input byte/pixel hashes, mask/annotation revisions, registration recipes, timeline/trace, analyzer build or code hash, dependency lock identity, settings, and schema versions. Do not include nondeterministic timestamps in this identity. Hash the dependency closure, not three selected modules. Cache keys use the same dependencies. A changed frame invalidates its local checks, neighbors, loop/transition dependencies, packet eligibility, and downstream export selections.

### Performance targets to measure

These are acceptance targets, not existing results:

- Local cached-core checking on 256×256 frames: target p95 below 50 ms for one changed frame plus its directly affected neighbors, excluding provider calls and video encoding.
- A 200-frame 256×256 procedural batch: target below 5 seconds after startup on the documented developer machine; report cold and warm results separately.
- Playback: correct 60 Hz schedule, without cumulative hold drift over 10,000 loop iterations. Browser rendering may skip paints under load; tick selection remains correct and dropped display samples are observable.
- UI: open a cached review packet in under 2 seconds locally. Thumbnails load progressively; decoding must not block all controls.

A target miss prompts profiling and an honest reduced supported workload. It never permits dropping required checks, hiding `unmeasured`, or claiming unmeasured speedups. No image/vision API belongs in the synchronous playback path.

## 9. Generation, registration, and bounded repair

### Brief compiler

Compile a typed bundle containing the approved identity and style references, independent phase/pose authority, native scale ruler, relevant contact/attachment guides, prior and next accepted context where eligible, required action intent, preservation rules, forbidden transformations, candidate output schema, and evaluation tools to call next. Include both original assets and a labeled visual guide that preserves internal linework. A silhouette-only guide can hide arm placement.

Reference roles must be checked against approval/lineage records. Never use filename fragments as the only rejected-input policy. A rejected candidate may be attached as labeled negative evidence if the task explicitly requests diagnosis; it cannot become the positive master. Never let iterative edits displace the original references. Allow batch/keyframe generation as a provider option, but evaluate every frame, source crop, and temporal relationship.

Generation is not guaranteed to return exact dimensions or transparency. Persist the original response first. Registration is an explicit operation with an auditable recipe: isolate a declared cell, inspect source ownership, apply the approved uniform calibration, place it on the native canvas, record its alpha/mask source, then check. If calibration cannot be established, block the candidate rather than normalizing every pose independently.

### Repair loop

1. Load the exact baseline revision, current evaluation, and issue targets. Reject stale evidence.
2. Produce a repair task with affected frame-instance IDs, requested outcome, allowed mask/region, protected pixels, neighborhood/context dependencies, references, and attempt/cost limits.
3. Ask the provider for a candidate, keeping the original reference bundle. Persist request metadata, actual input assets, output bytes, and errors. Never fabricate output on failure.
4. Register the candidate using the frozen calibration. If provider inpainting cannot preserve the exterior, compose the patch into the original image with a frozen mask. Save the full provider result and the composition recipe separately.
5. Evaluate the whole proposed revision plus relevant transitions. Reject stale bases, undocumented transforms, protected-pixel changes, missing required coverage, and newly failing constraints.
6. Save a child revision and review packet only when the correct selection policy is satisfied. Keep failed attempts for diagnosis and weak labels.
7. Stop at the configured budget or no-progress condition and expose `needs_attention` with the best evidence. Do not retry blind.

Exact exterior protection means the compositing support includes any allowed feather/filter halo. P0 uses a hard mask for deterministic protected pixels; fancier edge blending is a later explicit profile. Local repairs do not alter unrelated timing or registration to compensate for bad art.

### Selection policy

- For **technical repairs**, name targeted issue instances. A progress candidate must resolve a target or improve a defined target metric beyond a frozen minimum; it must introduce no new violation, worsen no protected metric, and reduce no required coverage. Retain it as an intermediate draft if other required defects remain. Send the completed batch for ordinary human acceptance only once all required gates pass.
- Do not use raw total error count as the sole objective. Two harmless warnings disappearing cannot justify a new support failure. Group overlapping defects by cause while retaining individual evidence.
- For a **human visual correction** with zero technical errors, technical error count need not decrease. The new revision must pass the same gates and preserve non-targeted regions; label it `awaiting_human_comparison`. Only the human can say that the subjective issue is resolved.
- Every artistic comparison is against the exact old/new revisions at identical timing by default. If retiming itself is the requested correction, show that change explicitly.

Default P0 budget: three generation/repair attempts per target and a project-configured cost ceiling. These are product defaults, not provider limits. A no-progress signature includes target IDs, candidate content hashes, and unchanged metrics so repeated calls cannot run forever.

## 10. Model-facing tools and orchestration

The model should not need to understand database tables, file layout, web UI internals, or media codecs. Give it a small vocabulary with predictable results. Tool descriptions specify state preconditions, side effects, required evidence, and permitted next steps.

| Tool | Main input → result |
|---|---|
| `project_create`, `project_get` | Project metadata → IDs, capabilities, state summary |
| `asset_import` | Authorized upload/import handle + rights/source metadata → immutable asset IDs and diagnostics |
| `contract_propose`, `contract_validate` | Structured action/reference constraints → draft revision, missing authority/coverage list |
| `clip_create_revision` | Contract ID + frame instances + expected base → draft revision |
| `brief_compile` | Revision/phase/issue target → conditioning bundle + content hash |
| `generation_submit`, `job_get`, `job_cancel` | Brief + provider + idempotency key → persisted job/attempt |
| `candidate_register` | Attempt output + approved registration recipe → candidate revision or explicit blockers |
| `clip_evaluate` | Exact revision + check profile → evaluation + coverage + overlays |
| `repair_plan`, `repair_evaluate` | Exact issues/base/masks/candidate → bounded task or selection result |
| `review_packet_create`, `review_packet_get` | Revision/evaluation/comparison → curated evidence and persistent review URL |
| `corrections_list`, `correction_claim`, `correction_submit` | Cursor/lease/source issue → task or replacement packet |
| `dataset_export`, `dataset_validate` | Frozen selection + policy → snapshot/job + independent validation report |

Human actions such as approve reference, approve/reject art, and resolve an issue are authenticated review API operations. They are not exposed as model tools. The orchestrator may acknowledge a task or submit a proposed fix; it cannot impersonate its reviewer.

Enforce that separation in service authorization, rather than only hiding tool names. Orchestrator credentials cannot invoke review writes, freeze reference approvals, or alter publication gates. Review writes use a reviewer session with origin/CSRF protection; events retain actor type. Local development access must not accidentally turn the model's API token into a reviewer token.

### Result envelope

```json
{
  "schema_version": "2.0",
  "ok": true,
  "operation_id": "op-123",
  "revision_id": "clip-rev-04",
  "technical_status": "incomplete",
  "human_acceptance": "unreviewed",
  "coverage": {"required_total": 12, "required_measured": 11},
  "issues": [{"code": "required_anchor_unmeasured", "frame_instance_id": "fi-03"}],
  "artifacts": [{"id": "asset-overlay-03", "role": "diagnostic_overlay"}],
  "next_actions": ["request_annotation_review"],
  "cursor": null
}
```

`ok` means the operation executed successfully, not that the art passed. Invalid input, stale revisions, rate limits, cancelled jobs, unsupported provider capabilities, and media failures have stable error codes and retryability. Validate unknown keys, enums, non-finite numbers, lengths, ROI bounds, duplicate IDs, and positive holds. A transport must not turn failure into an empty successful list.

### Spark runtime controller

Use Spark to select actions and interpret evidence. Keep budget, permissions, reference eligibility, tool schemas, state transitions, and publication gates in application code. Persist the conversation/tool trace sufficiently to replay decisions and reconstruct conditioning; do not require or export private chain-of-thought.

The controller repeatedly retrieves project state, compiles a brief, submits or registers a candidate, evaluates it, chooses a bounded repair if justified, and creates a packet when eligible. It waits on explicit job status and correction cursors rather than flooding the server with polls. At `awaiting_review`, it stops generating. Resume only for a new correction or an authorized new task.

Parallelize independent frame checks or provider requests within configured budgets. Do not mutate the same revision concurrently or race approval against repair. Tool calls must be matched with their corresponding results before the next model turn. A model timeout does not erase completed work.

## 11. Meta integration: verified surfaces and remaining work

Meta’s current [overview](https://dev.meta.ai/docs/overview) documents `https://api.meta.ai/v1`, bearer authentication through `MODEL_API_KEY`, Spark `muse-spark-1.3`, Muse Image `muse-image-1.0`, and SAM `sam-3.1`. Treat these as researched starting points and verify them with the participant’s actual account. Provider access and behavior can differ; missing access is a capability result, not an excuse to invent success.

### Muse Spark

Use a documented structured tool loop. The [tool-calling guide](https://dev.meta.ai/docs/tool-calling) makes local tool execution the application’s responsibility. Use [structured output](https://dev.meta.ai/docs/structured-output) for proposed contracts/critic records where supported, then still validate semantics server-side. Schema conformity cannot prove that a point is visible or that an action was performed.

Spark critique consumes images and short clips with frame/time identifiers, approved references, declared intent, and deterministic findings. Require localized observations, uncertainty, and evidence references. Keep critique advisory and separately labeled. A second call to the same model is not independent ground truth.

### Muse Image

The [image-generation guide](https://dev.meta.ai/docs/image-generation) supports interleaved reference images through Responses and image editing through the edits endpoint. Its `size` parameter controls aspect ratio rather than guaranteeing exact returned pixels. Persist and inspect actual outputs; explicit registration is essential. Select returned image items by type, rather than assuming the first response item contains an image. Archive output bytes immediately instead of retaining expiring signed URLs.

Prefer the documented reference-conditioned Responses flow for P0. Send actual approved reference pixels or provider file IDs, not local filesystem path strings. Capture every reference role and hash in the ledger. Confirm output encoding, alpha, multi-image limits, timeouts, and edit/mask behavior in a small integration spike. Do not assume support for seeds, exact dimensions, ControlNet, a video endpoint, or strict inpainting masks. Feature flags must describe capabilities actually observed.

The same guide documents internal image/web search controls. For reproducible original-character work, disable external search where supported and record tool settings. Preserve any provider provenance available for generated material.

### SAM 3.1

The [media-segmentation guide](https://dev.meta.ai/docs/media-segmentation) uses Responses with real image/video content. It describes special-token box/mask output requiring decoding. Implement and test the documented parser/client path; do not send a local path to chat completions and call the result a mask. Store the mask bytes, prompt, coordinate mapping, model identity, request ID, and any returned confidence. No match, multiple matches, corrupted output, or inconsistent dimensions is an explicit result.

Alpha is a useful deterministic fallback when it truly represents the intended foreground. Opaque backgrounds do not become subject masks. SAM proposals need quality checks against obvious empty/full/clipped masks and approved references; thin or occluded parts may remain unmeasured. Keep mask uncertainty visible in every measurement that depends on it. Never label an alpha mask as SAM output.

### Provider contract spike

Before building elaborate generation UX, save a redacted request/response fixture for: one Spark tool call, one image request carrying at least two role-labeled references, one image edit, and one SAM result that decodes into a correctly aligned mask. Pin the SDK/parser versions and record the docs URLs in `docs/PROVIDER_CONTRACTS.md`. Provide a no-key `unsupported/not_configured` result; keep offline procedural and recorded-replay modes distinct. Retry only bounded transient failures with backoff. Record cost/usage when returned and mark estimates as estimates.

## 12. Persistent review application

The desk is where a person makes decisions after the model has done the repetitive work. Use short labels and concrete findings. Avoid marketing copy, invented quality percentages, and a wall of raw JSON.

### Screens

| Screen | Required behavior |
|---|---|
| Project inbox | Projects, actions, revision, pending packets, blocker count, coverage gaps, last activity; resume where the reviewer stopped |
| Review packet | Intent and reference strip; large stage; true-speed clip; frame strip/timeline; findings and coverage; explicit decision controls |
| Compare | Baseline/candidate synchronized at identical timing; side-by-side, blink, onion-skin, or difference; distinguish timing corrections |
| Issue detail | Exact ROI/frame range, note/category/severity, evidence, correction status, attempt history, replacement packet link |
| Artifact shelf | Persistent stills, contact sheets, guides, masks, overlays, video and dataset snapshots with role/source labels |
| Dataset snapshot | Counts by label origin, independent drawings, accepted/unreviewed/failed data, exclusions, split policy, validation, download |

### Playback and media

- Native-resolution and gameplay-scale views; integer zoom/pixelated sampling for pixel art; appropriate smooth sampling for illustration.
- Play/pause, previous/next drawing, tick step, restart, playback speed, loop/one-shot indicator, slot/phase/elapsed time, optional contact/root overlays.
- Fixed stage registration: no automatic recentering or zoom per frame. Background choices should expose alpha edges and readability.
- Canonical playback uses the frame manifest and integer clock. Preview MP4/GIF/video is a derived artifact with the same timing metadata.
- Imported video keeps source PTS and a frame/time mapping. Do not invent a fixed FPS for variable-rate sources. A source without reliable extraction/timing can be reviewed as video with reduced measurement coverage.
- Video issue ranges use timestamps and map to canonical frame instances where a mapping exists. MP4 is normally composited; preserve original alpha frames separately.
- Contact sheets and overlays are immutable artifacts linked to the exact revision/evaluation, rather than temporary browser screenshots.
- Display genuine generated outputs, procedural fixtures, recorded replay, and derived samples with clear source badges.

### Issue marking and correction handoff

Pause or select a frame range, draw a rectangle or click a point, choose shape/size/movement/appearance/timing/contact/other, add a concise note, and submit. Category and spatial markup are aids; prose is optional when the structured annotation is sufficient. Include desired outcome when known.

The resulting task contains packet/revision/evidence IDs, affected frame instances and time interval, ROI in native coordinates, category, note, relevant references, protected scope, and the comparison baseline. Preserve the original subjective statement alongside machine-readable tags. The model claims the task with a lease and submits a replacement packet. The issue becomes `awaiting_comparison`, then the human explicitly resolves, reopens, or rejects it. Unrelated issues remain open.

Do not re-show unchanged passed frames as new work. Group related frames into a packet and prioritize new defects, high-impact changes, and uncertain coverage. Always permit opening the full clip and transition context; curation must not conceal failures.

### Persistence and interaction quality

SQLite stores projects, packet selection, annotations, issues, decisions, and task state; blobs store media. Refresh, browser close, and service restart preserve all review history. UI requests show saving/saved/failed state and prevent duplicate decisions. Server-sent events with cursor-based catch-up can update jobs/tasks; polling remains a working fallback.

Keyboard support: Space play/pause, arrows drawing step, modified arrows tick step, Escape cancel ROI, and labeled shortcuts for decisions. Show focus and selection. Never use color as the sole status cue. At 1440×900 and a smaller laptop viewport, stage, timeline, and decision controls remain usable. A media failure displays the missing artifact and retry state; it must not leave a black stage that looks like an empty valid drawing.

Reference approval is a small review operation, not a general character editor. Threshold/contract changes are proposed revisions with before/after differences and invalidated evidence, rather than sliders the model can move until the art turns green.

## 13. Training data as a first-class output

Maintain two concepts: a complete **research archive** and selected **training views**. The archive captures attempts and events; positive image training, defect-critic training, preferences, and temporal training have different eligibility rules. A technical failure is useful supervision but is not an approved generative target.

### Export layout

```text
snapshot/
  README.md                       # dataset card, rights and limitations
  snapshot.json                   # frozen selection, versions, split policy
  manifest.sha256.json             # relative path -> byte hash
  media/images/<digest>.png
  media/masks/<digest>.png
  media/videos/<digest>.mp4
  conditioning/<brief-id>.json
  archive/attempts.jsonl
  archive/events.jsonl
  archive/evaluations.jsonl
  imagefolder/{train,validation,test}/
    <digest>.png
    metadata.jsonl
  coco/annotations/instances_{train,validation,test}.json
  coco/images/{train,validation,test}/<digest>.png
  records/critic.jsonl
  records/preferences.jsonl
  records/corrections.jsonl
  records/temporal.jsonl
  validation/report.json
```

All references are relative and remain valid after moving the snapshot to another machine. Copy, package, or safely deduplicate every referenced original/reference/mask/candidate asset; no absolute local paths or expiring provider URLs. No credentials or unnecessary personal identifiers travel in the archive.

### Standard formats and honest compatibility

| View | Format and intended use | Validation required |
|---|---|---|
| Positive frame generation | Hugging Face ImageFolder: images plus `metadata.jsonl`, including `file_name`, caption/text, original brief, frame context and labels | Load with `datasets.load_dataset("imagefolder", data_dir=...)`; access actual pixels and verify required metadata |
| Segmentation/detection | COCO instances with categories, image dimensions, bbox, area, and RLE masks | Load with COCO API; decode masks with `pycocotools`; compare pixels, bbox and area to originals |
| Defect critic | Typed JSONL records with assets/context, check outcomes, coverage, label origin and optional human defect labels | Load through `datasets` with declared features; do not equate a technical failure with a human-rejected image |
| Image repair/preference | Documented paired records with common conditioning ID, chosen/rejected asset IDs, decision provenance and context | Validate same-task comparability, explicit label origin, packaged pixels, and distinct hashes |
| Temporal learning | PNG frame sequences plus typed temporal JSONL and optional MP4 preview; ordered IDs, PTS/holds, roots, contacts, phases, loop/transitions | Load via a supplied example reader; check timestamps, frame count, duration and media hashes |

ImageFolder’s image/metadata convention is documented by [Hugging Face Datasets](https://huggingface.co/docs/datasets/image_dataset). Use it directly rather than inventing a directory structure and assuming the loader accepts it. COCO mask encoding/decoding is provided by the [official COCO API](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/mask.py); use column-major binary masks and test round-trip equivalence. Handle compressed RLE serialization correctly and resolve `file_name` relative to the actual images root.

The [TRL dataset guide](https://huggingface.co/docs/trl/dataset_formats) specifies text/conversation preference structures, including `prompt`, `chosen`, and `rejected`. Merely placing image filenames in those columns does not create a generally usable image DPO dataset. Framebound’s image pairs and temporal records are **versioned task schemas built from standard media**, with adapters/examples for a named downstream pipeline. Do not advertise universal direct DPO/video-training compatibility. If exporting text/tool SFT or preference traces to TRL, match its documented schema and verify the chosen trainer can consume a sample.

### Label and preference policy

- Positive image training defaults to exact human-approved outputs that also meet technical eligibility. An explicit research policy may include technical-only positives, but exports must call them weak labels and keep that view separate.
- Use a human chosen/rejected pair only after an explicit comparison between two outputs for the same character, action phase, contract, and conditioning task. A reference drawing is not automatically a preferred completion.
- A repair request and the original generation request often differ. Store both execution prompts. Define a common outcome-conditioning record for any pair; if comparability cannot be established, retain a correction example instead of inventing a preference.
- Technical ranking pairs can exist in a separate weak-label view with check-based origin and rationale. They must not silently mix with human preferences.
- A rejection without a paired approved replacement remains an unpaired negative. Unreviewed work is not rejected work. Human approval does not imply every anatomical dimension was measured.
- Preserve the exact set of issue labels, including clip-wide failures. A frame cannot be labeled generally passing merely because it lacks a slot-specific error.
- Masks and keypoints include source and trust level: alpha, SAM proposal, model proposal, or human-reviewed. Do not fill hidden keypoints with guessed coordinates. If keypoints are added to COCO, define the category/skeleton and visibility mapping explicitly.
- Store explicit decisions, correction notes, tool calls/results and available concise model summaries. Do not require private reasoning traces as training data.

### Leakage, duplication, rights, and sampling

Group train/validation/test by character family and reference/derivation lineage, not random frames. Original, mirrored, retimed, repaired, resampled, and near-duplicate variants stay in the same split. Group sources before deriving data. Detect exact pixel duplicates; use conservative near-duplicate grouping plus reviewed lineage for semantic duplicates. Freeze the split seed and group manifest. If there is only one character family, a genuine identity-held-out evaluation is unavailable: export train plus an explicitly limited development benchmark or leave validation/test empty. Never claim generalization from neighboring poses of the same source.

Record source origin, license/permission, provider terms reference, attribution requirements, consent where relevant, allowed uses, and export eligibility for every asset. Unknown permissions default to exclusion from shareable training exports with an explanation; preserve private archival evidence according to project policy. Keep code licensing separate from art/data licensing. The demonstration should use original character assets with documented provenance.

Repeated holds and derived samples do not multiply positive-example weight automatically. Export independent drawing count, unique pixel count, sequence duration, derivation count, and sampling/weighting policy. Avoid training a model to copy one frame merely because it appears in many ticks. Specify any background compositing or RGBA→RGB conversion required by a downstream model; retain alpha originals and do not train accidentally on a checkerboard preview.

### Obsolescence measurement

Track defects per 100 independently generated poses, provider attempts per accepted clip, human review time per accepted clip, unresolved coverage, reference dependence, and false-negative defects discovered in human review. Keep a held-out action/character set as corpus size permits. Compare an untrained baseline and any fine-tuned model under the same briefs, costs, and checks. Improvement means less correction without increased missed defects. More exported rows alone is not progress.

P0 must prove valid exports and example consumption. Fine-tuning an image/video model is not required for completion. A small critic experiment is P1 and must report dataset size and leakage limitations. Do not imply that closed provider models can necessarily be fine-tuned with these exports.

## 14. Test strategy and acceptance fixtures

Tests must exercise independent expectations and known failure modes, not simply serialize and re-read the implementation’s own result. Keep original procedural fixtures deterministic; use genuine generated examples as a separate recorded integration corpus. Add each new human-discovered defect to a regression case before changing tolerances.

| Fixture / test | Expected behavior |
|---|---|
| Clean registered run | Pass its declared required checks; report optional unsupported dimensions |
| Same canvas, local torso pulse | Local span/part check fails even when whole-frame height stays constant |
| Intentional crouch or foreshortening | Correct compatible-phase profile passes; inappropriate standing comparison is inapplicable |
| Wrong pose replacing push-off | Phase/contact defect detected against independent guides |
| Similar silhouette, different action | Descriptor ambiguity reported; no universal anatomy/action approval |
| Blank frame / full background / no segmentation match | Explicit error or unmeasured result; never success by zero area |
| Missing/ambiguous required feature | Technical status incomplete, coverage gap present |
| Hidden limb / proposed joint | No fabricated length or reviewed landmark |
| Pose-specific resize / clipped toe / unexplained component | Registration/ownership failure; attached-extra-limb limitation stays disclosed |
| Repeated holds and derived interpolation | Correct sample count and distinct drawing count; no false independent-pose claim |
| Hold boundary and 10,000 loops | Exact scheduled frame on both sides of every boundary, no cumulative drift |
| One-shot terminal pose | No artificial last→first seam test; declared terminal/handoff honored |
| Translating root with held planted drawing | Per-tick world sliding fails even when static support passes |
| Run interrupted at each phase | Declared departure/entry behavior and contact continuity; missing transition reported |
| Exact mirror and asymmetric costume | Transformed annotations remain aligned; prohibited mirror is rejected |
| Local repair | Protected RGBA pixels identical; original provider output and composite both retained |
| Repair with fewer total errors but new contact failure | Rejected as regression |
| Subjective issue with baseline technical pass | New passing candidate can reach human comparison without inventing numerical improvement |
| Changed input/annotation/analyzer/timing | Cached evaluation and downstream acceptance eligibility become stale |
| Stale browser approval or stale correction submit | 409; approval cannot attach to new pixels |
| Retry identical tool action | One attempt/event, same operation ID; no duplicated paid generation |
| Restart mid-job / unknown provider timeout | Recovery reconciles durable state and does not blindly reissue |
| Human rejects one issue, approves unrelated frame | Only explicit issue-resolution events close issues |
| Export after moving directory | All referenced images, masks, guides, comparisons load by relative path |
| Invalid preference / split leakage | Export excludes or fails validation with a precise reason |
| ImageFolder and COCO consumers | Real library loading and mask round-trip succeed |
| Corrupt/missing preview | Clear media error; source sequence and review history remain accessible |
| Review injection/path traversal | Notes render as text; asset endpoints cannot read arbitrary files |

### Browser acceptance journey

From a clean project, import original fixtures, freeze a reference set, create/evaluate a clip, open a packet, watch real-speed playback, mark an ROI over frames 3–5, and submit. Restart the API and reload the browser. Confirm the issue, annotation, selected revision and media survive. Have the tool client claim it, submit a passing replacement, compare both revisions, and resolve the specific issue. Export, move the snapshot, and load it independently. Verify the original failure, replacement, and human event all remain traceable.

P0 release requires this journey through the real service and browser, plus the CLI and MCP invoking the same evaluation semantics. Mock providers verify the mechanics; at least one recorded actual Meta run verifies the provider claim.

## 15. Ordered implementation work packages

The suggested dates use Dublin time and assume work begins 27 October. Treat the acceptance gates as binding and the dates as planning targets. If a package slips, use the scope cuts below rather than claiming unfinished work is done.

| Package | Target | Deliverables and files | Completion gate |
|---|---|---|---|
| WP0: baseline and integration spike | 27 Oct | Inventory/migration report; `IMPLEMENTATION_STATUS.md`, `SUBMISSION_REQUIREMENTS.md`, `PROVIDER_CONTRACTS.md`; redacted provider fixtures; dependency decision | Existing tests recorded; actual available endpoints/outputs established or explicit access blocker documented; no fabricated live claim |
| WP1: schemas and durable domain | 27–28 Oct | `domain/`, `storage/`, `schemas/`; asset store, revisions, annotations, review events and jobs; migration dry run | Complete valid examples, invalid-input tests, stale-write protection, asset hashing, restart recovery, untouched originals |
| WP2: canonical media and verification | 28–29 Oct | `media/`, `checks/`; registration, integer timeline, coverage, evidence IDs, overlays, original faults | Clean and negative fixtures behave correctly; per-tick sliding and loop/one-shot cases tested; stale evidence rejected |
| WP3: tools, providers and bounded loop | 29–30 Oct | `services/`, `mcp/`, CLI, `providers/`, `orchestration/`, `briefs/`; three-attempt budget | Real client MCP handshake; references reach image model; outputs stored; masks decoded if available; bounded repair and no-regression policy work |
| WP4: review desk and human round-trip | 30 Oct–1 Nov | `api/`, `web/`, packet renderer, ROI/range issues, correction leases, before/after | Full browser restart journey passes; human decisions cannot be written by model tools; subjective correction supported |
| WP5: portable training snapshots | 1–2 Nov | `exports/`, loaders, split/rights policies, dataset card | Moved snapshot loads with `datasets` and COCO API; labels/preferences checked; hashes and duration match; exclusions visible |
| WP6: genuine character demonstration | 2–3 Nov | Original run/jump/attack assets, three transitions, provider ledger, review history, 200-frame stress benchmark | Full workflow works on real output; no hidden auto-fitting; visual acceptance remains accurately reported; live/replay badges correct |
| WP7: release and submission | 3–4 Nov | Clean-clone instructions, local verification script, video, demo package, actual submission artifacts | All P0 gates pass; exact portal requirements checked; repository PR merged; submission receipt verified by the entrant |

Build a minimal API and plain diagnostic page during WP2/WP3 so evidence can be inspected before visual polish. By 30 October there should be a thin complete path through storage→check→repair→review event→export; later packages deepen it. Do not spend the first three days on an attractive empty dashboard.

Each package uses its own branch, local validation, remote PR, and merge to `main`, as required by repository instructions. Resolve conflicts and re-run the affected checks. Keep PRs small enough that a reviewer can understand which invariant they implement. Do not add a remote dependency or deploy an exposed writer just to manufacture a demo URL; establish the portal’s actual requirements first.

### Proposed validation interface

Implementation must provide a documented command set equivalent to the following. These are target commands; they do not exist in the initial prototype.

```sh
python -m framebound doctor
python -m framebound migrate-v1 --source PATH --dry-run
python -m framebound demo --profile v2 --offline --out PATH
python -m framebound serve --project PATH --host 127.0.0.1
python -m framebound verify --project PATH --report PATH
python -m framebound export --project PATH --snapshot NAME --out PATH
python -m framebound dataset-validate --snapshot PATH
python -m framebound benchmark --fixture stress-200 --report PATH
python -m pytest
```

Add exact frontend typecheck/build/browser commands to the README after selecting the package manager and pinned runtime. Add one `scripts/verify-local` entry point that runs the meaningful P0 checks with clear failure exits. Core validation must work offline; provider tests are opt-in and visibly skipped when credentials/access are absent. Skipped live tests do not count as provider proof.

### Scope cuts if behind

Keep contracts, evidence, coverage, protected repair, persistent correction, real provider proof, and validated exports. Cut extra characters/directions, elaborate overlays, video upload conveniences, automatic skeleton/part proposals, engine adapters, cloud hosting, and training experiments first. If multi-action art cannot be completed, demonstrate a complete run plus explicit transition fixtures and document reduced action coverage. Do not call that the full P0 release. Do not substitute hundreds of duplicate frames for independent motion.

## 16. Instructions specifically for Muse Spark 1.3

Meta describes Spark 1.3 as suited to long-horizon tool use, coding, and multimodal perception, with a large context window and configurable reasoning. Those are documented capabilities, not proof of flawless implementation or animation judgment. See [Muse Spark 1.3](https://dev.meta.ai/models/muse-spark). Use the strengths for repository comprehension, inspecting visual artifacts, generating typed implementation proposals, and following a tool/evidence loop.

No project-specific evaluation of Spark 1.3’s failure rates was available during planning. The safeguards below address general coding-agent risks and the concrete prototype defects observed here. Do not present them as experimentally established model-specific weaknesses. Begin with a short calibration pass and tighten workflow where failures actually occur.

### Calibration tasks before large changes

Ask the model to: identify every authority/state boundary in WP1; derive the selected frame at exact hold boundaries; explain a technical pass with partial optional coverage; distinguish a draft landmark from a reviewed point; reject a repair that reduces error count but introduces sliding; build a reference-bearing image request from current docs; and load a sample dataset using independent libraries. Compare answers to fixtures and tool results. Record failures and the guard that catches them in `IMPLEMENTATION_STATUS.md`.

### Working discipline

1. Read this entire plan, current repository instructions, and implementation status before editing. Restate the current package and acceptance gate concisely; do not regenerate the architecture every session.
2. Work on one package/vertical slice at a time. Begin with schemas and independent failure fixtures, then service implementation, then transports/UI, then recorded validation. Do not implement the whole plan in one unreviewed change.
3. Use higher reasoning for schema/state transitions, coordinate/timing math, repair policy, and export labeling. Use ordinary effort for bounded mechanical edits. Verify supported reasoning values against the actual client; do not invent configuration parameters.
4. Search current provider/library documentation before writing integrations. Pin versions and save a minimal exercised example. An SDK-compatible API does not imply every multimodal capability shares the same request/response schema.
5. Use server-side validation and deterministic gates even when structured generation is enabled. If a required fact is absent, return an explicit missing-input/unsupported result. Never fill a schema with plausible invented coordinates, approvals, prices, or IDs.
6. Keep a short durable handoff: branch/commit, package, changed files, schema versions, test commands and results, genuine artifacts, known blockers, next exact step. The large context window is useful; it is not a substitute for this ledger.
7. Inspect actual native drawings and normal-speed clips after media changes, including seams and transitions. A contact sheet or passing numerical check alone cannot establish motion quality. Report automated observations separately from human visual decisions.
8. Preserve frozen references and negative regressions. Do not solve a failing fixture by widening thresholds, disabling a check, treating unknown as pass, relabeling a reference as approved, or changing expected output without a reviewed contract change.
9. Do not optimize for green status by altering frame holds, root trajectory, canvas calibration, or allowed masks unless that is the authorized task. A local visual fix must not acquire an unrelated timing fix silently.
10. Verify outcomes through a separate consumer: standard dataset loaders, a real MCP client, an API/browser restart journey, and trace fixtures computed from explicit expected schedules. Tests that only echo generated JSON are insufficient.
11. Execute tools and inspect exit status. Never write “tested,” “live,” “approved,” “persisted,” or “compatible” based only on code inspection, mock responses, or intention. If a test is blocked, name the blocker and retain the evidence.
12. Do not hardcode the demonstration character into algorithms or hide failures to make the presentation smoother. Keep reusable mechanisms, subject-specific contracts, procedural fixtures, and genuine generated evidence separate.
13. After each slice, run the relevant checks, review the diff, open the remote PR, resolve conflicts, and merge only after its acceptance gate passes. Do not use a huge rewrite or last-minute feature addition to bypass the staged gates.

### Failure guards

| Risk | Guard in the implementation workflow |
|---|---|
| Plausible but invented provider interface | Minimal live spike, docs link, recorded redacted fixture, strict adapter capability tests |
| Losing constraints across a long task | Package checklist, durable handoff ledger, schema/authority tests |
| Fixing symptoms by weakening criteria | Frozen profiles, required negative fixtures, explicit contract-revision review |
| Calling visual guesses measurements | Typed proposal/review/visibility states; unmeasured coverage gates |
| Confusing technical success with approval | Separate state fields, review-only actor permissions, stale-revision tests |
| Rendering a beautiful but nonfunctional UI | Full persisted correction journey before polish; empty/error/restart states |
| Inflated training or pose claims | Standard-loader tests, pair-eligibility validator, independent-drawing and lineage counts |
| Endless repair or expensive duplicate attempts | Persisted attempt IDs, budgets, no-progress signature, timeout reconciliation |
| Missing coordinate/timing edge cases | Explicit units, half-open intervals, mirror/ROI/held-foot/transition fixtures |
| Claiming planned work as delivered | Status ledger with commands and artifact IDs; distinct planned/implemented/verified columns |

## 17. Release definition and demo script

The hackathon implementation is complete only when:

- A fresh clone starts with documented dependencies, an offline demo, and explicit provider configuration.
- A real model run creates reference-conditioned output, checks it, records a repair attempt, and produces a packet, with genuine provider provenance.
- Required registration, phase/timing, contact, repair protection, and evidence-freshness regressions are covered by independent tests.
- Human issue marking survives restart and returns to the model with exact ROI, time range and revision; a replacement returns for explicit comparison.
- Technical status and unresolved coverage remain visible even after a human decision; model tools cannot write that decision.
- Moving an export to a new directory does not break images/references/masks/timing; standard image and segmentation consumers load it.
- Positive targets, weak negatives, actual human preferences, correction records, and derived samples are labeled accurately, with rights and split policy.
- Performance targets have measured results or clearly stated misses and supported limits.
- Current docs describe implemented behavior, the remote PR is merged, and all remaining submission requirements are checked against the actual portal.

Suggested demonstration, adapted to the portal’s verified duration limit:

1. Show a clean character reference, then a visibly inconsistent run. State the developer’s practical problem briefly.
2. Show Spark using typed tools, Muse Image receiving real reference inputs, and the framework catching a local pulse or incorrect support phase.
3. Compare the bounded repair at normal speed. Inspect one protected contact/region and the coverage report.
4. Mark an issue across a frame range, show the resulting model task, and open the returned comparison packet. Reload to demonstrate persistence.
5. Export and load the dataset. Show a genuine chosen/rejected pair, original conditioning, timing, and label provenance.
6. State the supported scope and the training objective: fewer defects and less review over time. Label any replay or procedural data while it is visible.

Keep screen text functional: action name, revision, phase, measured defect, coverage, and decision. The evidence should carry the demonstration.

## 18. Copyable implementation kickoff

```text
Implement Framebound using docs/GREENFIELD_IMPLEMENTATION_PLAN.md as the design
authority. It is a staged greenfield replacement, not an instruction to delete
the existing prototype or user data.

First inspect repository instructions and current implementation status. Start
WP0 on a dedicated branch: record the baseline, inventory reusable original
fixtures and user data, verify current Meta provider interfaces, and record
authenticated hackathon requirements if accessible. Do not invent inaccessible
rules or call offline/mock output a live integration.

Then complete WP1 and proceed through the ordered work packages. Preserve the
plan's authority boundaries: frozen references, explicit registration, exact
timing, measured versus unmeasured coverage, revision-bound human review,
protected bounded repairs, and honest portable training labels. Keep provider
generation outside playback. Keep the model-facing service contract primary.

Build and verify a thin complete persisted workflow before polishing the web
desk. Use independent fixtures, a real MCP client, browser restart tests, and
standard dataset loaders. Maintain docs/IMPLEMENTATION_STATUS.md with the
current package, actual commands/results, artifacts, limitations and next step.
Never loosen a frozen bound or manufacture an approval to pass a test.

For each package, create the remote PR, resolve conflicts, run its acceptance
checks, and merge to main. Continue through P0; apply the documented scope cuts
if necessary and report reduced coverage honestly. Do not claim the full P0
release until its completion gates have actually passed.
```
