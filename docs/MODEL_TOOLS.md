# Model-facing tools

The external orchestrator uses the v2 CLI or MCP stdio server. Humans use the persistent review desk for references, comparisons and decisions. There is no internal general-purpose adviser or critic.

```sh
framebound v2-mcp --project PROJECT
framebound capabilities
```

The MCP server uses the official SDK handshake and actual tool discovery. Enumerate its tools rather than copying a historical catalogue. All transports call the same application services; current capability and pending-evidence states are available at `/api/capabilities`.

## Public creation

```sh
framebound project-create --project PROJECT --project-id PROJECT_ID --name NAME
framebound asset-import --project PROJECT --src FILE --asset-id ASSET_ID
framebound character-propose --project PROJECT --character character.json
framebound guide-propose --project PROJECT --guide guide.json
framebound contract-propose --project PROJECT --contract contract.json
framebound clip-create --project PROJECT --contract-id CONTRACT --revision-id REVISION --frames ASSET_IDS --phases PHASES
```

MCP provides `project_create`, `asset_import`, `character_propose`, `guide_propose`, `contract_propose` and `clip_create`. Create a stored project and character, distinct identity/style inputs, independent phases and an immutable guide. The desk reviewer approves the exact art, support, calibration and repair policy. The orchestrator cannot approve or revoke that authority through a model tool. See [the native sprite profile](NATIVE_SPRITE_PROFILE.md) for the required inputs and unsupported cases.

## Automatic work

```sh
framebound animation-compile --project PROJECT --contract-id CONTRACT
framebound animation-start --project PROJECT --revision-id REVISION --idempotency-key WORK
framebound animation-step --project PROJECT --run-id RUN
framebound animation-get --project PROJECT --run-id RUN
framebound animation-run --project PROJECT --revision-id REVISION --idempotency-key WORK
```

MCP exposes the matching compile/start/step/get operations. `animation-run` is a bounded CLI convenience loop. Consume returned diagnostics and persisted state. Deterministic native operators execute within approved controls. Only a complete passing candidate reaches `technically_ready`; its artistic acceptance remains unreviewed. Unsupported or missing measurements return a specific blocker. Do not replenish grants by renaming contracts or request keys.

A supported per-frame fault may queue scoped redraw and return `awaiting_provider` with its durable job ID. Default work is offline. An authorized live start uses frozen provider settings and an existing operator grant. Use the normal `job_get` / `orchestrator_run` / `orchestrator_send` services, then resume `animation_step`. Reference, source, phase and support images are transmitted; the framework composites the proposed result and independently rechecks it. Optional SAM proposals never grant artistic approval or repair authority.

Unknown upstream outcomes require operator reconciliation, never blind resubmission. Models do not mint grants or recovery receipts. See [provider recovery](PROVIDER_RECOVERY.md) and [provider contracts](PROVIDER_CONTRACTS.md).

## Human feedback and training

The desk's ROI/frame-range issue becomes a durable task. Consume `corrections_list`, claim through `correction_claim`, submit the exact scoped result through `correction_submit`, and retain the returned comparison identity. Claims are fenced and payload replay must be identical. The reviewer compares, resolves or reopens subjective issues. A technical improvement does not resolve artistic feedback automatically.

Export through the desk/API or CLI and validate the moved snapshot. Positive membership requires current eligible decisions, rights and origin. Simulated or unresolved ancestry is retained as explained research material rather than promoted into positives. Preference data requires an explicit comparison packet. See [snapshot consumption](SNAPSHOT_CONSUMPTION.md) for a decoded native-pixel batch.

The v1 file-oriented `check`, `preflight`, `repair-plan`, `repair-evaluate` and `mcp` commands remain compatibility paths. New durable workflows use `v2-mcp` and the services above.
