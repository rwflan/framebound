# Review desk design studies

Five static HTML pages: `index.html` is a visual selector for four interactive directions.

- **Afterhours** — dark screening room, large player, compact diagnostics.
- **Paperwork** — paper contact sheet, eight poses visible together.
- **Split** — full-width revision wipe in lilac and acid green.
- **Orbit** — cobalt motion map with a circular frame selector.

Open `index.html` directly, or use the existing Vite server at `/designs/review-desk/`. The production web build copies this folder unchanged. No installation, external fonts, network media, or API connection is required.

Click the top navigation or press **1–4** to switch directions; **Escape** returns to the selector. **Space** toggles playback and **←/→** steps through frames. Frames, guides, marks, and decision controls work in every candidate. Split includes a draggable comparison wipe; Orbit includes sample queue selection and scrubbing.

These are UI studies. The original SVG courier poses and metrics are illustrative fixtures, not project frames or check results. Review decisions only affect the current page and reset on navigation. The existing production review desk is unchanged.

Validation: production Vite build, JavaScript syntax check, browser screenshots at desktop and phone widths, overflow checks, and interactive checks for playback, frame selection, guides, marking, decisions, keyboard navigation, wipe, queue, and scrubber.
