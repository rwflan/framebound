# Review desk design candidates

Five HTML candidates present the same framework review case through different layouts:

1. `index.html`: queue, main preview, evidence inspector and scoped correction form.
2. `02-ledger.html`: measurement ledger beside frame and reference evidence.
3. `03-comparison.html`: synchronized baseline/candidate pixels with references and findings.
4. `04-triage.html`: findings lead frame selection and correction authoring.
5. `05-sequence.html`: phase/hold contact sheet with a selected-frame comparison.

Use the numbered navigation or **1–5** to switch. Open through the project's Vite server at `/designs/review-desk/`, or serve this folder with a local HTTP server. HTTP is required for reliable canvas pixel comparison. There are no external assets, fonts, libraries or API dependencies.

## Functional review case

`scripts/build_review_design_fixture.py` generates original procedural Pip PNGs and actual evaluations through the production project/asset/character/guide/contract/clip/packet services. It uses a named test reviewer in a disposable project to bind fixture reference authority. It does not approve entrant art.

- Run r02 has measured silhouette-area drift at frame 04 against the frozen same-phase reference.
- Run r03 is a clean replacement for comparison; its passing technical result is independent of human acceptance.
- Jump has partial coverage and an unmeasured declared feature. Contract-declared occlusions remain separately visible as not applicable.
- Idle provides a passing, unreviewed clip.

All five candidates support frame/tick stepping, locked authored holds, presentation speed, native integer zoom, baseline/side-by-side/blink/real RGBA difference, frozen identity/style/phase references, fixture edit/protected scope, findings and measured bounds, and native-pixel ROI/tick-range correction authoring.

Local review events bind the exact revision, packet, evaluation and evidence digest. Local correction requests include the real frame instance, authored tick range and native ROI. The Corrections dialog supports inspection, replacement comparison, approval-gated local resolution and reopening. Local decisions and tasks persist across reloads and design navigation; reopening revokes local acceptance. Review JSON downloads these prototype records. They are not submitted to the model or a server, and they cannot confer production approval or release eligibility.

The header labels the procedural sample and local prototype. **Reset** clears local prototype review only. Regenerating the fixture creates new evaluation identities; reset local state after regeneration. The production React desk and its authentication, API and policy are unchanged.

The information architecture is documented in `docs/REVIEW_DESK.md`, grounded in the framework's current design, service contracts and browser acceptance journey. The desk never edits poses or authored timing and never treats missing measurements as passes.
