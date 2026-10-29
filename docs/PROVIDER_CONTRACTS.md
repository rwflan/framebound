# Specialist provider contracts

Framebound uses image generation/edit and optional SAM as bounded artifact providers. An external orchestrator can be Spark or another tool-capable model. There is no internal general-purpose critic, and no critic call is required for repair, readiness, export or the live probe.

This document describes the implemented adapters and their tested boundaries. A strict fake transport can establish what bytes Framebound sends and how it handles a response. It cannot establish that the participant's account or the current upstream service accepts that request. Participant live observation remains pending.

## Implemented request path

The v2 image and SAM adapters build Responses requests. Image generation carries the approved identity and style pixels plus applicable phase, baseline, repair and support images. An edit chains a durable successful response for the same target and retains reference ancestry. SAM receives the actual source image and returns source-bound proposals only after successful status and decode checks. No match, failed status, malformed output or missing mask is a failed capability rather than successful segmentation.

The job freezes the complete executable request, model, endpoint, approved scope and offline setting before dispatch. Changing environment variables or run settings cannot silently change that queued request. Only the controller can reserve an attempt and issue a one-use permit consumed at the HTTP boundary. Adapter convenience calls cannot send without it. Atomic job, run, target and operator-grant accounting prevents overlapping workers from sending twice or resetting a ceiling by renaming a contract.

A scoped redraw has a persisted authorized operation and exact baseline, source slot, phase, editable and protected pixels. Provider output is normalized only through the approved fixed family calibration. The native writer composites within the effective support, preserves exterior and protected pixels, derives provenance from its actual parents, and re-evaluates the whole revision. A provider success is not technical readiness or artistic acceptance.

## Origins and evidence

Offline jobs persist `not_configured` without contacting a provider, even if a key happens to exist. An injected fake transport stays simulated through materialization, further repair and export. Actual live origin is recorded at the consumed send boundary; an operator receipt cannot upgrade a simulated origin. Derived rights remain conservative across all parents. Redacted requests, responses, hashes and immutable recovery receipts remain addressable artifacts.

Unknown outcomes require an operator to reconcile the original request using a matching receipt. Confirming no upstream acceptance can release the quoted money reservation while retaining the consumed call. Abandonment retains uncertain reservation. An equivalent receipt replays the same result; a conflicting receipt fails. See [PROVIDER_RECOVERY.md](PROVIDER_RECOVERY.md).

## Participant live probe

```sh
sh scripts/verify-local --live --work-dir /outside-repo/participant-spike
```

The first invocation writes a persistent configuration shape and reports pending. Configure an existing genuinely approved project, operator grant and explicit spend ceiling before supplying a participant credential. The probe records image generation, chained edit and decoded SAM. It resumes existing jobs and bundles rather than repeating completed paid stages. The gate requires actual live origin and complete passing technical evidence. Human art approval remains separate.

The v1 prototype and historical provider fixtures are compatibility artifacts. They are not the active v2 request contract. The authoritative builders and parser checks are `framebound/v2/providers/image.py`, `sam.py` and `wire.py`; durable execution is in `services/jobs.py`, `orchestrator.py`, `dispatch.py` and `provider_recovery.py`.
