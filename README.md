# Framebound

Consistency bounds for AI-generated 2D animation.

Framebound is the checking, feedback and evidence layer for an external animation agent. The agent starts from intent and optional appearance/source inputs, supplies native image-generated frames, receives localized measurements and correction instructions, then submits immutable child revisions within persistent limits. Creative judgment and human acceptance remain separate from technical checks.

Built for the Meta Global AI Developer Hackathon (Indie track, Build for Your World). See [docs/HACKATHON.md](docs/HACKATHON.md).

Product direction: [agent-led animation workflow plan](docs/AGENT_ANIMATION_WORKFLOW_PLAN.md) — reference-optional generation and correction, actionable agent feedback, exceptional human intervention and training-data export. The reference-free agent loop, live workspace and portable trajectory exporter are implemented. Known-good enhancement/interpolation is optional. The tracked-scene milestone is provisional; independently reviewed generated-art validation remains pending. See [the implementation audit](docs/AGENT_WORKFLOW_IMPLEMENTATION_AUDIT.md).

## Agent-led workflow

1. Register an immutable v3 task: intent, native canvas/timing, optional inputs, measurable requirements, completion policy and limits. Unsupported requirements stay explicit gaps.
2. Generate art with the parent agent's own tools, import the PNGs, and submit a revision through CLI, MCP or HTTP. Framebound does not require a motion guide or reviewer event.
3. Consume one durable feedback bundle: exact evidence, affected frames/times/regions, observed/expected values, preservation rules, remaining budget and actual continuation operations.
4. Submit corrections against current saved bindings. The full matrix is rechecked, earlier best results are retained, and restarts, repeated outputs or a new run name cannot reset limits.
5. Inspect the run timeline and candidate-first film. Save exceptional markup/decisions, copy instructions, or download a self-contained handoff for an agent without project access. Human corrections require explicit owner resolution.
6. Manually export portable trajectories and separate human-accepted, automatically verified, research and withheld views. Revision order never creates human preferences.

Start with [agent task creation](docs/AGENT_TASKS.md) and [the complete agent loop](docs/AGENT_LOOP.md). Structural checks do not verify animation quality; declared-region/track checks cover their explicit inputs and limits. Arbitrary anatomy, perspective, hidden physics and prose action correctness are not solved by those measurements.

## Existing reviewed-guide profile

1. **Contract.** One approved master, one native canvas, locked frame holds, frozen phase references, declared contacts, anchors, and visible features. Everything hash-bound.
2. **Check.** Deterministic raster checks per frame: silhouette area/width/height vs the same phase, phase correspondence, visible-feature span and pulse, palette drift, support contacts, anchor drift, centroid steps, cadence. Named issue codes, no prose parsing. Unknowns are reported unmeasured, never passed.
3. **Brief.** Generation briefs bind master + identity + phase + neighbours by SHA-256. A previous edit is never the sole reference; rejected paths are forbidden inputs.
4. **Repair.** Compile reviewed bounds and execute native translation or protected restoration. Other measured faults can queue scoped image work. Persist every attempt, preserve protected pixels and re-evaluate the full revision. Only complete passing results become technically ready; artistic approval remains human.
5. **Review.** A persistent web desk for the human: playback at true holds, frame metrics, issue marking, approve/reject. Open issues become machine-readable correction tasks for the model.
6. **Export.** COCO annotations, a Hugging Face imagefolder dataset, chosen/rejected preference pairs, and clip timing — the training data that makes this framework obsolete.

Framebound itself compiles approved controls, measures failures, applies authorized native repairs and verifies the resulting pixels. An external orchestrator uses the CLI or MCP tools. Muse Image generation/edit and SAM segmentation are optional bounded specialists; there is no internal general-purpose adviser or critic. See [docs/DESIGN.md](docs/DESIGN.md) and [docs/PROVIDER_CONTRACTS.md](docs/PROVIDER_CONTRACTS.md).

Start with [automatic repair](docs/AUTOMATIC_REPAIR.md), [portable training consumption](docs/SNAPSHOT_CONSUMPTION.md) and the [current evidence matrix](docs/IMPLEMENTATION_STATUS.md). The public browser journey exercises creation, automatic repair, restart, review and moved export without domain-row inserts.

## Quick start

Python 3.11+. Reproducible install (no machine-specific URLs; the lock stays portable):

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e '.[test,export-validation]'
pip check                                            # must report no broken requirements
npm --prefix web ci --ignore-scripts && npm --prefix web run build
python scripts/sync_desk_build.py                    # stage the desk into the package
python -m framebound doctor                          # project + dependency self-check
```

```sh
sh scripts/verify-local                        # offline P0 checks (live providers opt-in, skipped honestly)
python -m framebound demo --profile wp6 --offline --out build/wip6   # Pip: 4 clips pass
python -m framebound serve --project build/wip6/project --port 8765  # desk at http://127.0.0.1:8765
# desk dev: cd web && npm install && npm run dev   (proxies /api and /v3 to :8765)
# v1 prototype still works: python -m framebound demo --out build/demo
```

Review works directly in the local browser. A same-origin, loopback-only HttpOnly session is managed automatically; model actor headers remain separate from reviewer credentials. Live provider calls need `MODEL_API_KEY` plus an explicit `FRAMEBOUND_SPEND_CEILING`, otherwise
`scripts/verify-local --live` stays pending with the exact command.

Open http://127.0.0.1:8765 for the review desk.

The desk opens on interventions grouped by project, with chronological history and keyboard sequence search. Each animation selects and centres its first frame needing attention. The candidate film sits above a separate check/correction track, with compact opaque tabs and a contextual inspector. Previous revisions or designated known-good sources appear only in explicit comparisons using valid authored-time correspondence. Playback uses one main stage and keeps inspection still until paused. Drag and trackpad overscroll spring back to padded film ends. Review dialogs retain exact tick playback, native-pixel regions and server-derived release eligibility. See [the review workflow](docs/REVIEW_DESK.md).

## Model-facing tools

CLI (JSON in/out) and MCP (stdio) expose the same operations: `check`, `brief`, `preflight`, `repair-plan`, `repair-evaluate`, `record-failure`, `export-dataset`. See [docs/MODEL_TOOLS.md](docs/MODEL_TOOLS.md).

v2 adds typed services on the same pattern (`asset-import`, `contract-propose`, `clip-create`, `clip-evaluate`, `brief-compile`, `job-submit`, `correction-submit`, `export`, …), an MCP server (`v2-mcp`), and a FastAPI review desk (`serve`). See [docs/MODEL_TOOLS.md](docs/MODEL_TOOLS.md).

```sh
python -m framebound doctor
python -m framebound migrate-v1 --source path/to/v1demo --dry-run
python -m framebound asset-import --project proj --src img.png --asset-id a-01
python -m framebound clip-evaluate --project proj --revision-id clip-01
python -m framebound brief-compile --project proj --contract-id c-01 --slot 2
python -m framebound export --project proj --snapshot s1 --out build/s1 --revisions clip-01
python -m framebound dataset-validate --snapshot build/s1
python -m framebound v2-mcp --project proj   # MCP stdio (same services as CLI/HTTP)
# v1 prototype tools (check/brief/preflight/repair-plan/repair-evaluate/mcp) unchanged
```

Live specialist work additionally requires genuinely approved references, an operator grant, a frozen live request and an explicit spend ceiling. Offline jobs never send, even when a key is present. Participant live proof is pending; see [provider recovery](docs/PROVIDER_RECOVERY.md).

## Corpus research

The [local Muse corpus workflow](docs/MUSE_ANIMATION_CORPUS_PLAN.md) covers external Muse generation, typed attribution, immutable correction ancestry and portable model supervision. All corpus media, reference identities and receipts live outside the repository. Human oversight is optional; model labels retain their source and uncertainty.

## Licence

Code: MIT. Procedural demo art is original. Downloaded research references retain their recorded source licences and credits; they are not demo art or Muse-generated benchmark outputs. Publisher screenshots are research references, not an automatic generation or training grant.

For staged generation, scoped model assessment, automatic correction and feature-only learning experiments, see [Local animation campaigns](docs/ANIMATION_CAMPAIGNS.md).
