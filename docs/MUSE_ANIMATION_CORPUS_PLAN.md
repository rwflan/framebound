# Game-led Muse animation corpus plan

Restarted 2026-10-30. This replaces the asset-pack/museum-led reference approach. The visual bar is established games with strong, distinctive 2D art. Source selection starts with the game and what its art and animation do well, then selects representative images and motion examples. Availability of CC0 assets does not determine the aesthetic target.

## Reference library

Open the [game-led gallery](research/game-art/index.html) and [source manifest](research/game-art/games.json). Publisher storefront screenshots and trailers are the initial research sources. The gallery links original full-resolution screenshots rather than presenting sprite-pack promotional sheets. It groups work by named games so comparisons remain recognizable and useful.

The first pass lists 27 games and 170 publisher screenshot links. Titles without acquired images are marked as acquisition gaps. These are research references, not a completed model-conditioning library.

## Initial game shortlist

| Game | Visual direction | What to study |
|---|---|---|
| Shovel Knight | 8-bit inspired | Silhouette economy, readable anticipation and compact effects |
| Sonic Mania | 16-bit inspired | Momentum, expressive poses and layered pixel scenery |
| Chrono Trigger | 16-bit RPG | Character readability, directional poses and environmental animation |
| Metal Slug 3 | Arcade pixel | Detailed expressive sprites, mechanical motion and effects |
| Street Fighter III: Third Strike | Arcade drawn fighters | Weight, anticipation, impact and recovery; collection screenshots need title verification |
| Celeste | Modern pixel | Small expressive actors, movement clarity and restrained palettes |
| Dead Cells | Rendered-to-pixel hybrid | Dynamic poses, lighting and high-energy effects |
| Blasphemous | Detailed pixel | Large anatomy, costume texture and dramatic silhouettes |
| Owlboy | Detailed pixel | Expressive characters and richly layered environments |
| Sea of Stars | Modern RPG pixel | Rich lighting, directional characters and environmental detail |
| Hollow Knight | Hand-drawn | Clean outlines, character silhouettes and atmospheric depth |
| Cuphead | Traditional cartoon | Rubber-hose motion, extreme poses and painted backgrounds |
| Ori and the Will of the Wisps | Painterly dimensional | Soft materials, luminous effects and layered depth; hybrid production |
| Rayman Legends | Illustrated | Exaggerated forms, expressive motion and dimensional painted scenery |
| GRIS | Watercolour inspired | Colour composition, delicate shapes and fluid transitions |
| Spiritfarer | Drawn character animation | Acting, secondary motion and expressive character interaction |
| Hades | Isometric illustrated | Strong shapes, rich colour and readable action effects |
| Streets of Rage 4 | Drawn action | Weight, impact, readable combat poses and bold contours |
| Skullgirls 2nd Encore | Drawn fighters | Extreme key poses, acting and recovery |
| Darkest Dungeon | Ink and graphic shadow | Heavy line weight, restricted movement and strong value design |
| Don’t Starve | Scratchy illustration | Angular shapes, line texture and deliberate puppet-like movement |
| Paper Mario: The Thousand-Year Door | Paper cutout | Paper articulation, layer relationships and graphic silhouettes |
| Super Mario World | 16-bit platformer | Silhouette clarity, compact cycles and tile/actor relationships |
| Super Metroid | 16-bit action | Atmospheric palette, anatomy and effects |
| The Legend of Zelda: The Minish Cap | Handheld pixel | Expressive compact poses, colour hierarchy and environmental charm |
| Dragon’s Crown | Painted fantasy | Large illustrated characters, materials and exaggerated proportions |
| Octopath Traveler II | Dimensional pixel | Pixel actors against dimensional lighting and scenes |

## Curate the actual art, not a list of style labels

For each selected game, curate 12–20 representative images: character close-ups, clear silhouettes/key poses, environments, materials and effects. Add at least three short motion studies with source URL, timestamps, action, contact/extreme/transition poses and timing notes. Keep screenshot source IDs and hashes when files are legitimately acquired. Record the exact title and edition: collection screenshots must be verified against the intended game, especially Third Strike. Reject menus, logos, unrelated collection entries, duplicate shots, promotional collages and images too small to inspect.

Separate character art, background art, effects, animation technique and camera presentation. Ori and Octopath are hybrid references rather than proof of an exclusively hand-drawn production pipeline. Historical 8/16/32-bit categories are context; record native size, palette, alpha, perspective and timing independently.

The first focused boards should be Celeste/Shovel Knight for compact pixel clarity; Sonic Mania for expressive platform motion; Metal Slug for detailed arcade animation; Hollow Knight for clean drawn characters; Cuphead for traditional cartoon extremes; GRIS for watercolour treatment; Spiritfarer for acting; and Streets of Rage 4/Skullgirls for drawn combat. Use a few strong exemplars deeply before broadening the library.

Each board needs a written visual breakdown: contour and silhouette, shape proportions, palette/value hierarchy, shading/material, background separation, effect language, key-pose exaggeration, holds, transitions and secondary motion. Select images because they demonstrate those properties. A reviewer should be able to identify the intended visual target without reading a generic style tag.

## Muse generation

Use Muse Spark 1.3 Contributor through Muse Code as the preferred external parent and Muse Image as the separately recorded pixel generator/editor. Pin actual observed versions; record requested versus observed model identity and Contributor mode. See [Meta model documentation](https://dev.meta.ai/models/muse-spark), [Contributor mode](https://dev.meta.ai/help/subscriptions/muse-code-contributor-mode) and [Muse Image generation](https://dev.meta.ai/docs/image-generation).

Translate reference analysis into original character and scene briefs. Research access to a screenshot does not itself grant permission to upload it for generation or training. Record conditioning eligibility separately; use cleared images or original Muse-generated design anchors where required. Preserve the game-led visual analysis even when an image remains research-only. Do not substitute generic asset packs for the chosen art direction.

Generate a calibration character and action test per board before large batches. Judge whether the defining traits have been captured, then freeze the approved style card and reference subset. Generate benchmark sequences and repairs with Muse models; keep procedural controls and downloaded references separate from actual Muse outputs. Retain failed generations, actual tool receipts, input/output hashes and transformations. Never manufacture successful examples or human reviews.

## Parent and generator provenance in framework and web app

Introduce additive typed execution identities and generation-event records linked to existing runs, immutable revisions, assets and provider jobs. Capture parent provider/model/version, Muse Code harness/version, session identity, effective Contributor setting and evidence source. Record the image model, actual request/response IDs, ordered conditioning hashes, prompt digest, original output hashes, editing ancestry and postprocessing independently.

External assertions, locally observed provider responses and unknown attribution must remain distinguishable. Parent changes append timeline events and do not rewrite earlier revisions or reset budgets. Model judgments remain separate from authenticated human decisions. Retain provenance in CLI/MCP/HTTP, saved handoffs, returned corrections and portable dataset closure, with explicit reader capabilities and older records left unknown.

In the web inspector, show compact Parent and Image model fields for the inspected revision, the named game-led style board, actual supplied references and provenance status. Historical views show historical attribution. Reference research does not become an automatic known-good animation lane. Keep one main playback stage and retain current/best revision semantics.

## Tests and delivery

Start with eight curated game-led boards and four original animation requests each: 32 base clips. Cover locomotion, acting, interaction and effects; use appropriate nonuniform holds, loops and terminal actions. Allow at most two model-made repair/negative variants per base within frozen call/cost/time/pixel limits. Capture unknown provider outcomes without blind retries.

Test both real defects and legitimate counterexamples: occlusion, smears, held drawings, squash/stretch, line variation and changing effect topology. Existing exact-colour/landmark profiles cannot establish general painterly or anatomical accuracy; retain unsupported judgments explicitly. Freeze family-safe development and held-out splits before generation, retaining reference/identity/repair ancestry together. Obtain independent real defect reviews and report per-board false alarms, misses, localization, repair regressions and unmeasured coverage.

Implementation sequence: (1) curate and visually review game boards and motion studies, (2) typed parent/generator provenance and immutable reference bindings, (3) inspector/timeline/export support, (4) actual bounded Muse pilot, (5) independent labels and measured expansion. Each code phase uses its own branch/PR and merges after appropriate checks. This document and gallery are research/planning artifacts; they do not claim runtime implementation or completed Muse generations.
