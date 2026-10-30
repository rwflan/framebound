# Implementation status

The active framework has no internal general-purpose adviser or critic. An external orchestrator supplies typed work through CLI, MCP or HTTP. Framebound compiles reviewed controls, measures actual pixels, executes authorized native repairs, queues bounded image work when needed, and independently checks the result before presenting a comparison.

## Agent-led v3 path

The reference-free task/agent loop, saved interventions and handoff, packet-free
workspace, portable training views and optional source-time correspondence are
implemented. The tracked-scene profile and offline quality benchmark are a
provisional broader milestone, with camera/visibility/event counterexamples.
See [the requirement audit](AGENT_WORKFLOW_IMPLEMENTATION_AUDIT.md) and
[the public operations](AGENT_LOOP.md). Tests and procedural benchmark cases do
not supply independently reviewed generated-art reliability evidence.

## Reviewed-guide evidence by capability

| Capability | Implemented | Counterexample tested | Public integration | Participant live observation | Entrant artistic acceptance |
|---|---|---|---|---|---|
| Project, character, guide and contract creation | Yes | Yes | CLI, MCP, HTTP and desk | Not applicable | Pending for entrant art |
| Native translation and protected restoration | Yes | Yes | Real MCP workflow and killed-worker recovery | Not applicable | Pending |
| Scoped image generation/edit and optional SAM | Yes | Yes | Public jobs and strict simulated transport | Pending | Pending |
| Atomic dispatch, frozen requests and operator recovery | Yes | Yes | CLI/HTTP grants and receipts | Pending | Not applicable |
| Playback, issue range/ROI, correction, reject/approve, resolve/reopen | Yes | Yes | Real Chromium over the API, including server restart | Not applicable | Test reviewers only |
| Snapshot publication and training consumption | Yes | Yes | Desk export, moved standalone validation and decoded training batch | Not applicable | Test decisions only |
| Authenticated portal check, entrant video and submission receipt | No | Not applicable | Pending entrant action | Pending | Pending |

The same distinction is available from `/api/capabilities`. Test reviewer identities, procedural references and strict fake provider responses prove engineering boundaries. They do not prove a participant account works or that an artist accepted the demo.

## What the public journey exercises

`web/e2e/journey.mjs` starts with an empty project and speaks the actual MCP stdio protocol. Two procedural character families have different pixels and reviewed controls. A desk reviewer fixture approves references. The engine repairs an exterior fault, survives a worker process killed after rendering, and resumes without another attempt. Actual frame bytes are compared independently.

The browser then measures a real visual difference, marks an issue with spatial and temporal scope, and survives a killed API server. The normal correction CLI submits a scoped replacement. Reject, approve, resolve and reopen change current eligibility. A simulated derivative with unresolved ancestry remains excluded from positives even after a test reviewer approves its art. An unrelated provider note and blob are excluded from the selected export.

The desk publishes an export, which is moved before validation. The source database is made unavailable. The consumer loads an actual native RGBA preference batch from the moved snapshot. A process-level socket guard covers setup, MCP, workers, API, CLI and consumption; any nonlocal connection fails the run. Procedural fixture positives require explicit opt-in.

## Reproducible checks

Use the locked installation in the README, including the export-validation extras and a Python interpreter with working `lzma`. Then run:

```sh
python -m pytest tests/ -q
npm --prefix web run typecheck
npm --prefix web run build
python scripts/sync_desk_build.py
sh scripts/verify-local
```

The verifier includes the real browser journey. Focused counterexamples live in `test_automatic_execution.py`, `test_scoped_specialist_repair.py`, `test_dispatch_reservations.py`, `test_provider_recovery.py`, `test_specialist_resume.py`, `test_snapshot_publication.py`, `test_reference_revocation.py` and `test_public_transport_contracts.py` under `tests/`. They include actual process death, overlapping dispatch, stale authority, changed configuration, corrupted replay, protected pixels, invisible masks and pending-operation portability.

## Practical limits

Native repair currently provides rigid translation and approved protected restoration. Other measured shape, palette and phase failures can queue scoped image work; they are not silently replaced with a generic model opinion. Checks cover declared measurable controls. They do not prove every possible anatomical or artistic property. Unsupported or incomplete measurements block technical readiness.

Evaluation rechecks the whole revision; there is no incremental frame cache. The benchmark reports small and 200-frame evaluation, actual local repair, and playback separately. None measures provider generation latency or guarantees real-time image synthesis. Fixed family calibration can normalize a provider source only when the exact crop and uniform scale were reviewed; arbitrary per-pose fitting is refused. Legacy registrations with nonzero transforms require native rematerialization and re-evaluation.

The filesystem and the process operator are trusted. HTTP sessions constrain reviewer actions; operator secrets constrain grants and reconciliation. Someone who can rewrite the database or local application code bypasses those boundaries.

For authorized live work use [PROVIDER_RECOVERY.md](PROVIDER_RECOVERY.md). Existing approved participant references, an explicit grant, a credential and a persistent work directory are required. Ambiguous sends require a receipt; they never trigger blind redispatch. Portal and submission inputs remain tracked in [SUBMISSION_REQUIREMENTS.md](SUBMISSION_REQUIREMENTS.md).
