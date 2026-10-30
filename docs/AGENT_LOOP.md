# External-agent loop (v3)

Framebound accepts externally generated PNG assets against an immutable task;
no guide approval, review packet or browser session is needed. The reviewed-guide
v2 route remains available separately.

## Public operations

| Operation | CLI | MCP | HTTP |
|---|---|---|---|
| Start/resume | `agent-run-start --task-id TASK --run-id RUN` | `agent_run_start` | `POST /v3/runs` |
| Progress/feedback | `agent-run-get --run-id RUN` | `agent_run_get` | `GET /v3/runs/RUN` |
| Submit/evaluate | `agent-run-submit --submission FILE` | `agent_run_submit` | `POST /v3/runs/RUN/submissions` |
| Exact evidence | `agent-revision-get --revision-id REV` | `agent_revision_get` | `GET /v3/revisions/REV` |
| Output policy | `agent-run-eligibility --run-id RUN` | `agent_run_eligibility` | `GET /v3/runs/RUN/eligibility` |
| Cancel | `agent-run-cancel --run-id RUN --reason TEXT` | `agent_run_cancel` | `POST /v3/runs/RUN/cancel` |

Each CLI command also takes `--project DIRECTORY`. Import pixels with the existing
`asset-import`/`asset_import` operation first. A submission JSON file contains:

```json
{
  "run_id": "run-1",
  "revision_id": "attempt-2",
  "frame_asset_ids": ["drawing-0", "corrected-1", "drawing-2"],
  "parent_revision_id": "attempt-1",
  "feedback_id": "feedback:attempt-1",
  "presented_holds": [2, 3, 2],
  "generation_metadata": null
}
```

The initial submission omits parent and feedback. HTTP gets `run_id` from its URL.
The complete ordered asset list reuses unchanged asset IDs. Missing generation
metadata is stored as missing, without invented prompts or provider details.
Identical request replay returns the same feedback without another attempt.
Different content under an existing revision ID and stale parents are rejected.

## Measured profile

`structural-v1` checks native dimensions, readable nonempty pixels and exact holds.
Its completion explicitly does not verify animation quality.

`fixed-subject-v1` adds an explicitly limited declared-region matrix. It requires
feature, appearance, contact, continuity and moving-interval measurements, plus a
loop-boundary measurement for looped clips. Missing families remain required and
unmeasured; no reference image or annotation is manufactured to fill them.

A `region_observations` entry binds `id`, `family`, `slot`, native half-open `roi`,
exact `rgba`, inclusive `minimum`/`maximum` matching-pixel counts, `visibility`,
`provenance` and `source`. Families are `feature`, `appearance` and `contact`.
Visibility can explicitly exempt an occluded region; that is not a claim about
its hidden anatomy. Color measurements are local to the specified region.

A `temporal_observations` entry binds `id`, `family`, `left_slot`, `right_slot`,
`provenance` and `source`. `continuity` and `loop` additionally bind
`left_region_id`, `right_region_id` and `max_distance_px` for the corresponding
color-centroid displacement. `moving` checks that the two declared drawings are
different. Only declared moving intervals reject repeats; intentional holds are
allowed. Loop observations must bind the final slot to slot zero in a looped task.

Bounds are task-authored assumptions, frozen with their provenance. They are not
universal quality scores. Exact-color counts and centroids cannot establish
anatomy, identity across arbitrary poses, physical contact, or the correctness
of a prose action. Add an explicit required requirement for an essential claim
that these methods cannot measure; it will block automatic completion. Model or
agent-proposed measurement assumptions retain their source and do not become
human labels. General images without usable color/region declarations need
another validated evaluator; the present profile must not claim coverage.

The executable procedural benchmark is `tests/test_agent_loop.py`. It includes
feature disappearance and duplication, costume-region flicker, unexpected feature
displacement, missing declared image-plane contact, an unintended repeated drawing
and a broken loop. Each has an independently authored expected check ID and a
fail → repair → pass assertion. Counterexamples include valid deformation outside
constrained regions, intentional holds and explicit occlusion. The occlusion case
retains partial coverage when temporal evidence is absent. This benchmark proves
engineering behaviour on these controlled fixtures; it is not real generated-art
validation or a statistical estimate of evaluator reliability.

## Persistence and authority

Submissions, frame instances, native registrations, evaluations, feedback and
completion are committed atomically. Immutable frame/registration and asset
records reuse the established v2 media/storage types. V3 revision/evaluation
semantics are stored in explicit v3 tables so legacy v2 readers cannot silently
interpret automatic output as reviewed data. The schema addition backs up the
project to `backups/before-agent-loop-v3.sqlite3` before creating those tables.
Older task serialization and hashes are retained; new model defaults do not
rewrite the saved task or its negotiated capabilities.

A run has separate current/best revisions. Selection retains earlier success on
required checks rather than accepting an improvement that introduces regressions.
Every attempt remains queryable, including rejected improvements. Fingerprints,
submission limits and no-progress counts survive restarts; repeated/alternating
outputs eventually stop. A second run name for the same animation is rejected,
including when a new task specification exists, so it cannot reset the budget.
Task rebinding uses the explicit version-checked specification-revision operation
below; it retains spent budgets and exact old evidence. Starting another run is
not a workaround.

Media/tool errors and missing measurements are distinct from measured defects.
Feedback includes stable issue IDs, exact bindings, localized frame/tick/region
scope, actual and expected values, hashes and evidence locations, preservation
instructions, regression results and actual submission arguments. Required
unmeasured results prevent completion. Timing changes never obtain a pass under
the same task. Declared-region edit permission is currently rejected until a
saved intervention grant exists; the loop does not widen it to full-clip edits.

Automatic completion uses `technical-unreviewed-v1`; it records no reviewer event
and leaves creative status unreviewed. `human-reviewed-v1` waits for a concrete
decision instead. Output eligibility rechecks current evidence hashes, policy,
coverage and run state; it is separate from the legacy human-reviewed release
route. Internal provider execution is unavailable on this path: the external
agent owns generation and provider spending. A frozen evaluation pixel budget
bounds local raster allocation.

## Saved interventions and parent-agent handoff

A reviewer can save a correction against the current exact revision/evaluation
with `POST /v3/runs/RUN/interventions`. The JSON body contains `id`, `revision_id`,
`evaluation_id`, `desired_outcome`, a half-open authored `tick_range`, optional
native `roi`, and `authorize_edit_scope` (false by default). The saved action
creates a human-owned correction using the established correction status model,
a timeline event and an immutable feedback bundle. `handoff_id` identifies that
saved bundle. No copy action is offered for a transient selection.

`GET /v3/feedback/ID` returns the same bundle and concise text, a `stale` flag,
current revision/feedback identities and an explanation when bindings changed.
`GET /v3/feedback/ID/text` downloads exactly that rendered text. MCP
`agent_handoff_get(feedback_id)` and CLI `agent-handoff-get --feedback-id ID`
provide the same result. Evidence includes asset IDs, content hashes and project
blob/HTTP locations; access to the project is required. Pasted text is not a
credential. It includes actual import/submission operations, preservation rules,
expected bounds, full-matrix re-evaluation and remaining budget. Hidden provider
configuration and generation metadata are excluded from the renderer.

After another saved action or submission, old feedback cannot authorize a child
submission. A reviewer may explicitly request a new bundle with
`POST /v3/feedback/ID/rebase`, including `expected_revision_id` and
`expected_feedback_id`. Rebase records an event and reloads current requirements
and still-open human corrections; it does not silently change an old bundle.

Read a correction with `GET /v3/interventions/ID`, MCP `agent_intervention_get`
or CLI `agent-intervention-get`. Resolve/reopen with
`POST /v3/interventions/ID/resolve` or `/reopen`, passing `expected_version`, exact
`revision_id`/`evaluation_id` and optional `note`. Only its recorded owner can
resolve/reopen it. Resolution inspects an actual submitted replacement, while
technical success alone leaves the subjective correction open. Reopen restores
the task without replenishing submission or no-progress budgets.

An explicit edit grant freezes a preservation baseline and checks exact canonical
RGBA outside the union of saved authorized ranges/regions, including other
frames. A failed attempt cannot move this baseline; a preservation-passing child
can advance it. Markup without the grant is localization only. Initial generation
has no parent preservation baseline. Scoped child edits require a saved grant;
free text does not authorize broader edits or override execution limits.

Reviewer decisions use `POST /v3/runs/RUN/decisions` with `id`, exact bindings,
`action` (`approve`, `reject`, `needs_changes`) and optional `note`. Rejections and
change requests create unresolved corrections and saved continuation instructions.
Approval does not manufacture technical coverage or resolve open corrections.
The named human-reviewed policy checks the exact saved decision. Explicit-review
intervention policy also waits for a decision rather than ordinary automatic
completion.

Trusted CLI integrations use `agent-intervention-mark`,
`agent-intervention-resolve`, `agent-intervention-reopen`, and `agent-decision`
with an `--action JSON_FILE`, project/run or intervention IDs and a real reviewer
session (`--session-token` or `FRAMEBOUND_REVIEWER_TOKEN`). Browser writes use the
existing local reviewer session boundary. MCP agents can retrieve human work,
not mint reviewer authority.

Parent-agent satisfaction is a separate judgment: MCP
`agent_satisfaction_record`, CLI `agent-satisfaction-record --action JSON_FILE`,
or `POST /v3/runs/RUN/agent-satisfaction` binds `revision_id`, `evaluation_id` and
optional `note`. It neither creates human approval nor closes human corrections.
A new revision starts with unreviewed creative status, preserving prior judgments
as historical events.

## Run workspace

When a project has v3 runs, the default desk displays the run-based workspace.
Interventions contains saved unresolved corrections, blocked/missing-input runs
and exceptional decisions. An unreviewed automatically completed run does not
enter that queue. Timeline shows durable events grouped by project, including
machine/human/parent-agent sources; selecting a revision event opens that exact
revision. The latest/current and best revisions remain visibly distinct from
historical inspection. Ordinary runs appear without review packets.

The main film contains the candidate and aligned check/correction track, with
native pixels on neutral transparency backing. There is no empty reference lane.
Compare previous is explicit and verifies authored timing before synchronizing
playback. Contextual identity/style inputs are labeled by their actual role. The
first actionable chronological frame is selected and centered on opening; live
updates preserve inspection and unsaved correction text/region. Playback uses one
main stage and leaves inspector/strip selection stable; pausing adopts its stopped
frame once. Existing drag/elastic-end camera and zoom are reused.

The correction inspector supports shift-selected frames or authored half-open tick
ranges and native ROI drawing. Save precedes Copy instructions, and copy rechecks
the exact saved bundle before accessing the clipboard. Failure exposes selectable
text and a download of the same text; structured JSON is available. Decision and
owner resolve/reopen actions use the same reviewer session as the reviewed-guide
workspace. Reviewed-guide projects remain accessible through the existing routes
and More workspaces, without converting old approvals to v3 labels.

Read-only run documentation is available at `GET /v3/desk` and
`GET /v3/desk/revisions/REVISION`. The real browser acceptance script is
`node web/e2e/agent-workflow.mjs`; it launches a separate API process and drives a
saved native markup through clipboard/download, a separate parent-agent CLI
repair, exact owner resolution/reopen, historical event navigation, comparison,
stable playback, live-update preservation and clipboard fallback.

## Portable training export

Manual v3 export extends the existing `build_snapshot`/`validate_snapshot` path
and crash-recoverable publisher. Selecting a v3 revision includes its complete
run trajectory, ordered revisions, task predecessors, optional inputs, frame
instances, registrations, generation metadata, evaluations, feedback, events,
human interventions and completion records. It needs no motion guide or invented
reference row. Dataset version 3.0 advertises explicit reader capabilities;
reviewed-guide 2.3 snapshots retain their original publisher and labels. Export
v2/v3 selections in separate snapshots rather than mixing their label semantics.

The export screen selects runs grouped by project, a snapshot name, the versioned
`agent-training-v1` policy and an optional destination. Preview counts, exclusions
and withheld pixels precede publication. Export does not run automatically when
an animation completes. Publication freezes the project database, validates the
staging directory and atomically publishes it using the established recovery
journal. Export records are versioned separately from v2 records.

`POST /v3/exports/preview` and `POST /v3/exports` accept:

```json
{
  "name": "training-1",
  "run_ids": ["run-1"],
  "policy_id": "agent-training-v1",
  "include_automatically_verified": true,
  "include_procedural_positives": false,
  "rights_allow": ["original"],
  "destination": null
}
```

CLI `agent-export-preview`/`agent-export-build` take `--project` and
`--selection JSON_FILE`; MCP exposes the corresponding underscore names with a
`selection` object. The existing CLI `dataset-validate` and shared validator accept
both snapshot versions. `/v3/reader-capabilities` advertises supported versions
and label views. A false string is not accepted as a true/false policy value.

- `hf/` contains only current exact human-approved, technically complete, fresh,
  rights/origin-eligible frames with no unresolved human correction. It is never
  populated from automatic success or agent satisfaction.
- `automatically_verified/` is a separate opt-in imagefolder view for complete
  passing output under the automatic policy. Metadata says `technical_policy`,
  retains creative status and records the exact evaluation, digest, completion
  policy and measurement-assumption sources.
- `research/` retains nonaccepted/failed/partial examples with actual exclusion
  reasons. `withheld` records retain metadata when rights or missing bytes prevent
  packaging pixels. Derived and conditioning ancestry retain their exclusions.
- `trajectories.jsonl` records the failed parent, targeted saved feedback,
  candidate, changed slots, check outcomes and overall regressions. Improvement
  at a target is not substituted for overall success.
- `preferences.jsonl` contains only the explicit same-task reviewer comparisons
  described below; `weak_preferences.jsonl` remains empty. Without that comparison
  record both views stay empty; revision order and automatic rankings do
  not create human preference pairs. Existing v2 explicit comparisons continue
  through their strict reviewed-guide route.

`temporal.jsonl` retains ordered native pixels, authored holds and declared timing;
missing generation/provider metadata stays missing. `closure/asset_files.json`
resolves saved asset IDs to packaged content-addressed pixels. Raw feedback keeps
its original evidence rather than rewriting old hashes to destination paths.
Provider origin and structured generation briefs are retained when stored;
hidden provider settings and sensitive credential fields are omitted/redacted,
with omissions explicitly recorded. Procedural and simulated origins are never
silently relabeled as real generated art.

COCO annotations use the existing exact alpha-mask RLE encoder and validator.
All three imagefolder views carry their own label-source metadata. The explicit
v3 consumer `framebound.v2.exports.agent_reader.load_examples(path, view)` validates
the snapshot and materializes pixels for the requested view. A reader that does
not advertise the new label semantics rejects the snapshot. The existing
reviewed-guide preference consumer rejects v3 rather than loading automatic
examples as human comparisons.

Split components group run/animation ancestry, shared inputs, exact pixel
identities and conservative 64-bit dHash near-duplicate components (distance at
most four). Strict split policy rejects a family crossing train/dev/test;
exclude policy retains research evidence but removes conflicting trainable rows.
The hash grouping is a leakage precaution, not a quality metric.

Moved-snapshot validation needs no original database: it checks files and pixel
hashes, remeasures supported declared-region checks, verifies exact preservation
outside saved grants, checks task/evaluation/feedback and completion bindings,
verifies human resolution/acceptance sources, reconstructs split relationships,
and checks that trajectory outcomes reflect actual whole-clip results. Tests
include rehashed false-human-label tampering, withheld rights, mixed human and
technical sources, missing metadata, input closure, source-origin redaction and
family-safe split rejection. The browser journey exercises preview, publication
and validation after moving a snapshot.

New evaluations also record their actual evaluator source hash and Python/NumPy/
Pillow identities. Earlier v3 evaluations missing this identity remain historical
evidence; exports retain them as research rather than retroactively strengthening
their training eligibility. New evidence uses `declared-regions-v2`; stored task
negotiation and earlier evidence are never rewritten.

## Optional known-good enhancement and interpolation

A task may bind `source_correspondence` to a source sequence. This is an explicit
source designation with `designated_by`, `designation_basis` and `provenance`,
not inferred human acceptance or automatic promotion of a previous revision.
The source names its `frame_asset_ids`, original `timing` and `loop` behavior,
optional actual `source_revision_id`, declared enhancement/interpolation `goal`,
complete `time_map` and `protected_keys`. If a stored v2/v3 revision is named, its
actual pixels, timing and loop behavior must match this declaration.

```json
{
  "frame_asset_ids": ["source-0", "source-1", "source-2"],
  "timing": {"ticks_per_second": 30, "holds": [4, 4, 4]},
  "loop": true,
  "designated_by": "parent-agent",
  "designation_basis": "User designated this sequence as the enhancement source",
  "provenance": "Imported source animation",
  "goal": "enhancement_and_interpolation",
  "time_map": [
    {"source_tick": 0, "output_tick": 0},
    {"source_tick": 12, "output_tick": 24}
  ],
  "protected_keys": [
    {"source_tick": 0, "output_tick": 0, "preservation": "alpha_geometry"},
    {"source_tick": 4, "output_tick": 8, "preservation": "alpha_geometry"},
    {"source_tick": 8, "output_tick": 16, "preservation": "alpha_geometry"}
  ]
}
```

For output timing `{ "ticks_per_second": 60, "holds": [4,4,4,4,4,4] }`,
this preserves a 0.4-second source while adding three drawings. Time points use
exact rational arithmetic, not array index. Source/output maps must cover both
complete durations, be strictly increasing and preserve real-time timing; this
profile does not silently retime motion. Loop/terminal behavior must match. Every
original source drawing start needs an explicit protected output key at an actual
output drawing start, agreeing with the frozen time map. Changed timing or source
keys require a new valid task specification; they cannot be edited mid-run.

`exact_pixels` compares native canonical RGBA. `alpha_geometry` preserves the exact
alpha channel while permitting palette/texture changes. Either rule may be scoped
to a native ROI. Detail enhancement therefore does not blindly require palette or
whole-image color similarity. Missing source evidence produces required-unmeasured
fidelity, with re-import/recovery feedback. It cannot obtain automatic success.
Generation-input compilation returns the resolvable source assets and their hashes.

Compare known-good source is explicit in the workspace. Its film projects source
hold intervals onto the candidate's authored timeline; protected-key and source
motion-interval correspondence remain visible. Synchronized playback uses that
same map, including unequal frame counts and tick rates. An inserted frame never
claims exact same-frame source authority. Candidate-only viewing remains default.

Snapshots retain source designation, pixels, protected keys, correspondence and
source-record hashes. A named v3 source also brings its dependency trajectory into
closure; source-only dependencies stay research unless separately selected for
training. V2 source records retain their original schema identity without inventing
guide approval. The `source-correspondence-v1` reader capability is advertised when
needed. Older v3 snapshots without optional source records still validate. Moved
validation independently checks key fidelity and authored correspondence against
packaged source/candidate pixels.

This establishes the declared preservation and timing checks. More inserted
frames are not a fluidity score, and alpha/pixel anchors do not prove motion,
contact or camera behavior outside the explicitly evaluated requirements. Required
region/contact/event checks remain part of the full task matrix.

## Camera, occlusion and interacting-subject milestone

The provisional `tracked-scene-v1` profile adds frozen `scene` declarations with
up to 16 subject IDs, one explicit 2D camera transform per authored frame, and
frame-local feature ROIs with exact RGBA/count bounds and expected world anchors.
Every subject needs a visible/occluded/ambiguous declaration for every frame. The
camera's translation and uniform scale compensate measured feature centroids
before world-anchor and temporal-link checks. No perspective or 3D camera solver
is implied.

`scene.features` retain their source/provenance; an occluded feature makes no
visible-location claim. Ambiguous required evidence is unmeasured and blocks
completion. A required temporal link through an unobservable endpoint is also
unmeasured; an explicitly advisory link remains advisory rather than silently
becoming a required pass. The profile requires actual track, temporal and event
measurement families, so missing declarations do not yield a quality pass.

`scene.events` bind simultaneous feature IDs to contact/separation or left-of/
above constraints with authored world-distance bounds. A stable, correctly tracked
scene can still fail the specified interaction event. Landmark contact/order is
an image-space measurement: physical forces, hidden contact, anatomy and arbitrary
narrative semantics remain unsupported. Source/model-proposed camera or landmark
assumptions retain their provenance and do not validate their own semantic meaning.
The engine makes no internal generative/model calls.

`max_measurement_pixels` is a frozen run limit in addition to raster allocation
and submission limits. It bounds the summed declared-region measurement work;
an oversized declaration is rejected before registering a submission or spending
its budget. No internal retry loop can bypass the parent agent's run limits.

The procedural scene suite includes legitimate translation/scale changes,
intentional occlusion, two-subject contact/order, discontinuous motion, feature
loss/duplication and an incorrect event despite individually tolerated feature
positions. Fail→repair→pass and moved-snapshot reproduction use the same stored
matrix. The source/dependency identity and limitations are retained in scene
evidence and the `declared-color-camera-tracks-v1` portable-reader capability.
These fixtures are engineering evidence, not real generated-art reliability.

### Offline quality benchmark

`framebound animation-quality-benchmark --manifest CORPUS_JSON` executes a
versioned local corpus without provider calls. `schemas/v3/quality_benchmark.schema.json`
describes cases containing task specifications, relative asset paths, ordered
candidate asset IDs, independent expected defect/check IDs and frame/ROI labels,
complete/partial-label coverage, art origin, label source/provenance and held-out/
development split. Optional `repair_of` links assess actual after-outcomes and
new regressions separately from target improvement. Asset files must resolve
inside the corpus directory.

The report retains exact task/evaluation/asset identities and reports true/false
positives, misses, exact frame localization, frame IoU and available region IoU.
Unmeasured/tool errors are distinct from detected candidate defects. Precision
is not invented for partially labeled cases. Imported human-label declarations
are evidence with provenance, not authenticated reviewer decisions or training
acceptance. The report explicitly lists when independently human-reviewed held-out
image-generated cases are absent. No general accuracy claim follows merely from
procedural benchmark success. Broader real-art validation remains required before
promoting this provisional profile to a reliable general animation-quality claim.

## Explicit task changes and durable stops

`agent-run-revise-task --project PROJECT --run-id RUN --task-id NEW_TASK
--expected-version VERSION`, MCP `agent_run_revise_task` or
`POST /v3/runs/RUN/task-revision` applies a stored direct superseding task with its
recorded reason. Prior task/evaluation/feedback/completion records stay immutable.
The run's explicit task-change event and new feedback identify the new task and
its digest separately from the previous baseline evidence; an old failure is not
reclassified as a pass. Best selection is retained by task and restarted for the
new requirement matrix, rather than comparing scores across different policies.

The same spent attempts, fingerprints and no-progress counts persist. New limits
can reduce remaining capacity but cannot raise it. Exhausted/cancelled runs cannot
be revived through a specification change or another run name. Timing/canvas
changes cannot silently retarget unresolved human corrections. The workspace
labels an inspected previous-task result while awaiting a new-task submission.
Identical old submissions can still retrieve their immutable replay result after
a later task revision; replay spends no new budget.

Cancellation supersedes saved continuation instructions with an explicit stopped
bundle and a state-fetch operation. It does not leave an apparently live repair
instruction attached to a cancelled run. Timeline evaluations record their best
selection outcome and distinguish retained earlier results from selected current
ones.

## Disconnected handoff and returned correction

Download portable handoff in the saved-action control packages `manifest.json`,
`instructions.txt` and hashed native PNGs. The instructions use the same renderer
as connected feedback, but name packaged asset locations and the actual return/
import procedure rather than requiring inaccessible MCP IDs. Task versions,
baseline/preservation pixels, evidence, rights/origins and limits are included;
provider settings and unrelated generation metadata are excluded. The packet is
not an authorization token and does not grant training or execution rights.

CLI `agent-handoff-export --project PROJECT --feedback-id FEEDBACK --out FILE.zip`
and MCP `agent_handoff_export` produce the same archive. The HTTP route is
`GET /v3/feedback/FEEDBACK/portable`. Oversized or unavailable pixel closure is
reported as a blocker rather than packaged with invented evidence.

The external agent works from the unpacked packet and returns a `response.json`
with a new `revision_id`, complete ordered `frames` list and actual optional
`generation_metadata`. Each frame is either `{ "asset_id": "unchanged-id" }` or
`{ "file": "corrected.png", "rights": "unknown", "source_kind": "generated" }`.
Paths are relative to the response directory. Rights default to unknown, not an
invented original-art grant. See `schemas/v3/portable_response.schema.json`.

`agent-handoff-import --project PROJECT --manifest manifest.json --response
response.json`, or MCP `agent_handoff_import`, checks the saved packet against the
current durable project bindings, imports changed pixels, enforces edit support
and evaluates the whole clip. Path escapes and changed task/evidence bindings are
rejected. Identical replay returns the same result; a stale packet cannot target
a different current revision.

## Explicit human preference records

Ordinary approval, comparison playback and newer revision order never imply a
preference pair. While explicitly comparing a previous same-task revision, a
reviewer can select “Explicitly prefer this revision over …” and approve. The
saved decision includes exact `comparison_revision_id` and
`comparison_evaluation_id` in addition to the chosen revision/evaluation. Both
must be distinct actual candidates for the same frozen task.

The record is separate from artistic acceptance, technical ranking and correction
status. Export includes a pair only while its exact chosen approval remains
current and human-positive, with permitted rights/origin and no unresolved human
correction. The rejected pixels and both evaluations remain bound to the explicit
human choice. Later rejection/needs-changes removes the pair from a fresh
trainable export while preserving its historical record.

Snapshots advertise `explicit-human-preferences-v1`; the v3
`agent_reader.load_preferences(path)` validates and materializes common-task,
chosen/rejected pixels with the original label source. Earlier v3 snapshots with
no optional comparison closure still validate, and legacy v2 preference readers
continue to reject unsupported v3 semantics rather than guessing.

Feedback bundle version 2 adds deterministic correction groups. Related symptoms
sharing authored frames/regions can share a suggested repair scope while their
individual check results remain intact. Tool/evidence recovery, candidate defects
and human-owned corrections are kept distinct; grouping never grants extra edit
support or closes an owner's correction. An unmeasured continuity result caused
by an already-failed visible feature links to that actual prerequisite, rather
than instructing the parent to re-import otherwise readable media. Older saved
bundles retain version 1 semantics and their original evidence. Portable snapshots
advertise `feedback-groups-v2` when needed and verify group membership against the
saved targets.

Current output eligibility rechecks the candidate, bound known-good source and
contextual input assets, including their immutable asset records and byte hashes.
Loss of an evidence dependency withholds current output even though the historical
evaluation remains a recorded pass. Restoring the exact content-addressed bytes
restores eligibility without fabricating a new artistic decision. The inspector
shows this named output-policy result separately from evaluation and creative
status, and identifies when it applies to a different current best revision.


Parent-reported execution failures are durable even before the first candidate.
Use CLI `agent-run-report-failure --project PROJECT --run-id RUN --report report.json`,
MCP `agent_run_report_failure(run_id, report)` or `POST /v3/runs/RUN/failures`.
A report has a stable `id`, `kind` (`provider_failure`, `tool_error`, or
`missing_input`), actual `reason`, strict boolean `outcome_known`, and optional
`provider`/`external_request_id`. Identical replay returns the original event and
feedback; reusing an ID for another report fails. These are explicitly parent
reports, not independently observed provider receipts, reviewer actions or grants
to spend. No reporting operation dispatches a provider.

`max_external_failures` (default 8) and `max_provider_failures` (default 3) persist
across restarts and task revisions alongside submission/compute limits. An unknown
provider outcome stops the run immediately without advertising a blind retry;
neither a task change nor a creative approval clears that execution stop. Known
failures within budget return concrete recovery/state instructions. Before pixels
exist the saved handoff records no baseline, evaluation or fabricated defect.
Compile task inputs after recovery, import the complete frame list, then bind the
first submission to that current `feedback_id`. No pixel-repair ZIP is offered
until there is a candidate; the same saved recovery text remains copyable and
downloadable. Cancellation and explicit task changes supersede these instructions
without rewriting the original report. Snapshots retain the full report/feedback
history and advertise `pre-submission-feedback-v1`; validators check its actual
parent source and absence of invented evaluation evidence.
