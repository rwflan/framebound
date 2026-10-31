# Cohesive desk utilities

Apply `web/public/designs/posthog/DESIGN.md` and `docs/DESIGN.md`: warm stock, compact physical controls, thin borders, restrained shadows, existing window headers and contextual panes. This is a refinement of the established desk, not another layout or shell.

## Navigation

Use one shared ⋯ popover with icon-led rows, concise descriptions, visible current-page state and clear focus/hover treatment. Export, Status and Reviewed guides are utilities, not review workflows. Close on selection, Escape and outside click; Escape returns focus to the trigger. Keep the search, queue, keyboard guide and exact return-to-review location across utility navigation. Routes must open their named page: Reviewed guides must not silently fall through to the inbox, and Status must not switch to a different shell. Preserve older packet routes and available tools.

## Utility windows

Use the existing desk surface and pane title with compact utility tabs and a return-to-review action. Export presents a searchable, bounded run list beside snapshot settings/preview. Separate selection, preview and publication; changed selections invalidate preview. Show exclusions and actual validation without implying human approval. Existing run snapshots remain distinct from local reviewer approval handoffs.

Status leads with current review/generation work, budget commitments and blocked/unknown outcomes. Link work back to the exact animation; never retry unknown acceptance. Put the framework's detailed capability matrix behind a disclosure, label it as framework evidence rather than the current campaign's verdict, and keep wide tables scrollable inside the window.

Reviewed guides presents identity/style/phase thumbnails and the current reference approval, with exact authority and masks in disclosures. Use compact labelled definition lists and the same button treatments. Keep reference approval distinct from animation acceptance; do not invent guides for a project without any.

Keep utility errors/loading/empty states inside their window. Retain technical identifiers in disclosures or titles, wrap long paths, and avoid oversized headings or raw JSON dominating the page. Every active utility tab and inspector view must have a pressed state distinct from keyboard focus.

## Generation action

The button label is exactly `Submit & generate`. Put the per-request maximum in adjacent helper text so the price remains reviewable without inflating the action label. Preserve all current budget and duplicate-submission boundaries.

## Validation

Build, run existing web checks, verify menu dismissal/selected routes/back navigation/searchable export and all three utility pages in the actual browser. Verify the exact submit label, preserve drafts and avoid paid generations or approval actions in visual tests. Publish a remote PR, pass checks and merge to main.
