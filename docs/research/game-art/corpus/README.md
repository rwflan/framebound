# Muse animation corpus — status

Initial eight game-led style boards and 32 original animation briefs.
Machine-readable source: [boards.json](boards.json). Plan: [MUSE_ANIMATION_CORPUS_PLAN.md](../../../MUSE_ANIMATION_CORPUS_PLAN.md).

## Status: planning artifact, no generation performed

- 8 boards, 4 original briefs each (locomotion, acting, interaction, effects) = 32 briefs.
- All calibrations: pending. All board approvals: unapproved (approval must be recorded, never invented).
- All 24 motion-study slots: pending. No footage examined, no timestamps recorded.
- All visual-breakdown `observed_evidence` fields: pending. One inspection attempt
  (Celeste storefront fetch) returned page chrome only — no artwork pixels obtained.
- Generation calls made: 0. No receipts, screenshots, human labels, or procedural pixels fabricated.
- Conditioning eligibility everywhere: `research_only`. Nothing acquired (no files, no hashes).

## Boards

| Board | Games | Split |
|---|---|---|
| board-01-compact-pixel-clarity | Celeste, Shovel Knight | development |
| board-02-expressive-platform-motion | Sonic Mania | development |
| board-03-detailed-arcade-animation | Metal Slug 3 | development |
| board-04-clean-drawn-characters | Hollow Knight | development |
| board-05-traditional-cartoon-extremes | Cuphead | development |
| board-06-watercolour-treatment | GRIS | development |
| board-07-drawn-acting | Spiritfarer | held_out |
| board-08-drawn-combat | Streets of Rage 4, Skullgirls 2nd Encore | held_out |

Split frozen pre-generation by board identity family. Finite limits per base:
max 3 calls (1 base + 2 repairs), 512x512x48px, 600s/call, 1800s/base, USD 5/base.

## Gaps before any pilot

1. Pixel-level visual review of all 40 referenced screenshots.
2. 24 motion studies with source URLs, timestamps, pose/timing notes.
3. Edition verification for all 10 named games.
4. Remaining games.json indices (4-7/4-6/4) not yet curated.
5. Calibration tests, board approvals, Muse Image availability.

The corpus call ceiling reserves 16 calibration calls in addition to 96 base/variant calls (112 total), within USD 200. These ceilings are proposed frozen inputs, not evidence of spend or permission to exceed existing provider grants. Calibration judgments may be model judgments; independent human defect labels remain separate.
