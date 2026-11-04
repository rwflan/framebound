# Character continuity between poses

A pose matching its design reference does not prove it matches its neighbours.
Policies can declare `transitions` with explicit `left` and `right` frame IDs and
one feature per rule. Item rules identify a declared inventory item, so these
checks work for weapons, tools and other held objects.

- `body.shape`: face-relative body and garment cross-sections across poses.
- `item.shape`: rigid component size, fittings, strand thickness and construction;
  flexible articulation is allowed.
- `item.palette`, `item.texture`: material colour and surface construction.
- `item.owner`: anatomical shoulder/elbow/wrist ownership, independent of the
  fist's screen position.
- `item.orientation`: active end at the thumb/index side and butt at the palm
  heel for a conventional grip; requested exceptions belong in the contract.
- `item.grip`: the declared handle or mount remains held and connected.

The observation rubric also supports per-pose `grip_component` and `orientation`
item features. They supplement anatomical ownership and attachment distances.
Neither a grip match nor a matching brown colour waives a wrong hand, reversed
handle, duplicate strand or changing design.

`review_character_transitions.py` retains provider responses and source hashes.
Only complete current evidence can pass. A retained negative stays actionable
while its pair is unchanged; asking again cannot erase it. Missing or ambiguous
evidence stays unmeasured. The repair driver supplies concrete failed pair
findings and the comparison images to Muse, reviews proposed replacements, and
retains rejected attempts. Publication blocks incomplete transition checks even
in preview mode. This is model evidence, never human approval.

Optional `torso_profile_pairs` compare deterministic source-pixel width quantiles
in torso-local coordinates, normalized to the observed face span. The current
material filter supports a visible low-saturation light torso garment, such as
Valeria's white fitted shirt. It does not infer anatomy under clothing or support
arbitrary materials. Missing landmarks or ambiguous coverage block the declared
check. Choose every relevant pair to prevent gradual drift around a cycle.

`minimum_scale_reference_pixels` bounds native detail before display calibration;
rendering a small character larger cannot satisfy that threshold. Original source
framing remains independently checked before padding or background removal is
published. All artwork, prompts, observations and receipts stay outside Git.
