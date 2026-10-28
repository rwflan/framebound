# Training-data export

> Status (2026-10-28): the table below describes the **v1** `export-dataset` path.
> The v2 snapshot path (`export` / `dataset-validate`, `framebound/v2/exports/`)
> follows it with corrected semantics.

The framework's goal is its own obsolescence. Every checked project exports the data a model would need to learn the bounds: what was asked, what passed, what failed and why, what repair was chosen, and what the human decided.

## Command

```sh
python -m framebound export-dataset --contract project/contract.json --out build/dataset
```

Also available in the review desk (Export button), where recorded human decisions are included.

## Contents

| Path | Format | Contents |
|---|---|---|
| `coco/annotations.json` | COCO | Images, per-frame bbox + RLE segmentation (from alpha or SAM 3.1 masks), one category per character. |
| `hf/data/*.png`, `hf/metadata.jsonl` | Hugging Face imagefolder | Loadable with `datasets.load_dataset("imagefolder", data_dir=...)`. Each row: character, clip, slot, hold ticks, technical status, issue code, human decision, per-frame metrics. |
| `hf/README.md` | Dataset card | Provenance, contents, licence note. |
| `preferences.jsonl` | JSONL pairs | Per failed slot: brief prompt, `chosen` (frozen reference / accepted repair), `rejected` (failed frame), `reason` (issue code). Directly usable for preference fine-tuning. |
| `temporal.jsonl` | JSONL | Clip sequences: ordered frames, holds, loop flag, full metrics. For video/temporal models. |

## Principles

- **Failures are data, not waste.** A rejected frame with a named issue code is a labelled negative.
- **Decisions are labels.** Approve/reject/needs-work from the review desk travels with the frame.
- **Provenance is mandatory.** The audit report beside the export hashes every source frame; datasets can be regenerated and verified.
- **No silent relabelling.** Technical status and human decision are separate fields, mirroring the reports.

## Intended uses

- Fine-tune an image model on chosen frames conditioned on briefs; preference-train on chosen/rejected pairs.
- Train a consistency critic on metrics + issue codes to predict failures before human review.
- Provide temporal supervision (holds, phase order, contacts) that still-image datasets lack.

## v2 snapshots (current)

Built by `python -m framebound export --project proj --snapshot s --out build/s --revisions clip-01[,…]`
(or the desk Export view), validated by `dataset-validate` (moved-snapshot safe).

- **Positives (`hf/` imagefolder): eligible frames only** — technical PASS + COMPLETE,
  fresh evidence, packet-bound human approval for the exact revision+evaluation, no
  unresolved blocking tasks, allowed rights, non-procedural unless explicitly opted in.
  Unknown-rights, procedural-unless-opted-in, unreviewed and revoked targets are excluded
  with per-frame reasons; a legitimately empty positive view succeeds without invention.
- **Research archive (`research/`):** every other requested frame with truthful origins
  (`procedural-test`, `weak-negative`, `unreviewed`, `withheld`) — a labeled archive,
  never masquerading as positives.
- **Preferences (`preferences.jsonl`): explicit pairwise human comparisons only** — a
  comparison packet binding chosen+rejected plus a reviewer approve decision on that
  packet (same contract). Descendant approval alone is insufficient; technical rankings
  live in `weak_preferences.jsonl` labeled `technical-ranking`, never as DPO pairs.
- **COCO (`coco/annotations.json`):** every exported frame, RLE from alpha in exact
  row-major order; the validator decodes each mask pixel-for-pixel against its packaged
  source and recomputes area + bbox (area-only agreement is not acceptance).
- **Temporal (`temporal.jsonl`):** ordered frame/instance/asset refs, holds/tick-rate,
  loop/terminal rules, traces with explicit missing coverage (e.g. no world_positions yet).
- **Closure (`closure/`):** contracts, characters, guides, reference pixels, evaluations,
  attempts, review/comparison decisions, event provenance, edit masks. RGBA originals
  preserved; no absolute paths, credentials, or expiring provider URLs.
- Splits are validated by character/reference/derivation family + exact pixel duplicates;
  one family across train+test is recorded as a held-out-identity limitation, `strict`
  raises instead.
