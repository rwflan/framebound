# Anita engineering corpus

The Anita Dataset provides professionally hand-drawn 2D animation layers at
published timing. It is an optional external source for engineering tests. The
dataset is not vendored. Download it from
<https://github.com/zhenglinpan/AnitaDataset>, verify its mixed CC BY 4.0 and CC
BY-NC-SA 4.0 licensing, and keep the archive, extracted pixels, derived shards,
reports, and checkpoints outside Git.

Because the source includes CC BY-NC-SA animations, a checkpoint derived from
the complete collection is noncommercial research evidence. A production model
needs a separate corpus containing only rights-cleared sources.

## Build a feature shard

```sh
python scripts/build_anita_training.py \
  --source /absolute/private/anita/extracted \
  --output /absolute/private/training/anita-engineering-v1 \
  --version anita-engineering-v1
```

The builder groups paired color and sketch layers under one scene-family
identity. It creates:

- source-order sequences assessed clean for temporal and artifact defects;
- middle-swap, delayed-interior, and reversed temporal variants;
- ghost-plus-support-hole artifact variants;
- train, validation, and test rows split by scene family.

The three temporal variants share the source sequence identity. They exercise
different order failures without inflating independent sequence support.
Unknown semantic categories remain masked. Labels are engineering evidence from
the source timing and explicit local transformations, not human art review.
Scene folders are the strongest family identity supplied by this dataset, so
the split prevents window leakage but does not claim unseen-character
generalization.

The default gate requires 300 training sequences across 75 families and at least
30 positive and negative sequences for each advertised category. The transfer
format remains the existing bounded `native-geometry-v2` feature shard.

## Train and benchmark

```sh
python scripts/train_anita_engineering.py \
  --features /absolute/private/training/anita-engineering-v1/features.json \
  --private-root /absolute/private/training/anita-engineering-v1 \
  --version anita-engineering-v1
```

The trainer fits artifact-only linear and temporal NumPy candidates across three
seeds. The model and threshold are selected on validation families only. The
report compares the selected detector with a pass-all control on untouched test
families. Temporal ordering stays on the reference-bound scoring path because
the sequence-only temporal head did not clear the held-out benchmark.

```sh
python scripts/benchmark_anita_scoring.py \
  --source /absolute/private/anita/extracted \
  --output /absolute/private/training/anita-engineering-v1/reference-score-benchmark.json
```

The reference-bound benchmark uses actual source phases as known-good inputs.
It compares `visual_score` against the base evaluator, which accepts the raw
sequence without phase references. Threshold selection uses validation scenes;
the test scenes are evaluated once.

The generated `benchmark.json` and `reference-score-benchmark.json` preserve
the actual counts, thresholds, false positives, recall, and limitations. Neither
benchmark establishes arbitrary artistic quality, anatomy, human acceptance,
training readiness, or provider-model fine-tuning.
