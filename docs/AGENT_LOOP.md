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
