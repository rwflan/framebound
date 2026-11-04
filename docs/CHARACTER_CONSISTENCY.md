# Character consistency gates

Tasks may declare a `character_consistency` policy bound to an immutable identity
asset. Original artwork, observations, prompts and provider receipts remain local.
A missing or uncertain measurement cannot count as a pass. These gates establish
agreement with a declared reference and observation method, not human acceptance
or training readiness.

The policy checks facial identity separately from expression, garment design,
palette and accessory placement, rendered part proportions, calibrated character
scale and adjacent-frame changes, including declared loop transitions. Landmarks
measure visible projected image geometry; they do not establish hidden anatomy or
physical 3D dimensions. The optional pinned pose backend records model and code
hashes and refuses ambiguous cross-sections.

Every visible item follows the same inventory contract: weapons, shields, tools,
bags and worn accessories. Each item declares its design, palette, scale,
attachment, anatomical hand or mount, and optionally a rigid component to measure.
Flexible poses do not permit changes in construction. Unlisted visible items,
duplicates, ownership changes and disconnected grips fail. Mounted objects need
a visible, source-bound attachment landmark; unknown locations remain unmeasured.

Transfers and occlusions must be explicitly scoped to frames. Appearance changes
such as wetness or damaged clothing require exact feature/frame exceptions bound
to the originating request. They do not waive identity or unrelated item gates.

The assessment loop consumes observations bound to actual submitted pixels,
returns localized failures, and rechecks replacements and playback neighbours.
The demo repair driver retains original provider responses and proposes bounded
local edits. Unknown provider acceptance blocks resending; changing a prompt is
not a recovery mechanism. Direct Muse control assets remain frozen. Repair
attempts and automated evaluations do not themselves establish an improvement:
publication requires every declared gate and transition to pass.

A playable refinement preview is distinct from delivery. The publication tool
refuses failed delivery by default; `--preview` records outstanding findings and
marks the live lane **Refining**. Control image bytes and authored timing remain
frozen. Runtime registration records per-frame scale and translation without
rewriting native source artwork. A shared camera uses aggregate silhouette bounds
so registration cannot push a cape or item outside the viewport. The browser
loads a complete immutable revision before switching playback to it.

Material geometry recipes are versioned separately. A garment seam cannot stand
in for its outer width; tiny stripes and inconsistent lower-torso sections remain
unmeasured. The lower-torso band measures visible garment contours rather than
mistaking the pose model's hip/skirt centre for a waist. Changing a measurement
recipe requires a new frozen policy and reassessment of retained source pixels;
old failures and evidence are preserved.

## Visible volume and whole-sequence item review

An arm length is not evidence of arm thickness. Missing comparable arm-width
measurements now require an explicit `body.upper_arm_bulk` observation; otherwise
arm-volume coverage remains unmeasured. Targeted `body.forearm_bulk` and
`body.thigh_bulk` checks compare the actual referenced build, not stereotypes or
the word "athletic". Flexion does not permit a different muscular build.

The independent cohort observer sees the canonical source and all ordered frames
together. Focused outputs retain neighbouring images as context and bind the
review to every source hash. Item policies can require `material`, `topology`,
`proportions` and `configuration` alongside design, palette, scale and attachment.
These cover changing rigid handles, flexible-strand thickness, extra strands,
fittings and the required folded/coiled/extended state for any declared object.
Rigid-component size is also checked between adjacent frames, including loops.

A cohort review never overwrites original evidence. It adds retained source-bound
findings; neither a general appearance score nor individual-frame plausibility
can waive them. The demo can name body/item blockers that forbid publication even
as a refinement preview. Publication performs the configured whole-state reviews
again after selecting replacements. Unknown provider outcomes are not retried.

## Cumulative provider cost

`experiment_costs.summarize` scans explicitly declared lineage roots. It counts
shared initial generation separately from framework generation, assessment and
repair work, including failed and superseded experiments. Copied receipts with
the same provider response ID are deduplicated; distinct paid responses are not.
Conflicting receipts or response hashes fail the accounting check.

Observed usage/rate receipts and unreconciled commitments remain separate. A
missing response or cost receipt is not zero spend. No campaign restart or new
selection resets historical work. The private ledger retains operation-level
provenance; the public `costs.json` sidecar exposes only totals, counts and an
evidence digest. It refreshes independently from animation revisions. Local CPU
and external services without linked receipts are explicitly unpriced.
