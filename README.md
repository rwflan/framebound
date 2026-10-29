# Framebound

Consistency bounds for AI-generated 2D animation.

Image models produce a good style frame. They do not reliably hold a character's shape, size, movement, or appearance across dozens of frames of a specific action. Framebound gives the orchestrating model a frozen contract and deterministic tools to check its own work, repair only what failed, and send the rest to a human — with every result exported as training data so the model needs this less over time.

Built for the Meta Global AI Developer Hackathon (Indie track, Build for Your World). See [docs/HACKATHON.md](docs/HACKATHON.md).

## How it works

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
# desk dev: cd web && npm install && npm run dev   (proxies /api to :8765)
# v1 prototype still works: python -m framebound demo --out build/demo
```

Review works directly in the local browser. A same-origin, loopback-only HttpOnly session is managed automatically; model actor headers remain separate from reviewer credentials. Live provider calls need `MODEL_API_KEY` plus an explicit `FRAMEBOUND_SPEND_CEILING`, otherwise
`scripts/verify-local --live` stays pending with the exact command.

Open http://127.0.0.1:8765 for the review desk.

The desk opens on project interventions. Browse sequences and recorded history on a draggable film reel, zoom aligned reference/candidate frames, and inspect measurements and correction status directly beneath the frames. Review dialogs provide authored-tick playback, native-pixel issue regions, exact-evaluation decisions and release eligibility. See [the review workflow](docs/REVIEW_DESK.md).

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

## Licence

MIT. Demo art is procedural and original. Do not add third-party game assets.
