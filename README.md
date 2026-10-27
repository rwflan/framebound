# Framebound

Consistency bounds for AI-generated 2D animation.

Image models produce a good style frame. They do not reliably hold a character's shape, size, movement, or appearance across dozens of frames of a specific action. Framebound gives the orchestrating model a frozen contract and deterministic tools to check its own work, repair only what failed, and send the rest to a human — with every result exported as training data so the model needs this less over time.

Built for the Meta Global AI Developer Hackathon (Indie track, Build for Your World). See [docs/HACKATHON.md](docs/HACKATHON.md).

## How it works

1. **Contract.** One approved master, one native canvas, locked frame holds, frozen phase references, declared contacts, anchors, and visible features. Everything hash-bound.
2. **Check.** Deterministic raster checks per frame: silhouette area/width/height vs the same phase, phase correspondence, visible-feature span and pulse, palette drift, support contacts, anchor drift, centroid steps, cadence. Named issue codes, no prose parsing. Unknowns are reported unmeasured, never passed.
3. **Brief.** Generation briefs bind master + identity + phase + neighbours by SHA-256. A previous edit is never the sole reference; rejected paths are forbidden inputs.
4. **Repair.** Bounded only: declared region, protected regions, whole-batch evaluation. A candidate reaches human review only if it strictly improves and leaves zero errors. Nothing auto-promotes.
5. **Review.** A persistent web desk for the human: playback at true holds, frame metrics, issue marking, approve/reject. Open issues become machine-readable correction tasks for the model.
6. **Export.** COCO annotations, a Hugging Face imagefolder dataset, chosen/rejected preference pairs, and clip timing — the training data that makes this framework obsolete.

Meta models in the loop: Muse Image generates under briefs, SAM 3.1 supplies masks, Muse Spark/Wonder orchestrate and critique. Deterministic checks remain the gate; model opinion never overrides a failed bound. See [docs/DESIGN.md](docs/DESIGN.md).

## Quick start

Python 3.11+. Core: `pip install -e .` (pydantic, Pillow, numpy, mcp, fastapi, uvicorn). Export validation: `pip install -e '.[export-validation]'` (datasets, pycocotools). Desk: `cd web && npm install`.

```sh
sh scripts/verify-local                        # offline P0 checks (live providers opt-in, skipped honestly)
python -m framebound demo --profile wp6 --offline --out build/wip6   # Pip: 4 clips pass
python -m framebound serve --project build/wip6/project --port 8765  # desk at http://127.0.0.1:8765
# desk dev: cd web && npm install && npm run dev   (proxies /api to :8765)
# v1 prototype still works: python -m framebound demo --out build/demo
```

Open http://127.0.0.1:8765 for the review desk.

## Model-facing tools

CLI (JSON in/out) and MCP (stdio) expose the same operations: `check`, `brief`, `preflight`, `repair-plan`, `repair-evaluate`, `record-failure`, `export-dataset`. See [docs/MODEL_TOOLS.md](docs/MODEL_TOOLS.md).

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

With a Meta Model API key (`MODEL_API_KEY`), generation and vision critique go live; without one, adapters return the exact request they would send and fabricate nothing.

## Licence

MIT. Demo art is procedural and original. Do not add third-party game assets.
