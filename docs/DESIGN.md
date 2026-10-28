# Design

> Status (2026-10-28): the v1 prototype design below is historical. The
> implementation went through corrective passes R0–R8 (see
> IMPLEMENTATION_STATUS.md): schema `2.0` contracts, typed services
> (`framebound/v2/`), FastAPI desk, documented Meta Responses wire, durable
> jobs, gated bounded repair, eligible-only training views, a real browser
> journey, and an honestly labeled procedural replay. Corrections to the v1
> text are marked [v2]; unmarked sections describe the prototype.

## Problem

## Problem

A 2D game character may need hundreds of frames across run, jump, attack, hurt, and idle cycles. Image generation is strong at one frame in a style and weak at holding, across all of them: body proportions, costume colours, which pose belongs to which phase, whether a foot is planted, and whether frame 40 still matches frame 1. Human review catches this late and does not scale; unreviewed, it ships.

## Principle

Bound the work before generation, verify it deterministically after, repair only the bounded failure, and let a human decide only what machines cannot. Every artefact — pass, failure, repair, human decision — leaves as training data.

Three separations are enforced everywhere:

- `technical_status` (checks) vs `visual_acceptance` (human). A pass never approves art.
- Rendering authority (approved master) vs motion authority (phase references). Neither substitutes for the other.
- Measured vs unmeasured. Occluded or undeclared anatomy is reported unmeasured. A declared measurement that cannot be taken fails closed.

## Contract

One JSON file per character clip (`schema: 1`):

| Field | Meaning |
|---|---|
| `canvas` | Native frame size. Every frame, no per-pose fitting. |
| `master` | Approved standing design, SHA-256 frozen. Body/costume authority. |
| `identity_reference` | Independent identity source (face/design), SHA-256 frozen. |
| `references` | One frozen drawing per phase. Motion authority. |
| `holds`, `locked_holds` | Integer ticks per frame; changes fail as `locked_cadence`. |
| `region`, `grid` | Window and grid for the registered phase descriptor. |
| `contacts` | Declared support windows with minimum visible span. |
| `anchors` | Reviewed points per phase with maximum drift. Declared, never inferred. |
| `feature_span` | Two declared visible features (e.g. clasp, buckle), their colour rule and search windows; span is compared to the master. |
| `repair_regions`, `protected_regions` | Where a repair may and may never change pixels. |
| `forbidden_path_fragments` | Rejected-input paths that briefs must never reference. |
| `tolerances` | Per-contract thresholds. Defaults in `checks.DEFAULTS`. |

Reports hash the contract, every input file, and the analyzer modules, and fold them into an `evidence_id`. A stale report cannot pass as current.

## Checks

All checks are registered raster observations, not inferred skeletons.

| Code | Detects |
|---|---|
| `candidate_registration` | Frame size differs from the native canvas. |
| `silhouette_area_drift` / `silhouette_width_drift` / `silhouette_height_drift` | Size change vs the same frozen phase (cycle median only without references). |
| `phase_correspondence` | Frame matches a different phase substantially better than its own. |
| `stalled_phase` | Adjacent required phases collapse to one pose. |
| `surface_span_drift` / `surface_span_pulse` | Local size pulse: feature span vs master, and frame-to-frame. |
| `surface_feature_unmeasured` | Declared feature missing or ambiguous. Fails closed. |
| `appearance_palette_drift` | Quantised palette histogram vs the same phase (or master). |
| `missing_support_contact` | Planted phase has no visible support in its window. |
| `anchor_drift` / `unmeasured_anchor` | Reviewed anchor moved; or missing (warning, never a pass). |
| `root_drift_step` | Centroid jump between adjacent frames (warning). |
| `locked_cadence`, `playback_structure` | Holds changed or malformed. |
| `changed_input`, `missing_input`, `rejected_generation_input` | Frozen reference altered, absent, or forbidden. |

What checks cannot decide — grace, acting, occluded limb volume, texture quality, sliding inside a held drawing — stays with the human reviewer, and the report says so.

## Loop

```
brief ──> generate (Muse Image) ──> preflight ──> pass ──> human review ──> approve/reject
                                        │fail                     │issue marked
                                        ▼                          ▼
                                  repair-plan ──> bounded repair ──> repair-evaluate ──> human review
```

- **Brief** (`brief.py`): master + identity + exact phase + neighbours, hash-bound, with native canvas, holds, and preservation constraints.
- **Preflight** (`audit.preflight`): read-only. Candidates replace frames in analysis only.
- **Repair plan** (`repair.plan`): one task per error, instruction keyed by issue code.
- **Repair evaluate** (`repair.evaluate`): whole batch, all gates re-run, protected pixels verified, strict improvement and zero errors required for `selected_for_review`. Never writes runtime art.
- **Failure recording** (`record-failure`): symptom, expected behaviour, slot, code, evidence hash. New failures become regression fixtures before thresholds change.

## Meta model roles

| Model | Role |
|---|---|
| Muse Image | Generates frames under compiled briefs. |
| SAM 3.1 | Instance masks for shape measurement where alpha is insufficient. |
| Muse Spark / Wonder | Orchestrates the loop via CLI/MCP tools; second visual critic. Advisory only. |

Adapters [v1: `meta_api.py`; v2: `framebound/v2/providers/`] use the Meta Model API (`https://api.meta.ai/v1`, `MODEL_API_KEY`). Offline, they return the request they would send and fabricate nothing. At hackathon scale the deterministic core (pydantic/Pillow/numpy, not stdlib) is the fast inner loop and models are the slow outer loop: the public 8-frame 64×64 evaluation service benchmarks at warm p50 ≈ 27 ms (cold ≈ 320 ms), Apple Silicon, `benchmark-eval` report; raster primitives are microbenchmarked separately.

## Review desk

[v1: standard-library HTTP server + SQLite (`review.py`).] [v2: FastAPI (`framebound/v2/api/app.py`) + SQLite with the same persistence guarantees, plus a React desk with hash routing, a presentation clock, side-by-side/blink/difference comparison, issue detail, corrections queue, export view, and a DB-backed activity log. Browser journey proven in CI.] Persistent across restarts. Playback honours holds; per-frame metrics and errors are shown beside the frame; issues are marked by category and note; decisions are approve / reject / needs-work. `GET /api/corrections` is the model's work queue. Dataset export is one click and includes the recorded decisions.

The desk is for humans, but its consumer contract is machine-first: every human action is stored as structured data, not prose.

## Training-data export

See [DATASET.md](DATASET.md). Formats: COCO, Hugging Face imagefolder, preference JSONL, temporal JSONL. The intent is obsolescence: a model fine-tuned on bounded successes, bounded failures, repairs, and human decisions should eventually hold consistency without runtime bounding.

## Non-goals

- Not an editor. Humans do not draw or directly manipulate frames here.
- Not a skeleton/rig system. No joints are inferred from raster colour.
- No automatic art approval, anywhere, under any score.
