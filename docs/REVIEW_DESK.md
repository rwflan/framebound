# Review desk

The desk closes the framework's measured-repair/human-review loop. It is not an animation editor or a gallery. A reviewer needs enough visual evidence to decide on an immutable revision and enough precision to send a bounded correction back to the external model.

## Reviewer tasks

1. **Choose work.** Identify the character, action, revision, technical result, coverage, open corrections and current human decision. Prioritize unresolved work without confusing a passing evaluation with accepted art.
2. **Inspect the actual animation.** Show native frame pixels with authored holds, phase, exact frame and tick position. Support pause, frame/tick stepping and presentation speed. Timing is read-only.
3. **Check the authority and the change.** Make the approved identity/style and the matching phase reference accessible beside the candidate. Compare an actual baseline/parent with the candidate at the same scale and authored time. Include changed pixels and protected/editable scope when available.
4. **Understand evidence.** Show failed, errored and unmeasured checks with their actual reasons and frame scopes. Keep coverage separate from passes. A frame with no recorded failure is not automatically an accepted frame.
5. **Request a bounded correction.** Pause to mark a native-pixel ROI and an authored tick range, choose a category and enter the concrete defect. Submission creates a durable issue and correction task for this exact revision. Surface attempt/candidate/status information and let the reviewer compare, resolve or reopen the issue.
6. **Record a decision and export.** Approve, reject or request changes against the viewed revision and evaluation. Keep human acceptance, technical readiness and release eligibility distinct. Export selected revisions with real exclusions and validation results.

## Production workspace

The production React desk uses the approved PostHog-inspired desktop design: warm window chrome, system typography, compact controls, a project explorer and a separate frame inspector. The original design candidates remain archived HTML previews; the live desk uses the real typed API.

Interventions open first and prioritize open corrections, incomplete evidence and revisions awaiting human review. The sidebar groups animations and chronological events by project. Timeline source/order filters and paged history retain recorded timestamps and actors. A single click on a packet-bound event opens its sequence; an adjacent detail action exposes the event itself. Search (⌘/Ctrl K), J/K intervention navigation and tabs for opened revisions keep work accessible without another header menu.

Selecting an animation immediately selects and centres its earliest frame with a failed, errored or unmeasured check, incomplete-coverage occlusion, or overlapping unresolved correction. Analyzer output order does not determine which frame opens. Clean clips open on their first frame. The camera can centre the first and last frames as well as interior frames; live data updates preserve the current selection, camera and unsent review drafts.

Reference/previous-revision and candidate images share a draggable, zoomable camera. The stock is flat near-black (#050505), with alpha-cut sprocket holes and a neutral transparency checkerboard inside each aperture. Reference, Candidate and Checks labels are translucent row legends using the same type and ruled detail as the window headers. Their low-opacity wash reveals the pixels beneath. They follow the first complete visible frame, fade into the image, remain readable at overview zoom and reserve no side gutter. The Checks legend sits above the first measurement line.

Area/width drift, limits and attached correction notes occupy a separate warm paper measurement track below the candidate film. Columns stay aligned with the images as the camera moves. Failed measurements receive amber emphasis; compact overview states simplify the sheet while full values remain in the selected-frame inspector. Measurements are never drawn inside the film stock.

The frame inspector keeps the selected image, numerical checks, correction status, frozen identity/style references and human acceptance beside the sequence. Full evidence and provenance open in the same side pane. Native dialogs handle detailed authored-tick playback, native-pixel correction regions, correction attempts/replacements, exact-evaluation decisions and server-derived release eligibility. Shift-selection scopes multiple authored holds; the correction action binds the selected range. Main playback, speed, frame arrows, zoom and Fit affect presentation only. Baselines share a synchronized strip when contract and timing match; retimed comparisons retain their dedicated view.

Local browser review initializes automatically with a same-origin HttpOnly session. Corrections and decisions persist through the API. References, task inspection, pixel comparison, export validation and capability status share the same window, colour, type, spacing and state language. The desk monitors the persisted-store revision marker, including worker/CLI writes, without a manual refresh control.

Implementation: `web/src/App.tsx` handles navigation, project grouping and bounded bundle loading; `review-model.ts` derives priority, first attention, authored-range overlap and chronology; `Film.tsx` and `reel-camera.js` own presentation; `PacketWorkspace.tsx` binds the persistent inspector and review actions; `Operations.tsx` retains supporting workflows. `desk.css` and `film.css` define the visual system. Source checkouts serve their current `web/dist`; `scripts/sync_desk_build.py` stages a build for packaged installs.

Validation: `npm --prefix web run test:unit` checks timing, native geometry, camera bounds/centering and attention ordering. `node web/e2e/journey.mjs` exercises the real API and browser lifecycle, including correction persistence, replacement review and export. The read-only `node web/e2e/workspace-layout.mjs` checks a running project with a scoped failing check (default port 8765; override `WORKSPACE_URL`), including per-animation initial selection, edge-tab overlap, a separate aligned measurement sheet, contextual evidence, search, zoom and responsive controls.

## Boundaries

The browser consumes the existing typed API and preserves browser/machine actor separation, stale-evidence checks, immutable revisions, frozen holds, durable correction tasks and export policy. It does not mint authority, change poses, edit timing, imply that procedural/simulated media is live output, or infer that an approved picture is automatically eligible training data.

Sources: `docs/DESIGN.md`, `docs/DEMO_SCRIPT.md`, `framebound/v2/api/dto.py`, `framebound/v2/services/packets.py`, `framebound/v2/services/review_state.py`, `framebound/v2/services/eligibility.py`, and the real browser journey in `web/e2e/journey.mjs`.
