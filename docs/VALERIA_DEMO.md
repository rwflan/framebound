# Valeria movement comparison

Open `http://127.0.0.1:5173/#/valeria-demo`, or **••• → Valeria movement**.
Arrow keys move; Space jumps; S slides; J attacks. Compare drives both lanes
with the same camera, controls and authored clock. Pause freezes that clock.

Both lanes start from the **same high-resolution Muse generations**, with
identical base instructions, references and layout guide. Both receive the same
declared-magenta extraction, edge unmatting, fixed canvas, padding and timing.
No individual pose fitting or low-resolution Castlevania atlas is used.

Direct Muse stops after this shared preparation. Framebound measures native
geometry using `native-geometry-v2`, assesses the generated sheet against the
original references with Muse Spark, and can request up to two bounded repairs
per batch using the packaged framework principles. It keeps a replacement only
when the automated score increases without materially worsening measured size
or baseline spread. A rejected repair never replaces the control or best take.
Automated assessments do not establish human preference or artistic approval.
Clipping in a generated sheet remains a visible defect; padding never restores
missing artwork. The same extraction and registration apply to replacements.

## Local build

`python scripts/build_movement_demo.py --config PRIVATE_BRIEF.json --root PRIVATE_OUTPUT`

The private brief supplies `references`, `brief` and `batches`; each batch has
an `id`, `instruction` and `states` mapping state names to its three pose slots.
The current demo uses two run batches followed by idle, jump and action batches.
The six run keys play at 10 drawings per second. Source images, requests,
responses, assessments and spend receipts stay under `PRIVATE_OUTPUT/private`.
An exclusive pre-send marker prevents retrying a possibly accepted paid POST.
Completed responses can be replayed locally without another charge.

Expose `PRIVATE_OUTPUT/published` at `web/public/demo/valeria-live` using a local
symlink (ignored by Git). The builder publishes immutable revision directories
and replaces the manifest last. The browser checks that manifest every ten
seconds and loads both complete lanes before swapping them. Generated builds
in `web/dist` include the published assets for a standalone submission; neither
private prompts nor provider receipts are copied there.

The previous opaque-sheet/legacy-atlas comparison has been replaced. Evidence
inside the demo reports native resolution, frame count and selected repair
batches, without claiming delivery readiness or a measured aesthetic win.
