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
- **Meta tooling.** Muse Image generates under hash-bound briefs; SAM 3.1 supplies masks for shape measurement; Muse Spark/Wonder orchestrate via MCP tools and act as advisory visual critics. This is a division of labour, not a single API call: deterministic checks gate, models create and critique.
- **Technical depth.** Frozen contracts, hash-bound evidence, phase descriptors, feature-span metrology, bounded repair with pixel protection, fail-closed unmeasured handling, and a failure knowledge base generalised from a real production QA system. Pure-stdlib core: runs anywhere, ~20 ms/frame at demo scale.
- **Demo.** `python -m framebound demo` builds a procedural character, passes its clean cycle, fails four injected faults with four named codes, and selects a bounded repair — then the review desk and dataset export run live. No API key needed for the demo; keys turn generation and critique live.

## Ten-day plan

| Days | Work |
|---|---|
| 1 (26 Oct) | Foundation: contract, checks, brief, repair, review desk, dataset export, procedural demo. Public repo. |
| 2–3 | Live Meta integration: Muse Image generation under briefs with real character art; SAM 3.1 masks replacing alpha where needed; Muse Spark critique in the loop. Tune tolerances on real frames. |
| 4–5 | Real project: one game character, 3+ clips (run, jump, attack), end-to-end generation with fault/repair history recorded. |
| 6–7 | Review-desk polish from real use; video/GIF import; batch clips; dataset export from the real project; first preference-pair count. |
| 8 | Hardening: edge cases (occlusion, aliases), performance pass, docs, empty-state and error handling. |
| 9 | Demo video: problem, live loop, fault caught, repair, human correction round-trip, dataset. Submission draft. |
| 10 (4 Nov) | Final checks, submission before 9:00 PM ET. |

## Submission checklist

- [ ] Public repo, MIT, README quick start verified from a clean clone.
- [ ] Demo video (working product, live fault → repair → review → export).
- [ ] Live Meta API path exercised with credits; offline fallback documented.
- [ ] Real-character project included or linked, with its dataset export.
- [ ] Submission form: Indie track, Build for Your World, solo entry.

## Positioning line

Framebound bounds AI animation work so models can verify themselves — and exports every bound, failure, and fix as training data, so they eventually don't need it.
