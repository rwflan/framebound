# Agent task registration (v3)

The additive v3 task API accepts intent without a motion guide, character record,
phase drawing or reviewer approval. It stores an immutable specification and its
negotiated capabilities. Existing v2 reviewed-guide contracts and exports retain
their original semantics.

Create a project with `framebound project-create`, then save this JSON as `task.json`:

```json
{
  "id": "walk-task-1",
  "project_id": "project-1",
  "animation_id": "walk",
  "intent": "A character walks to the right",
  "subjects": "one character",
  "canvas": {"width": 128, "height": 128},
  "timing": {"ticks_per_second": 60, "holds": [6, 6, 6, 6]},
  "profile": "structural-v1"
}
```

```sh
framebound task-migration-report --project ./project
framebound task-create --project ./project --spec task.json
framebound task-get --project ./project --task-id walk-task-1
framebound task-compile-inputs --project ./project --task-id walk-task-1
```

MCP exposes `task_create(spec)`, `task_get(task_id)` and
`task_compile_inputs(task_id)` over the same services. HTTP exposes
`POST /v3/tasks`, `GET /v3/tasks/{task_id}` and
`GET /v3/tasks/{task_id}/inputs` through the local API's existing security boundary.

Optional inputs name imported asset IDs, an explicit role, provenance, designating
actor and basis. An identity/style/design proposal is not a motion reference or
human acceptance. Keyframe coverage uses half-open authored tick intervals.
Compilation checks the current availability and hash of the bound input pixels.
It returns the complete specification, exact digest and capability gaps for an
external generator. It does not authorize Framebound provider execution.

Task IDs are immutable and replayable. A changed specification needs a new ID,
`supersedes` and `change_reason`; the predecessor must belong to the same project
and animation. Policies, limits and negotiated requirements are frozen in each
record. A run binds exact task versions and retains its budget across explicitly recorded
specification revisions. `agent-run-revise-task` applies a direct superseding
specification with version checks; it cannot replenish attempts or erase earlier
evidence. Task registration itself does not start a run.

The first registration adds a separate `agent_task_specs` table and backs up the
pre-v3 database to `backups/before-agent-v3.sqlite3`. The dry-run report opens an
existing database read-only and never creates a project. No v2 data or labels are
rewritten. JSON schemas are in `schemas/v3/`.

The [external-agent loop](AGENT_LOOP.md) now implements immutable submissions,
declared-region evaluation, durable feedback, bounded stopping and automatic
technical output policy. Unsupported quality requirements remain explicit gaps.
The narrower methods and procedural benchmark do not establish arbitrary
animation quality or human acceptance.
