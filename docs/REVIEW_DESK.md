# Review desk

The desk closes the framework's measured-repair/human-review loop. It is not an animation editor or a gallery. A reviewer needs enough visual evidence to decide on an immutable revision and enough precision to send a bounded correction back to the external model.

## Reviewer tasks

1. **Choose work.** Identify the character, action, revision, technical result, coverage, open corrections and current human decision. Prioritize unresolved work without confusing a passing evaluation with accepted art.
2. **Inspect the actual animation.** Show native frame pixels with authored holds, phase, exact frame and tick position. Support pause, frame/tick stepping and presentation speed. Timing is read-only.
3. **Check the authority and the change.** Make the approved identity/style and the matching phase reference accessible beside the candidate. Compare an actual baseline/parent with the candidate at the same scale and authored time. Include changed pixels and protected/editable scope when available.
4. **Understand evidence.** Show failed, errored and unmeasured checks with their actual reasons and frame scopes. Keep coverage separate from passes. A frame with no recorded failure is not automatically an accepted frame.
5. **Request a bounded correction.** Pause to mark a native-pixel ROI and an authored tick range, choose a category and enter the concrete defect. Submission creates a durable issue and correction task for this exact revision. Surface attempt/candidate/status information and let the reviewer compare, resolve or reopen the issue.
6. **Record a decision and export.** Approve, reject or request changes against the viewed revision and evaluation. Keep human acceptance, technical readiness and release eligibility distinct. Export selected revisions with real exclusions and validation results.

## Information hierarchy

- Persistent project navigation and reviewer session.
- A review queue with actionable status and real thumbnails.
- The animation and frame timeline as the main workspace.
- Contextual findings, references and correction controls beside that workspace.
- A compact decision area bound to the current revision; supporting evidence/history on demand.

Screen text is functional: action, revision, phase, measured defect, coverage, decision and origin. There are no slogans, fabricated quality percentages or generic success messages. Unknown or unavailable evidence is labelled, not replaced with a passing state.

## Boundaries

The browser consumes the existing typed API and preserves reviewer pairing, stale-evidence checks, immutable revisions, frozen holds, durable correction tasks and export policy. It does not mint authority, change poses, edit timing, imply that procedural/simulated media is live output, or infer that an approved picture is automatically eligible training data.

Sources: `docs/DESIGN.md`, `docs/DEMO_SCRIPT.md`, `framebound/v2/api/dto.py`, `framebound/v2/services/packets.py`, `framebound/v2/services/review_state.py`, `framebound/v2/services/eligibility.py`, and the real browser journey in `web/e2e/journey.mjs`.
