# Review desk

The desk closes the framework's measured-repair/human-review loop. It is not an animation editor or a gallery. A reviewer needs enough visual evidence to decide on an immutable revision and enough precision to send a bounded correction back to the external model.

## Reviewer tasks

1. **Choose work.** Identify the character, action, revision, technical result, coverage, open corrections and current human decision. Prioritize unresolved work without confusing a passing evaluation with accepted art.
2. **Inspect the actual animation.** Show native frame pixels with authored holds, phase, exact frame and tick position. Support pause, frame/tick stepping and presentation speed. Timing is read-only.
3. **Check the authority and the change.** Make the approved identity/style and the matching phase reference accessible beside the candidate. Compare an actual baseline/parent with the candidate at the same scale and authored time. Include changed pixels and protected/editable scope when available.
4. **Understand evidence.** Show failed, errored and unmeasured checks with their actual reasons and frame scopes. Keep coverage separate from passes. A frame with no recorded failure is not automatically an accepted frame.
5. **Request a bounded correction.** Pause to mark a native-pixel ROI and an authored tick range, choose a category and enter the concrete defect. Submission creates a durable issue and correction task for this exact revision. Surface attempt/candidate/status information and let the reviewer compare, resolve or reopen the issue.
6. **Record a decision and export.** Approve, reject or request changes against the viewed revision and evaluation. Keep human acceptance, technical readiness and release eligibility distinct. Export selected revisions with real exclusions and validation results.

## Interaction concepts

The production React desk now adopts the fifth concept: a full-viewport film workspace with locally hosted DM Sans, gradient navigation and monochromatic grain. Interventions prioritize open corrections, incomplete evidence and revisions awaiting human review. Project selection scopes the reel; Sequences retains the full packet history. The Timeline combines timestamped revisions, evaluations, packets and recorded reviewer events, with source/order filters, event traversal and paged review history. Artifacts without recorded timestamps are not assigned invented dates.

Sequence review keeps reference/baseline and candidate lanes in one draggable, zoomable camera. Measurements, limits and overlapping correction status travel with each candidate frame. Shift-selection scopes authored holds; per-frame plus buttons scope exactly one hold. Fit, 5–200% zoom, anchored wheel/pinch gestures, keyboard navigation and reduced-motion handling affect presentation only. Baselines share a synchronized strip only when contract and timing match; retimed comparisons disclose their timing separately.

Native dialogs provide full evaluation evidence and provenance, pixel-region correction marking, playback at frozen holds, correction attempts/replacements, exact-evaluation decisions and server-derived release eligibility. Local browser review initializes automatically with a same-origin HttpOnly session. Correction requests and decisions persist through the API; the design-candidate pages continue to store only local prototype state. References, task inspection, pixel comparison, export validation and capability status share the production visual system.

Implementation: `web/src/App.tsx` handles navigation and bounded bundle loading; `review-model.ts` derives project scoping, priority, authored-range overlap and chronology; `Film.tsx` and `reel-camera.js` own presentation; `PacketWorkspace.tsx` binds review actions; `Operations.tsx` retains supporting workflows. `desk.css` and `film.css` define the shared visual system. The API exposes project labels and typed observed values, bounds, evidence digests and timestamps without changing review policy. Source checkouts prefer their current `web/dist` over an older packaging-stage build.

The retained HTML design candidates explore different ways to organize these tasks: a sequential
review ceremony, a spatial revision-comparison map, a correction lifecycle board,
a directly annotated canvas, and an aligned sequence/measurement matrix. They
have different primary surfaces and navigation rather than the same panels in
different positions. Detailed inspection is a secondary surface when needed.

Every concept must make the selected revision, its technical evidence, coverage,
and current human decision discoverable. Playback, references, correction scope,
comparison and decisions remain available without forcing a persistent queue or
inspector into every primary view.

The film workspace candidate prioritizes unresolved interventions by project and exposes chronological framework artifacts, check outcomes and human review activity on a draggable, zoomable reel. Sequence comparison uses two synchronized lanes with measured drift, limits and overlapping correction status integrated beneath each candidate frame. Fit, percentage zoom and gesture zoom share the same camera; camera movement changes only the view, while authored timing remains frozen. Measurements open full evidence and frame-level correction controls bind the exact authored hold. Keyboard navigation and reduced-motion behavior remain available. History preserves original timestamps and source actors; technical passes, human acceptance and current release eligibility remain separate.

Screen text is functional: action, revision, phase, measured defect, coverage, decision and origin. There are no slogans, fabricated quality percentages or generic success messages. Unknown or unavailable evidence is labelled, not replaced with a passing state.

## Boundaries

The browser consumes the existing typed API and preserves browser/machine actor separation, stale-evidence checks, immutable revisions, frozen holds, durable correction tasks and export policy. It does not mint authority, change poses, edit timing, imply that procedural/simulated media is live output, or infer that an approved picture is automatically eligible training data.

Sources: `docs/DESIGN.md`, `docs/DEMO_SCRIPT.md`, `framebound/v2/api/dto.py`, `framebound/v2/services/packets.py`, `framebound/v2/services/review_state.py`, `framebound/v2/services/eligibility.py`, and the real browser journey in `web/e2e/journey.mjs`.

The header uses one primary navigation row and one compact sequence row. Lane names occupy a fixed screen-space gutter outside the film pixels at every zoom level. A neutral checkerboard marks transparent viewing areas and improves dark-pixel contrast. The desk monitors a lightweight persisted-store revision marker, including worker/CLI writes, and updates on changes and window focus without remounting review forms or resetting the camera.
