# Training-data export

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
