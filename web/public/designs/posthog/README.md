# PostHog-inspired review preview

A separate, functional design candidate. The live React review desk is unchanged.

Reference: [PostHog's current website](https://posthog.com/), inspected 30 October 2026. The preview adapts its desktop window structure, compact navigation, system typography, warm neutral palette, thin borders and orange emphasis to animation review. It uses no PostHog brand illustrations or logos.

## Open

Build the web app and use `/designs/posthog/` on the existing Framebound server, or serve public files directly:

```sh
python3 -m http.server 8933 --bind 127.0.0.1 --directory web/public
```

Then open <http://127.0.0.1:8933/designs/posthog/>.

## Behavior

- Keyboard search (⌘/Ctrl K), frame navigation (arrows), next/previous intervention (J/K), expandable film workspace and tabs for opened revisions.
- Interventions first; chronological revision, evaluation, packet and human-review events are grouped under the fixture project. Clicking an event opens that sequence.
- Drag the aligned black film strips, zoom, fit, select frames or use arrow keys while the film has focus. Playback follows authored holds and ticks per second; non-looping clips stop at their end.
- Compare frozen phase references or the actual previous revision. Measurements show the existing fixture's results, including failure, unmeasured and not-applicable outcomes.
- Inspect full evidence alongside the film. Frozen identity and style references remain available in the frame window.
- Request corrections with tick ranges and optional native-pixel regions. Save human decisions against the exact revision, evaluation and evidence digest.

Frames and checks come from the existing procedural design fixture in `../review-desk/fixture.js`. This preview does not call the production review API. Requests and decisions persist only under `framebound.posthog-preview.v1` in this origin's browser local storage. They do not approve releases or modify the live project. The release panel displays the fixture's original eligibility result.

## Check

With the static server running:

```sh
node web/e2e/posthog-preview.mjs
npm --prefix web run build
```

The acceptance script uses an isolated browser context and checks fixture fidelity, fit at every viewport, correction regions and persistence, review decisions, timeline navigation, contextual evidence, frozen references, search, focus mode, non-looping playback, dragging, keyboard navigation and responsive layouts. The design rationale is in [DESIGN.md](DESIGN.md). Screenshots go to `output/playwright/posthog-preview` (override with `PREVIEW_SHOTS`); use `PREVIEW_URL` to target another server.
