# Local animation campaigns

The v3 campaign package implements a local experiment controller around bounded
Muse specialists. It never starts paid work on import, planning, replay or report.
It keeps experiment media, prompts, receipts, labels, models and reports outside
Git. Currency amounts are integer microdollars (one dollar = 1,000,000).

```sh
framebound campaign plan --root /absolute/local/root --campaign animation-v1
framebound campaign status --root /absolute/local/root --campaign animation-v1
framebound campaign replay --root /absolute/local/root --snapshot /absolute/validated/snapshot
framebound campaign run --root /absolute/local/root --campaign animation-v1 --muse
framebound campaign stop --root /absolute/local/root --campaign animation-v1
framebound campaign resume --root /absolute/local/root --campaign animation-v1
framebound campaign report --root /absolute/local/root --campaign animation-v1
framebound campaign export --root /absolute/local/root --campaign animation-v1
```

`python -m framebound.v3.campaign.credentials` creates an empty private credential file and prints its path. Open it in an editor, fill `api_key` and save. Existing credentials are preserved. The file stays outside the repository with mode 0600; setup makes no provider call. `run --muse` reads that file or `MODEL_API_KEY`; it also requires verified frozen prices and an explicit
allocation. Planning does not fund a release. The initial API ceiling is $15 and
Modal ceiling $10; the lifetime ledger retains prior incurred costs and unknown
reservations. `Ledger.fund` is the explicit local allocation interface and requires
price/access evidence. Never infer account credit eligibility from an installed
CLI/profile. Check credit expiry/restrictions, unrelated workspace consumption,
workspace usage budget and net spend limit before funding compute. The $30 Modal
contingency is outside the application spending ceiling.

`resume` clears a campaign stop; it preserves all requests, send permits, costs,
reservations and terminal evidence. It does not resend unknown outcomes. Reconcile
those using an actual provider receipt through `Ledger.receive`. A confirmed
provider failure is recorded as a received failure response with its actual cost;
an HTTP timeout is not proof of nonacceptance. The external command bridge reads
one frozen request on stdin and returns `raw_base64`, `incurred`,
`successful_images` and `receipt`. It must disable its own hosted-call retries.

The coordinator serially admits cases while enforcing the configured ceilings of
two image requests, two assessments and one Modal job. It stops on a malformed
provider schema or sheet shape before further admission. Native drawing holds,
loop windows and original identity anchors are preserved. Up to four six-pose
sheets can form a sequence. `enable_long_sequences` verifies two completed
six-pose cases and their actual receipts before allowing longer provider attempts.
This capability gate is distinct from importer compatibility tests.

Automatic repairs require task-authored permission and corroborated typed
findings. The authority is stored separately from reviewer interventions. A late
diagnosis can reopen technical completion without changing the task or budgets.
The second diagnosis uses a separately frozen preservation audit rubric. Raw candidates remain intact, localized outputs are composited locally, and exact
protected pixels are checked. At most two repairs run. Every candidate receives
new measurements and assessment, then an independent A/B comparison against the
original and retained learned best. Ties, uncertainty and rejected candidates are
retained. Structural `best_revision_id` and `learned_best_revision_id` have separate
meanings. Model comparison never becomes human acceptance.

The predeclared control allocation selects 80 validation specifications without
conditioning on repair success. Eligible released cases receive an original-request
rerun using the same anchor and image allowance. All attempts and exclusions must
remain in the intent-to-treat report; incomplete arms prevent promotion. Automatic
expansion uses recorded conditional selection probabilities and reports unmet
quotas. It cannot select final-test specifications. Final evaluation requires the
full 160-case frozen cohort and hashes of the promoted policy/model/prompts/
preprocessing. Until the support and comparison gates pass, the previous component
remains in use.

The existing corpus replay validates the portable snapshot, decodes actual frames,
replays historical labels and produces local numeric features. It preserves `dev`
as training, `test` as held out and excludes unsplit rows from training. It does
not invent category coverage from prose labels or certify clean clips. Historical
labels remain available alongside explicit unknown masks under the new taxonomy.

Training starts with at least 300 training sequences, 75 training families and 30
positive sequences per advertised category. Use `campaign features` to build an inspected feature shard from a closed export, and `campaign train --request` with a local feature file and category list to run the recipes. Single-teacher labels have a fixed weak weight; corroborated categories can pass the positive-support gate. Partial-scope negatives never become whole-sequence negative targets. The installed NumPy baselines use eight
local numeric measurements, so their semantic ceiling is limited. They return
native-window scores and cannot localize anatomy or spatial ROIs. An optional
PyTorch temporal convolution and repair ranker are included. Validation labels alone
select thresholds; family-clustered precision intervals, challenge negatives,
recall tradeoffs and matched controls determine promotion. Falling loss is not a
promotion criterion. Synthetic engineering tests are never reported as actual
Muse training results.

`export` closes detector/editor/preference/sequence/failure datasets with actual
native frames, requests, conditioning, raw receipts, generation ancestry and model
provenance. Unknowns remain masked; unsuccessful candidates do not become positive
editing targets. Ties and ambiguity remain nonbinary comparisons. The validator
checks hashes, closure, image decode and family splits. These are local portable
training datasets, not evidence that hosted Muse weights were fine-tuned.

Modal accepts only the canonical `FeatureShard` byte format: eight derived numeric
measurements per native frame, scoped targets/masks, weights and opaque IDs. Exact
transferred bytes are validated; arbitrary metadata, prompts, images, masks and
archives have no wire field. Final-test features are rejected from training jobs.
Derived features remain private information. `remote.Job` freezes the base image
digest, recipe, GPU/resource bounds, startup/replay allowance and transfer quote.
`modal_worker.build` constructs an ephemeral worker with only explicit generic
source files, no secrets, no corpus mounts, blocked outbound networking and one
single-use container. The built-in transport caps jobs at ten minutes and returns final checkpoints; longer jobs require a durable checkpoint/resume transport and are rejected. Importing it does not build or deploy an app. NumPy training
may be cheaper locally; profile before allocating a GPU. Resource reservations
remain conservative until reconciled against actual workspace billing.

No live credit terms, provider usage reconciliation, 80-case generated pilot,
300-sequence learned checkpoint, adaptive expansion or untouched final evaluation
is claimed by the software tests. Those are experiment results produced only after
their access, funding, capability and evidence prerequisites pass.

Primary execution references checked 31 October 2026:

- [Muse image requests](https://dev.meta.ai/docs/image-generation)
- [Meta model prices](https://dev.meta.ai/docs/pricing-rate-limits)
- [Modal resource prices](https://modal.com/pricing)
- [Modal budgets and net spend limits](https://modal.com/docs/guide/budgets)
- [Modal container replay behavior](https://modal.com/docs/guide/retries)
