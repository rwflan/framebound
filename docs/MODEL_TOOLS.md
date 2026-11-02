# Model-facing tools

The external orchestrator uses the CLI or MCP stdio server. Humans use the persistent review desk for exceptional feedback, comparisons and decisions. Built-in animation guidance is compiled into generation inputs; it is not a general-purpose critic or a claim of artistic acceptance.

```sh
framebound v2-mcp --project PROJECT
framebound capabilities --project PROJECT
```

The MCP server uses the official SDK handshake and actual tool discovery. Enumerate its tools rather than copying a historical catalogue. All transports call the same application services; current capability and pending-evidence states are available at `/api/capabilities`.

## Generate with your harness — no training required

Most users should start here. Connect the stdio server to your harness:

```json
{"mcpServers":{"framebound":{"command":"framebound","args":["v2-mcp","--project","/absolute/path/to/animation-project"]}}}
```

1. Call `create_animation` with `request` containing a stable `id`, `intent` and
   `subjects`. Optional settings are `appearance`, `canvas`, `holds`,
   `ticks_per_second`, `loop` and existing immutable reference `inputs`. Defaults
   are six 256×256 frames, two ticks per frame at 12 ticks/second, looping.
2. Use the returned compiled guidance, original references and declared shared
   camera to generate **one complete pose screen** with your harness's image tool.
   Generate distinct ordered poses, keeping every subject inside its declared cell.
   Framebound does not issue a hidden provider request or require you to train a model.
3. Call `submit_animation_sheet` with the returned `run_id`, a stable unique
   `revision_id`, an absolute `sheet_path`, and `columns`/`rows` whose product equals
   the frozen hold count. Six, twelve and twenty-four pose screens use the same
   path. The sheet must be a non-oriented PNG with real alpha and dimensions at
   most 2048×2048. Every cell shares the frozen canvas aspect ratio. Cutting is
   row-major; an explicitly recorded common scale applies to all cells, never a
   separate fit or zoom per pose. Originals and transformation hashes are retained.
4. If the generator returns opaque backing, use your harness to segment **the
   whole screen once**, retain its raw output and receipt, and submit the resulting
   alpha sheet with `original_sheet_path` identifying the original PNG. Framebound
   never guesses that white subject pixels are scenery. Clipped, scenic and
   unsuitable alpha remains an intake failure rather than a quality verdict.
5. Read `get_generated_animation`. Follow its saved feedback and returned
   `next_action` for a correction; bind the exact current `parent_revision_id` and
   `feedback_id`. Use original identity references rather than accumulating edits
   as the sole reference. A retry with the same revision and unchanged submission
   is a read-only replay; changed bindings are rejected. Report an unknown external
   provider outcome with `agent_run_report_failure` and never blindly send it again.
6. Call `export_generated_animation` when eligible. It publishes hashed native PNG
   frames, a sprite strip and the authored clock in `manifest.json`. Structural
   completion does not certify animation semantics or grant human approval. Stronger
   measured requirements can be declared with the existing task observations/profile.

Example initial call:

```json
{"request":{"id":"fox-walk","intent":"A fox walks in place through a complete cycle","subjects":"One original isolated 2D fox","appearance":"Flat warm orange coat and dark paws","holds":[2,2,2,2,2,2],"ticks_per_second":12}}
```

Meta/Modal credentials and custom model training are optional advanced product
features, separate from this external-harness generation path. Provider receipts
and attribution reported by a harness remain external assertions unless locally
verified; guidance, technical checks, creative satisfaction and human approval have
separate authority.

## Legacy reviewed-contract creation

```sh
framebound project-create --project PROJECT --project-id PROJECT_ID --name NAME
framebound asset-import --project PROJECT --src FILE --asset-id ASSET_ID
framebound character-propose --project PROJECT --character character.json
framebound guide-propose --project PROJECT --guide guide.json
framebound contract-propose --project PROJECT --contract contract.json
framebound clip-create --project PROJECT --contract-id CONTRACT --revision-id REVISION --frames ASSET_IDS --phases PHASES
```

MCP provides `project_create`, `asset_import`, `character_propose`, `guide_propose`, `contract_propose` and `clip_create`. Create a stored project and character, distinct identity/style inputs, independent phases and an immutable guide. The desk reviewer approves the exact art, support, calibration and repair policy. The orchestrator cannot approve or revoke that authority through a model tool. See [the native sprite profile](NATIVE_SPRITE_PROFILE.md) for the required inputs and unsupported cases.

## Automatic work

```sh
framebound animation-compile --project PROJECT --contract-id CONTRACT
framebound animation-start --project PROJECT --revision-id REVISION --idempotency-key WORK
framebound animation-step --project PROJECT --run-id RUN
framebound animation-get --project PROJECT --run-id RUN
framebound animation-run --project PROJECT --revision-id REVISION --idempotency-key WORK
```

MCP exposes the matching compile/start/step/get operations. `animation-run` is a bounded CLI convenience loop. Consume returned diagnostics and persisted state. Deterministic native operators execute within approved controls. Only a complete passing candidate reaches `technically_ready`; its artistic acceptance remains unreviewed. Unsupported or missing measurements return a specific blocker. Do not replenish grants by renaming contracts or request keys.

A supported per-frame fault may queue scoped redraw and return `awaiting_provider` with its durable job ID. Default work is offline. An authorized live start uses frozen provider settings and an existing operator grant. Use the normal `job_get` / `orchestrator_run` / `orchestrator_send` services, then resume `animation_step`. Reference, source, phase and support images are transmitted; the framework composites the proposed result and independently rechecks it. Optional SAM proposals never grant artistic approval or repair authority.

Unknown upstream outcomes require operator reconciliation, never blind resubmission. Models do not mint grants or recovery receipts. See [provider recovery](PROVIDER_RECOVERY.md) and [provider contracts](PROVIDER_CONTRACTS.md).

## Human feedback and training

The desk's ROI/frame-range issue becomes a durable task. Consume `corrections_list`, claim through `correction_claim`, submit the exact scoped result through `correction_submit`, and retain the returned comparison identity. Claims are fenced and payload replay must be identical. The reviewer compares, resolves or reopens subjective issues. A technical improvement does not resolve artistic feedback automatically.

Export through the desk/API or CLI and validate the moved snapshot. Positive membership requires current eligible decisions, rights and origin. Simulated or unresolved ancestry is retained as explained research material rather than promoted into positives. Preference data requires an explicit comparison packet. See [snapshot consumption](SNAPSHOT_CONSUMPTION.md) for a decoded native-pixel batch.

The v1 file-oriented `check`, `preflight`, `repair-plan`, `repair-evaluate` and `mcp` commands remain compatibility paths. New durable workflows use `v2-mcp` and the services above.
