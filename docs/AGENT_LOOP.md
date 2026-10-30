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
Task rebinding and negotiated broader permissions require an explicit future
operation; starting another run is not a workaround.

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
- `preferences.jsonl` and `weak_preferences.jsonl` stay empty for v3 until an
  explicit comparison record exists; revision order and automatic rankings do
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
