# Why this direction

PostHog's website uses a desktop metaphor with recognisable windows, compact controls and strong material boundaries. Its [website team](https://posthog.com/teams/website) explicitly prioritises a distinctive, consistent experience. Its [product redesign rationale](https://posthog.com/blog/posthog-as-a-dev-tool) explains the practical side: density, fixed panes, contextual tools and keyboard access. The latter describes a 2023 product redesign; the visual reference for this preview is the current [posthog.com](https://posthog.com/) site, inspected 30 October 2026.

The adaptation below is our design interpretation, rather than a claim about measured usability outcomes.

| Choice | Purpose in Framebound |
| --- | --- |
| Separate film and frame windows | Keep the sequence spatially stable while inspecting an individual frame. The frame window remains useful at fit zoom. |
| Warm tan stock, blue frame chrome, black film | Distinguish navigation, the working surface, inspection tools and image content without explanatory copy. |
| Thin borders, restrained offset shadows, pressed buttons | Make boundaries and click targets visible. Consistent physical feedback supplies character without decorative prose. |
| Queue thumbnails with concise finding labels | Recognise the animation, revision and reason for intervention before opening it. |
| Contextual evidence pane | Inspect source results without a modal hiding the film. Changing sequences updates the same pane. |
| Drift bars with actual tolerance markers | Show the size of a discrepancy and its allowed bound together. The scale is linear, 0–100%, and numeric results remain visible. |
| Keyboard search, frame arrows, J/K navigation, real open-file tabs | Move among sequences and revisions while retaining context. Tabs appear only after another revision is opened. |
| Frozen identity and style images | Keep the visual contract available alongside numerical checks. |
| Human review separate from technical checks | Preserve the framework's distinction between measured compliance, a reviewer's decision and release eligibility. |

Removed: the large repeated sequence heading, breadcrumb, packet identifier in the title bar, repeated project footer, empty-correction prose, zero-correction text on every frame, duplicate selected-frame phase/timing and the procedural-media status label. Provenance and preview limitations remain in About and the README. Full check explanations remain available in the evidence pane.

This is a design preview against the existing procedural fixture. It does not replace the live React desk or write to its project.


## Live desk rules (2026-10-31)

These principles govern the live React desk as well as this reference preview. Reuse its shell, queue, film window, contextual frame window, title bars and compact controls. Interventions is the single review entry point. Text feedback, frame marks, generation history and approval are contextual tools in that workflow. Never add a second review navigation item or a parallel studio layout. Put provenance, raw identifiers and machine handoffs in disclosures; keep the inspected frame and actionable controls first. Export stays in the existing workspace menu. Do not add sidebar promotional links. Transparent checkerboard is viewer chrome only: it must never be baked into accepted artwork.

Annotation mode controls belong in the main film window beside the work they affect. Use distinct hand, pen and broad-marker icons; group mode switches, stroke appearance and history actions separately. Pressed mode states must be visible, undo/clear stay quiet and clearly scoped, and drawing must pause playback without panning the film. Keep the on-screen keyboard guide visible, including frame/playback, queue/search and drawing shortcuts. The inspector mirrors the marked frame and holds feedback, not a second drawing toolbar.

Keep the search shortcut keycap inside the search field; do not repeat it in the bottom guide. Search Escape clears the current filter, then leaves the field when already empty. Distinguish persistent selection (pressed fill and inset edge) from transient keyboard focus (outer ring). Reuse the existing palette and controls for these states.

Keep an expand control in the film window title bar. Expanded mode reuses that window and hides the queue and inspector; retain the header, drawing tools, transport and shortcut guide. Show an explicit Restore action with Esc and a Feedback return action. Preserve the selected take, frame, zoom and draft across expansion; pause playback on layout changes. Keep history compact so the film gets the added space.


Utility navigation follows the same material language as review: one icon-led ⋯ popover, compact selected tabs, the existing window title bar and an exact return-to-review link. Export, Status and Reviewed guides stay in the current desk shell. Do not route them into another application layout. Use bounded lists, adjacent settings/preview panes and disclosures for detailed authority, raw evidence and capability matrices. Keep the primary generation action label `Submit & generate`; show the request price in adjacent helper text. See `docs/DESK_UTILITIES_PLAN.md` for the implemented flow.

Playback keeps a moving sprocketed film rail visible beneath a stable projection in the existing window. Use the authored clock for projection, rail and scrubber; keep the right inspector pinned during play. Scrubbing pauses and selects a frame. Keep timeline and labelled slow-speed controls visible, including in expanded mode; honour reduced motion. Review starts at ½× and never changes authored timing. See `docs/FILM_PLAYBACK_PLAN.md`.

Paused inspection uses the same large projection and visible scrubbable film rail as playback; avoid a separate Inspect film mode. Drawing overlays sit on the large paused image. Keep image zoom/fit local to the projection, speed controls compact, and the right inspector pinned during playback. Feedback supports several independently frame-scoped issues in one take-bound bundle: a compact editable list, explicit affected-frame pressed states, global native-frame marks, and one `Submit & generate` action. Keep the existing comment when submitting without an extra Add click; preserve saved drafts. Show the quote for the entire bundle, without multiplying generation calls by issue count. See `docs/PROJECTION_FEEDBACK_BUNDLES_PLAN.md`.

Every review queue item needs an evidence-based reason, repeated in a compact notice in its film window. Distinguish first human review, checks not run, failed checks, unmeasured coverage and verification of earlier feedback. Evidence must bind the displayed take: show affected-frame links and observed/expected values for actual findings, and label previous-take reports separately. Never inherit a source take’s checks onto a newly generated replacement or imply that an isolation gate assessed animation quality.
