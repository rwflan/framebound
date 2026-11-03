# Valeria movement comparison

Open `http://127.0.0.1:5173/#/valeria-demo`, or **••• → Valeria movement**.
Arrow keys move; Space jumps; S slides; J attacks. Compare drives both lanes
with the same camera, controls and authored clock. Pause freezes that clock.

The current generator uses **one full-native Muse image per pose**, rather than
splitting a three-pose sheet. Portrait requests return 1280 × 1920 sources;
wide actions use 1920 × 1280 sources. A shared 2048 × 2048 delivery canvas adds
transparent letterboxing only: stored pixels are never upscaled or fitted per
pose. Playback uses one fixed pixel-density factor per source format in both
lanes, so a wider composition does not shrink the character.
Original source resolution and the delivery canvas are reported separately in
Evidence. Runtime bounds include the entire delivered artwork in both lanes,
so moving or turning cannot cut a long cape or whip against the playfield edge.
The camera follows at the edge of the safe projection, retaining the full
movement range even for a wide whip pose.

Both lanes start from exactly the same base generation, references and brief.
The reference is the later tailored-skirt Valeria without the hanging white
waist panel. Both lanes receive identical declared-magenta extraction, edge
unmatting, letterboxing and timing. Direct Muse then stops. Framebound checks
original image framing and native subject span, reviews the pose and costume
with Muse Spark, and can request bounded regenerations under the framework's
packaged principles. A narrow canvas with side collisions triggers a wider
composition. Original source pixels are checked again before publication.

A missing or clipped cape, braid, finger, sole or prop tip fails even when more
than 90% of the border remains clear. Padding cannot clear a failed source
check. The framework lane must pass framing, complete-silhouette and wardrobe
checks before a revision is published. Failed attempts and spend receipts are
retained; a failed build leaves the current demo untouched. Automated reviews
and framing passes do not establish human artistic preference or approval.

## Local build

`python scripts/build_movement_demo.py --config PRIVATE_BRIEF.json --root PRIVATE_OUTPUT`

For individual poses, the private brief supplies `mode: individual`,
`references`, `brief`, `native_canvas` and `poses`. Each pose has an `id`,
`instruction`, `image_size` and `states` mapping. `max_repairs` bounds attempts;
`minimum_subject_span` bounds native detail. `publish_root` optionally selects
an existing published-assets directory for atomic live updates. The legacy
`batches` mode remains available and now also withholds clipped framework cells.

All source images, prompts, responses, assessments and receipts stay under
`PRIVATE_OUTPUT/private`. An exclusive pre-send marker prevents retrying a
possibly accepted paid POST. Completed responses can be replayed locally. `--publish-received` rebuilds
individual-pose playback without any provider calls. It requires the complete
pose set and uniquely matches each selected response to its retained original
framing/extraction report; missing or ambiguous provenance blocks publication.

Expose the published directory at `web/public/demo/valeria-live` using a local
symlink (ignored by Git). Publication writes immutable revision directories
before replacing the manifest. The browser polls every ten seconds and loads
both complete lanes before swapping them. The dev server supports new revision
files without restart. `web/dist` includes published artwork for the submission
build; the desk API is still required. Prompts and receipts are not copied.

## Framework integration

`framebound.v3.intake.framing` measures safety margins and subject pixel span
against original image/cell bounds. The generation service checks immediately
after extraction, before resampling. The public sheet-consumer path checks
before its shared canvas transform. Existing padded derivations must supply
`source_box` to validate their retained original bounds. Raster isolation and
framing are separate checks; neither grants semantic quality or approval.
