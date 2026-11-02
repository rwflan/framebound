# Desk utility design audit

The live desk was reviewed against `web/public/designs/posthog/DESIGN.md` and `docs/DESIGN.md`. The audit covers the active agent desk, its five ⋯ destinations, the legacy desk routes that share those destinations, and the review shell that surrounds them.

| Surface | Finding | Decision |
| --- | --- | --- |
| Shell, Interventions, Timeline, film and frame windows | The tan stock, blue grey chrome, compact controls, fixed queue and contextual inspector follow the PostHog adaptation. | Keep these shared surfaces. No second navigation or review workflow. |
| Empty Interventions landing | Timeline omitted runs that had revisions but no studio case, leaving the review surface blank even though source history existed. | Include those runs in Timeline → Animations and open the latest timeline entry when Interventions has no actionable item. Keep the queue badge at zero and label submitted sources without implying intake or quality approval. |
| Intake failure in the film window | A long centered block exposed every intake rule and raw failure reason at once. | Lead with the withheld decision and replacement action; put the exact intake evidence in a disclosure inside the existing film window. |
| ⋯ menu | Training and legacy reference tools appeared as peers of everyday utilities. | Keep training as a direct menu action. Group reference approvals with legacy tools. |
| Utility window | Every destination rendered every utility as a tab, including the training journey. | Retain compact Settings, Export and Status tabs. Training and reference approvals use the same window without tabs. |
| Train a model | A large editorial introduction repeated the window title above the existing three step wizard. | Lead with one sentence and the Connect, Choose, Launch steps. Existing runs lead with their name, state and progress. Preserve spend limits and receipts. |
| Settings | A second display heading and repeated storage explanation crowded the connection cards. | Keep the provider cards first, one short introduction and one short storage note. |
| Export | The save step was visible before a preview existed. | Keep selection and preview adjacent; show Save only after a current preview. Keep withheld and exclusion details in a disclosure. |
| Status | The top level status and current work were repeated in nested headings; capability data is dense. | Keep current work and generation allowance as the two visible sections. Keep capability and release evidence collapsed. |
| Reference approvals | Raw identifiers dominated the list and detail header. The current project has no authored guide proposals. | Retain this route for the legacy scoped approval and revocation workflow. Show numbered guides and visual references first; place raw IDs and repair authority in disclosures. Do not treat approval as animation acceptance. |
| Legacy Export and Status routes | Both repeated the window title inside their content. | Remove the duplicate headings while retaining their existing actions and evidence. |

The menu and utility pages continue to use the existing paper palette, title bar, borders, pressed selection, compact type and return to review control. The app has no added studio, sidebar link, or competing feedback route.
