# Hackathon positioning

Event: Meta Global AI Developer Hackathon (Meta × Cerebral Valley), virtual, 26 Oct – 4 Nov 2026. Submissions due 4 Nov, 9:00 PM ET. Judging 4–8 Nov; finals 9 Nov.

## Entry

| Item | Choice |
|---|---|
| Track | Indie developer (solo). Judged on creativity, technical ambition, and whether it works. |
| Theme | Build for Your World: a problem known firsthand — holding one game character consistent across hundreds of AI-assisted animation frames. |
| Judging weights | Impact 30% · Use of Meta AI tooling 25% · Technical depth & execution 20% · Demo 25%. |

## How the project answers each criterion

- **Impact.** Every solo dev and small team using image models for game animation hits this wall. The framework is engine-agnostic, dependency-free, and exports training data that improves the underlying models — useful after the hackathon, designed to become unnecessary.
- **Meta tooling.** Muse Image generates under hash-bound briefs; SAM 3.1 supplies masks for shape measurement when a declared task needs it. An external tool-capable model (Spark or another orchestrator) drives typed CLI/MCP tools. This is a division of labour, not a single API call: deterministic application code gates, providers propose artifacts. No internal general-purpose critic is in the runtime or a readiness gate (corrected handoff Stage A).
- **Technical depth.** Frozen contracts, hash-bound evidence, phase descriptors, feature-span metrology, bounded repair with pixel protection, fail-closed unmeasured handling, and a failure knowledge base generalised from a real production QA system. Deterministic core (pydantic/Pillow/numpy), measured 28 Oct 2026 on macOS arm64 / Python 3.11.4: the public 8-frame 64×64 evaluation service runs warm p50 36.7 ms (cold p50 369 ms); a representative 200-frame workload runs warm p50 932 ms; runtime playback presentation costs 0.85 ms/tick (`benchmark-eval` report). Raster primitives are microbenchmarked separately and never presented as framework latency; no realtime AI-synthesis claim is made from these numbers.
- **Demo.** `python -m framebound demo --profile wp6 --offline` replays Pip (4 clips + 3 evaluated transitions, all pass, badged `[replay/procedural-original]`); injected faults fail with named codes as labeled regressions, never demo totals; the review packet stays UNREVIEWED for a real reviewer. No API key needed for the replay; a key plus the `recorded-run` path turns one real generation live (still pending).

## What actually happened (replaces the ten-day sketch above)

| Dates | Work |
|---|---|
| 26–27 Oct | Prototype foundation (v1 checks/brief/repair/desk/export/demo). |
| 27 Oct | Corrective implementation pass R0–R7 against an independent audit: safe outputs + reliable verification + locked install (R0); real authority/transactions (R1); fail-closed evaluation + reproducible evidence (R2); documented provider wire + durable jobs (R3); bounded repair + correction state (R4); portable training views with pixel-correct masks (R5); actual review experience + browser journey (R6); demonstration as evidence (R7). Nine merged PRs, every gate green. |
| 28 Oct | R8: release re-audit (this document set), public-service benchmark, clean-clone + fresh-environment proof, live/offline semantics check. |
| 28 Oct | Second remediation PRs #21–#27 + S8: portable install identity, operator-gated authority, frozen conditioning, durable controller, provider loops + four-capability runner, durable corrections, split-safe training exports, playback runtime evidence. Full suite 222 passed + 1 env-dependent skip; browser journey green; exact clean-clone install + wheel proof recorded. |
| Remaining | Live provider spike (needs participant credential), authenticated portal check, genuine human review of the demo packet, demo video, submission. See ENTRANT ACTIONS in SUBMISSION_REQUIREMENTS.md. |

## Submission checklist

- [ ] Public repo, MIT, README quick start verified from a clean clone.
- [ ] Demo video (working product, live fault → repair → review → export).
- [ ] Live Meta API path exercised with credits; offline fallback documented.
- [ ] Real-character project included or linked, with its dataset export.
- [ ] Submission form: Indie track, Build for Your World, solo entry.

## Positioning line

Framebound bounds AI animation work so models can verify themselves — and exports every bound, failure, and fix as training data, so they eventually don't need it.

## Muse-generated animation test corpus

The [Muse animation corpus plan](MUSE_ANIMATION_CORPUS_PLAN.md) specifies Muse-generated benchmark artwork, Muse Spark 1.3 Contributor through Muse Code as the preferred parent, separate image-generator provenance, a 48-style research matrix and a downloaded reference catalogue. It stages a small measured hackathon pilot before a larger reviewed corpus. The references and plan are research artifacts; proposed Muse generations, runtime provenance features and independent quality reviews are not yet implemented or observed.
