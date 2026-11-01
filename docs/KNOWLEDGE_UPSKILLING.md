# Evidence-led animation learning

Framebound now provides a versioned curriculum, a private evidence inventory,
scoped supervision, an advisory experience library, richer geometry features,
local baseline/ablation studies, and measured admission to feature-only Modal
compute. These operations prepare and evaluate experiments. Installing them does
not establish detector reliability, creative acceptance or completion of a live
training campaign.

All commands use `framebound campaign ACTION --root PRIVATE_ROOT --campaign NAME`.
`PRIVATE_ROOT` must be outside the repository. JSON request paths passed with
`--request` can be absolute; paths *inside* those requests are relative to
`PRIVATE_ROOT` and cannot escape it through `..` or symlinks. No report, training,
planning or retrieval action dispatches an image provider or Modal job.

## 1. Audit existing evidence

`inventory` inventories registered campaigns, actual terminal outcomes, scoped
category coverage, receipt closure, recorded costs and unresolved requests. It
validates closed exports, decodes their frames, rechecks current isolation, reports
rights and applies conservative family/shared-input/exact-pixel/dHash split
quarantine. Reports are content-addressed under private `knowledge/inventories`.
The original receipts, annotations, datasets and model judgments are preserved.

`audit` separately replays corroboration diagnostics. `replay --snapshot PATH
--campaign historical-upskill-v1` validates a portable historical snapshot and
replays its original labels without inventing new taxonomy coverage. Unsplit
examples remain excluded and historical test assignments stay held out.

An isolated raster is not proof of correct subjects, anatomy or action semantics.
Unknown rights and unsupported labels remain unknown. Current campaign training
and knowledge collection accept only recorded `original` rights, current intake
eligibility and split-safe components. Rejected examples remain in the local
research export, including their unsuccessful trajectories.

## 2. Freeze the MVP curriculum

`plan` defaults to `animation-mvp-v2-keyed`, schema 2.0 / dataset `mvp-2`. Supply
`--config` for a complete custom frozen configuration. The historical schema 1.0
parser and `curriculum()` remain available for old experiments; existing plans
cannot be overwritten by new defaults.

The MVP curriculum freezes 800 specifications: 480 training, 160 validation and
160 final-test cases across 200 identity families. It contains eight treatments,
five difficulty levels and four actions per family. Subjects cover characters,
animals, figures and objects. Every case declares an exercise, legitimate
counterexample and target categories. There is one subject, a fixed camera, fixed
topology, and optional held-prop interaction. Effects-only output, scenery and
opaque surroundings are excluded.

The initial 12-case rehearsal covers all eight treatments and six authored poses.
It is a subset of the 80-case pilot. Training initially advertises only temporal
and artifact categories. The separate repair-control allocation contains 80
validation specifications; its purpose and denominators differ from the pilot.

Generation requests explicitly reserve pure magenta RGB(255,0,255), prohibit that
color in the subject, and require generous margins. Native alpha is preserved;
otherwise the existing declared-key extractor creates alpha. Source sheets,
provider bytes, extraction recipes and raw crops remain intact. This is an
extraction derivation, not a semantic pass. Historical white backgrounds are never
silently erased. An extraction or malformed-sheet failure stops the batch before
repeating the failing paid shape.

## 3. Allocate and collect in bounded stages

`fund --request FUND.json` is explicit allocation, not a side effect of planning.
A v2 API allocation request has this shape (replace all evidence with actual
current values):

```json
{
  "subsystem": "api",
  "microdollars": 1000000,
  "evidence": {
    "verified_at": "<current ISO timestamp with timezone>",
    "source": "<verified pricing source>",
    "account_access": "<actual account/access evidence>",
    "image_microdollars": 10000
  }
}
```

Evidence expires after 24 hours for new allocations. A changed image price
requires a new frozen configuration rather than rewriting old quotes. Allocation
cannot erase incurred cost or reservations. The initial API ceiling is $15 and
Modal ceiling is $10; lifetime ceilings and previous bookings remain in effect.

`run --muse --request BATCH.json` uses `{"max_cases": 1}` for one rehearsal case,
or a bounded batch of 1–80 unfinished admitted cases. Without a batch request it
visits the current admitted cohort. Completed cases replay without another send.
A saved source-layout or declared-key failure can be closed with `quarantine`:
provide the admitted `case_id` and relative `failure_report`. This verifies actual
received receipts, records the negative acquisition evidence and leaves the campaign
stopped. Explicit `resume` can then continue other cases. Quarantine never resends
the failed case, resolves unknown outcomes or converts execution bugs into art defects.
Unknown sends never retry. Native timing, the two-repair limit and long-sequence
capability gate remain enforced.

`readiness` reports stage evidence and training support. `release --request
PILOT.json` takes `{"stage":"pilot"}`. It requires all rehearsal outcomes, usable
scoped assessments for at least 75% of the allocated cases, at most 25% intake
failures, actual intact receipts and no unresolved sends. These are acquisition
criteria, not accuracy claims. Releases do not allocate money.

Expansion requires the same pilot evidence and a saved local baseline support
report. Use `mode: "representative"` (the default) to collect outcome-blind tranches
of at most 80 additional cases while training support is insufficient. Its request
contains `stage: "expansion"`, a unique safe `batch`, `baseline_file` and `size`.
Each tranche retains its actual selection probability.

`mode: "adaptive"` additionally requires an informative evaluated baseline and
`candidates` with case `id` plus observed `uncertain` / `supported_failure` flags
where supported. The existing adaptive sampler reserves
40% recurring failures, 30% disagreements, 20% challenge cases and 10% exploration.
Selection probabilities and unmet quotas are retained. Already released cases and
final-test cases cannot be admitted as another expansion batch. Release requests
are immutable and replayable.

## 4. Close data, derive features and accumulate knowledge

`export --request VERSION.json` closes frames, conditioning, requests, receipts,
ancestry and comparison outcomes in an immutable private version. New exports use
`animation-training-2.0`; the reader retains v1 support. Known initial acquisition
failures have a separate `acquisition` lane with original request/receipt closure,
execution label provenance and no fabricated native frames or training targets. Use a new
version when exporting with new metadata; never rebuild a published version with
changed contents. The export request is `{"version":"study-v2"}`.

`features` takes `version`, optional `dataset_version` and `extractor`. Use the
same closed `dataset_version` with distinct feature `version` names for a matched
representation ablation. Existing closed datasets are read without re-exporting
a campaign that may have acquired more media. V2 defaults to
`native-geometry-v2`: the historical eight measurements plus twelve normalized
alpha geometry, silhouette, displacement, overlap and foreground-change features.
`native-numeric-v1` remains available for matched ablations. Neither represents
anatomy, semantic action correctness, inferred landmarks or spatial diagnosis.

Supervision is category-specific. Different executions and rubrics must agree on
binding, target and native scope. Corroborated positives additionally require
matching subject/part/ROI/time evidence. Agreement in one category never upgrades
another. Conflicting labels are masked; a partial negative is never a whole-clip
negative. Weak weights are fixed at 0.5; corroborated weights are 1.0. Teacher
confidence is not a calibrated loss weight. Repair variants share an opaque
sequence ID and cannot inflate independent support counts.

Final-test rows are excluded by default. Explicit `include_test: true` creates a
final-evaluation shard; local development studies and remote jobs reject it.

`knowledge-build --request VERSION.json` derives entries only from eligible,
split-safe training examples. Each retains observed/expected behavior,
subject/part/frame/time/ROI scope, counterexamples, provenance, evidence hashes and
linked correction experiences, including unsuccessful outcomes.

`knowledge-query` takes `version`, `categories`, optional `exclude_families` and
`limit` (1–10). It revalidates the evidence closure on use and returns advisory
entries; it does not create findings or authorize repairs. No validation or test
example enters the library.

`advisory-set` selects a `knowledge_version` and/or `model_file`. A model selection
also requires `feature_file`, supported training data and selected validation
thresholds. Selection remains an advisory trial with no automatic promotion.
The runner includes selected experiences/scores only in an already authorized
correction brief. Independent teacher diagnosis and A/B assessment never receive
these suggestions, preventing the learner from supplying its own evaluation labels.

## 5. Establish local baselines and representations

`baseline` takes `feature_file` and `categories`. It runs reproducible linear and
temporal NumPy baselines across three seeds. Exploratory baselines need ten
training families, five validation families, ten training positives/negatives and
five validation positives/negatives per category. Otherwise they return explicit
insufficient support. They are marked engineering-only and cannot be activated or
promoted as supported models.

`ablation` takes `baseline_file` and `candidate_file` for two saved baseline
reports. It requires the same sequence IDs, splits, labels, weights and categories.
Compare the original representation against geometry features before adding more
complexity. Results do not establish repair usefulness.

`train` runs supported NumPy recipes. Its category gates require 300 independent
training sequences, 75 training families, and 30 corroborated positives plus 30
assessed negatives per advertised category. Unknown targets remain masked.
Validation selects thresholds; the final cohort is unavailable to training.

The optional PyTorch temporal convolution supports both representations and
portable CPU prediction. `profile` takes the same `feature_file` and `categories`
and measures the actual 200-step temporal forward/backward/optimizer workload on
CPU and available Apple MPS, with at least 20 training sequences and real assessed
targets. The fastest successful local device supplies the compute comparison;
unsupported-device errors are recorded. Profiling is
engineering evidence and cannot promote a checkpoint.

Part/landmark tracking and visual embeddings remain future representation
experiments. Their implementation requires scoped labels, explicit visibility,
local ablation evidence and another versioned wire schema; the current code does
not claim those capabilities.

## 6. Admit Modal only when it has measured value

`compute-plan` produces a frozen `Job`, conservative quote and missing-evidence
reasons without reserving funds or contacting Modal. Its request includes
`feature_file`, pinned `image_digest`, `categories`, `purpose` (`profile`, `train`
or `reproduce`), optional bounded resource allowances, and `study` paths.

`study` names `local_profile_file`, `baseline_file`, `credit_file` and
`hypothesis_file`. The hypothesis JSON has exactly `question`, `success_measure`
and `stop_condition`, each with substantive text. Credit evidence contains:

- Current timezone-aware `verified_at` and future `expires_at`.
- `source`, `restrictions`, `available_microdollars`,
  `workspace_remaining_microdollars`, `net_spend_remaining_microdollars`.
- `pricing_source`, `l4_microdollars_per_second`,
  `l40s_microdollars_per_second`, `cpu_microdollars_per_core_second`,
  `ram_microdollars_per_gib_second`.

Account evidence must be refreshed within 24 hours. It is an explicit operator
account declaration, not an authenticated provider balance attestation. Verified
rates must match the versioned quote implementation. Outstanding reservations are
included when checking available credit and limits.

`modal` takes `case_id` (an admitted accounting association), `feature_file`, the
frozen `job` returned by planning and the same `study`. A training job additionally
requires `remote_profile_request_id`: a received profile for identical data,
recipe, categories and resources, showing at least 25% end-to-end speedup over
the fastest measured local device. Reproduction also requires a matching received `training_request_id`.

The initial stage caps are $1 profiling, $3 first training and $2 reproduction;
$4 remains unallocated. All are cumulative across campaigns. The aggregate wall
allowance is one hour, including startup/replay reservations and earlier jobs.
Individual jobs over ten minutes are refused without a durable checkpoint/resume
transport. Existing bookings can therefore reduce the number of new experiments
that fit these limits. No allocation is an instruction to spend its full amount.

Only canonical bounded numeric FeatureShard bytes cross the wire. Images,
prompts, identities, masks, archives and arbitrary metadata have no transfer field.
V2 includes the declared eight or twenty measurements, opaque sequence/family IDs,
label masks and category weights. Eight-feature v2 rows enable matched-supervision
ablations without weakening the legacy v1 wire contract. New paid training requires
v2 scoped supervision; historical global weights must be re-extracted locally. The worker receives only allowlisted generic source, has no
corpus mounts or provider secrets, blocks outbound networking, disables retries
and uses a single-use container. Exact test rows are refused. Derived features
remain private information.

The profile runs the same temporal training workload, not a toy linear-layer loop.
Returned checkpoints are saved locally with provenance. Unknown outcomes retain
reservations and block redispatch; received jobs replay even after account
evidence expires. Costs remain conservatively booked pending actual billing.

## 7. Freeze and evaluate a candidate

Validation requires positive predictions across at least 30 independent families,
sufficient category support, a family-clustered 95% precision
interval whose lower bound reaches 0.90, and at least 100 assessed challenge
negatives with false-positive rate at most 0.05. The positive-support gates do not
replace validation support. Compare recall with the previous model when supplied.
Repair utility must beat matched blind reruns without additional regressions.
Missing control arms remain visible and prevent promotion.

`release` with `stage: "final"` requires `model_file`, development `feature_file`,
`policy_file`, `prompts_file`, `preprocessing_file`, optional `previous_model_file`
and `knowledge_version`. It independently recomputes model eligibility,
calibration and saved repair-control evidence, then hashes the exact artifacts.
All 160 final specifications remain frozen. Advice cannot be changed after final
release, and altered artifact bytes block final execution.

`final-report` takes a final-evaluation `feature_file`. All 160 allocated outcomes
must exist. Original baseline sequences supply detector evaluation; repaired
variants cannot replace them. Intake failures remain explicit exclusions in the
160-case denominator. Thresholds remain those selected on validation. The report
retains scoped model-label semantics, unassessed counts and no artistic acceptance
or general quality claim. Final evidence is advisory; broader repair authority
requires separately demonstrated safety and usefulness.

Primary execution references: [Meta prices](https://dev.meta.ai/docs/pricing-rate-limits),
[Muse Image](https://dev.meta.ai/docs/image-generation),
[Modal prices](https://modal.com/pricing), [Modal budgets](https://modal.com/docs/guide/budgets).
