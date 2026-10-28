# Automatic native repair

The external orchestrator creates characters, imports references and proposes a motion guide. The review desk's References screen shows the art, editable/protected masks, fixed source calibration and repair policy together. A reviewer session approves those controls. A guide without a repair policy permits manual work only.

An approved `repair_policy` whitelists operators and caps translation, local attempts and compute steps. A contract may narrow that policy. Masks are native PNG assets: luminance above 127 is selected; protected support overrides editable support. Missing editable support protects the whole frame. Bounds and masks are included in compiled authority and evidence. Changing a guide requires a new immutable guide and approval.

```
framebound animation-compile --project PROJECT --contract-id CONTRACT
framebound animation-start --project PROJECT --revision-id REVISION --idempotency-key WORK
framebound animation-step --project PROJECT --run-id RUN
framebound animation-get --project PROJECT --run-id RUN
framebound animation-run --project PROJECT --revision-id REVISION --idempotency-key WORK
```

MCP exposes `animation_compile`, `animation_start`, `animation_step`, `animation_get` and `source_calibrate`. Start/step/get are also available at `/api/animation/runs`. Run performs bounded local steps until technically ready or blocked. These operations do not approve artistic quality.

The native operators execute integer translation and protected restoration. Translation derives an alpha-centroid delta against the independent phase guide when `native_registration.params.max_anchor_drift_px` is declared. It refuses clipping, wrong dimensions, excessive composed movement or changes outside approved support. Restoration copies the guide baseline outside editable support. Every output records parents, the operation and the exact controls; rights and execution origin survive derivation.

Attempts and compute grants persist per compiled plan/slot across runs and request keys. A project worker lock serializes local execution across processes and releases after process death. Reservation, deterministic artifact identity, immutable child, evaluation and final selection support restart without another attempt. Improved candidates remain internal until all technical and coverage requirements pass. Unsupported or unmeasured work blocks with the actual faults.

`source_calibrate` applies one approved source size/crop/uniform nearest-neighbour scale to every family member, preserving the raw parent. It never fits each pose independently. Native imports remain PNG-only; source decoding must satisfy the calibration's format and orientation policy.

The deterministic public journey and worker-death checkpoints are exercised by `tests/test_automatic_execution.py`. These are labeled test references and reviewer decisions. They are not live provider output or entrant artistic acceptance. Specialist redraw integration and the persistent live gate are tracked separately from these native operators.
