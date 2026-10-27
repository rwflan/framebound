# Submission requirements — status 2026-10-27 (Europe/Dublin)

Checked: public event page + public overview pages via web search on 2026-10-27. The authenticated
details/rules portal was NOT accessible in this pass (details URL redirects to login; waiver text not exposed).

## Verified from public sources (re-check before submitting)

- Event: Meta Global AI Developer Hackathon (Meta × Cerebral Valley), virtual, 26 Oct – 4 Nov 2026.
  Source: https://cerebralvalley.ai/e/meta-ai-developer-hackathon
- Track: Indie developer track exists; focus described as creativity, technical ambition, and working execution.
- Theme: Build for Your World — a problem the builder knows firsthand.
- Tools listed on the event page: Muse Spark, Muse Wonder, Muse Image, SAM 3.1, Meta open-weight models.
- Public schedule: submissions 4 Nov 2026 at 9:00 PM ET (= 5 Nov 02:00 Europe/Dublin); judging 4–8 Nov; finals 9 Nov.
  Internal submission target: 4 Nov 18:00 Dublin (buffer for packaging/portal problems).
- Model docs index used for integration planning: https://dev.meta.ai/docs/overview
  (Spark https://dev.meta.ai/docs/spark, tool calling https://dev.meta.ai/docs/tool-calling,
  structured output https://dev.meta.ai/docs/structured-output,
  image generation https://dev.meta.ai/docs/image-generation,
  media segmentation https://dev.meta.ai/docs/media-segmentation,
  models https://dev.meta.ai/models/muse-spark).

## UNVERIFIED — do not assume; entrant must confirm in authenticated portal

- Final scoring weights (the prototype doc's 30/25/20/25 must NOT be treated as verified).
- Demo-video duration limit and format.
- Required hosting / public code / public demo URL arrangements.
- Reuse/disclosure rules for pre-existing work (prototype vs event-period work).
- Exact submission fields/portal steps and any required model-use minimum.
- Dependencies between selection criteria and final project rubric.

## Standing instructions

- Resolve all unverified items before disclosure/publish/submit decisions.
- Preserve the honest distinction between pre-existing foundation and work completed during the event.
- Do not infer reuse permission from a public marketing page.
- Next check: entrant opens the authenticated submission portal, records exact fields + rules here with date + source links.

## ENTRANT ACTIONS (human, before 4 Nov 18:00 Dublin)

- [ ] Open the authenticated submission portal; record exact fields, rules, video limit, hosting/code
      arrangements, reuse disclosure, and model-use minimum here with date + source links.
- [ ] Run one live provider spike (Spark tool call + reference-conditioned image + SAM decode) with the
      participant account; save the redacted fixtures next to `fixtures/provider-spike/` and pin versions.
      Until then every demo stays badged `[replay/procedural-original]` — never present it as live.
- [ ] Record the demo video following `docs/DEMO_SCRIPT.md` within the verified duration limit.
- [ ] Submit; paste the submission receipt (ID/URL/timestamp) here. Only the entrant can verify this step.
