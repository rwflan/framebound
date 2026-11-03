# Declared visual scoring

Framebound can now measure three narrow animation defects when a task freezes the relevant evidence before candidate submission. The design follows the Castlevania animation quality findings: wrong phase order, lifted planted support, and same-pose shape drift can survive whole-frame bounds and generic similarity checks. A task must declare the target phase, visible support window, or same-pose comparison region. These checks do not infer skeletons, judge arbitrary actions, or grant human acceptance.

## Contracts

Add `visual_observations` to a v3 task. A phase observation names a frozen `known_good_animation` reference asset and at least one competing phase asset. The scorer compares coarse alpha occupancy in the declared region. It requires both an absolute match and a positive margin over the nearest competing phase, so a substituted later pose does not pass merely because it resembles the subject. The reference images must use the native canvas and are retained with the evaluation evidence.

A `contact_span` observation measures the longest contiguous alpha run on one row of a declared visible support window. This detects a missing planted support within that window. It cannot prove the pixels are a foot or that the contact is physically plausible. A `same_pose_shape` observation compares foreground area ratio and alpha overlap against a frozen same-pose, same-view reference in a declared region. Different views, intentional deformation, and occlusion require a different task contract. Mark a declared occluded observation `visibility: occluded`; its result is `not_applicable`, never a quality pass.

The task negotiator treats visible visual observations as required checks. A missing reference returns `unmeasured` and blocks technical completion. A failing check gives a localized slot, tick range, ROI, observed numbers, thresholds, and reference asset IDs in the saved evaluation and feedback. Neither a visual pass nor an isolation pass changes `creative_status` from `unreviewed`.

## Reproducible adversarial benchmark

`python -m pytest tests/test_visual_score.py -q` freezes two procedural poses and tests three faults: replacing push-off with the later phase, removing visible support, and widening the body in the same pose. The previous declared-region evaluator passes all three because those faults have no preexisting task observation. The new scorer flags all three; the clean candidate passes all three. Tests also check missing reference abstention, occlusion, input binding, and submission status. This is a deterministic sensitivity check, not a measured precision or recall claim on generated art.

Existing generated-art pilots lack frozen phase, contact, and same-pose references, so this new scorer cannot retroactively claim a quality improvement on them. Independent human-reviewed generated clips and frozen references are needed before claiming generated-art quality accuracy or training readiness. Keep pilot media, labels, receipts, and benchmark outputs outside Git.
