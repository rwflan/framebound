# Controlled tracked-scene benchmark

Run from the repository root:

```sh
python -m framebound animation-quality-benchmark --manifest fixtures/quality/tracked-scene-v1/corpus.json
```

Six independently labeled procedural cases exercise a uniform 2D camera's
translation and scale, two subject landmarks, intentional occlusion, authored
contact/order, missing and duplicated features, an unexpected discontinuity,
and an incorrect interaction despite individually tolerated feature positions.
The repaired case links to the incorrect-interaction baseline.

The initial report detects all six labeled failing checks with no missed checks
or false alarms and exact frame localization for all six. These small controlled
examples establish engineering behavior only. They are not an independently
human-reviewed generated-art dataset. The report retains that absence explicitly;
no general animation-quality accuracy or human acceptance follows from the result.

Thresholds belong to the frozen fixture tasks: expected visible landmark count is
one, allowed per-frame world-anchor error is 1.1 units, the valid temporal step is
one unit and adjacent contact permits a one-unit landmark separation. The wrong
event intentionally stays within the independent feature-error bounds while
violating the contact constraint. Other shapes, textures, inferred landmark
semantics, occluded physical contact and perspective are outside this benchmark.

All PNGs were created procedurally. `corpus.json` records their source and label
provenance and complete-label declarations; none is represented as original
participant art, a provider observation or a reviewer decision.
