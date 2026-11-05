# Provider grants, receipts and persistent spikes

The controller freezes the executable request, model, endpoint, references and edit parent before sending. An edit must name a durable successful response for the same target. A one-use permit reserves job/run/target/operator units and checks active operation authority at the network boundary. Image/edit/SAM use shared grants.

An operator grant can authorize dispatch units or a monetary ceiling backed by an explicit maximum quote and pricing reference. Money uses integer micro-USD reservations. A call grant never claims to enforce dollars. Reservations are conservative quote holds; actual billing and provider latency remain unmeasured without live evidence. Negative, zero and non-finite money bounds refuse before transmission.

Settlement is explicit:

| Event | Call units | Money reservation | Next step |
| --- | --- | --- | --- |
| Verified cancellation before permit consumption | Refunded, including run/target reservation | Refunded | Cancelled job stays terminal |
| Known provider completion | One consumed dispatch | Maximum quote remains held | Use recorded output/outcome |
| Ambiguous timeout/crash after transmission | Held/consumed | Held | Operator receipt required |
| Operator confirms non-acceptance/no charge | Transport entry remains consumed | Last maximum quote refunded | Same frozen job may requeue within remaining grants |
| Operator attaches actual response | No new dispatch/attempt | Held | Decode and complete the same job atomically |
| Operator abandons ambiguity | Consumed | Held | Job fails; no automatic retry |

Use the operator-only CLI or API to reconcile. The receipt JSON binds an exact request digest and current version:

```json
{
  "id": "account-receipt-unique-id",
  "expected_version": 7,
  "request_sha256": "<64-character frozen request digest>",
  "outcome": "response",
  "receipt_reference": "<actual provider/account receipt reference>",
  "evidence_note": "<operator-observed evidence>",
  "provider_response": {"status":"completed","id":"<actual response>","output":[]}
}
```

This example is a shape, not a valid generated image. `response` must contain actual decodable image output or the SAM token lane; no output is invented. `not_accepted` and `abandoned` omit `provider_response`. Identical receipts replay their original result; changed payloads or stale/foreign request identities conflict. Image and SAM completion, output records and receipt recording share one transaction. A failed provider result cannot become a usable mask merely by being reconciled.

```
framebound provider-reconcile --project PROJECT --job-id JOB --receipt receipt.json
framebound provider-grant-get --project PROJECT --grant-id GRANT
framebound provider-grant-revoke --project PROJECT --grant-id GRANT --expected-version VERSION
```

These operator mutations require `FRAMEBOUND_OPERATOR_SECRET` or the explicit secret option/header. The secret is never part of a persisted job, receipt or artifact. Reviewer authority and artistic decisions are separate.

## Persistent live spike

```
sh scripts/verify-local --live --work-dir /outside-repo/participant-spike
```

The first invocation writes a persistent `live-config.json` shape and reports pending. Configure an existing project, genuinely approved references, contract/baseline/slot, a new revision ID, stable workflow key and an operator grant. Then supply the participant API key and explicit `FRAMEBOUND_SPEND_CEILING` (`calls-N`, or a USD ceiling backed by a quoted grant). The verifier never creates/replaces the participant project or fabricates reference approval.

For just the configured spike:

```
python scripts/live_spike.py /outside-repo/participant-spike
```

Image generation, chained edit and SAM are the three capabilities. There is no critic requirement. Prior bundle versions are retained under `live-bundle.json.history/`. Completed jobs reuse their original paid results; uncertain outcomes await operator reconciliation. An explicitly offline workflow needs a new authorized live identity. Arbitrary per-pose fitting is refused; an oversized or non-native source needs the already reviewed fixed family calibration.

The live gate passes only for actual live origin, complete passing technical evidence and all three recorded specialist capabilities. Fake upstream tests remain simulated. No participant live result or artistic acceptance is claimed by the local test suite.


## Private demo operation recovery

The helpers below operate only on explicitly authorized private demo runs. They do not reconcile or weaken the operator-only production grants and receipts described above. Unknown parents remain unknown and their commitments remain retained.

### Durable generation and recovery

A private run config can enable `durable_provider_transport: "stream"`. Every new
paid request freezes its wire and commitment before dispatch, stores the SSE
transcript and acceptance ID, and retains its terminal response and cost receipt.
An interrupted accepted operation resumes by GET of that exact ID. Its POST is
never repeated. A per-operation file lock prevents concurrent dispatchers from
creating duplicates. A lost local cost receipt can be reconstructed from the
retained terminal result without generating again.

The provider can fail before returning an acceptance ID. That operation remains
unknown. A user-authorized private `provider_recovery_policy` supplies an explicit
`authorization`, `max_successors_per_parent` (bounded across the entire recovery
chain), and `max_recovery_microdollars` for the run. The default bounds are two
successors per chain and $1 of new recovery commitments. Recovery creates a new
operation, links its original request digest and authorization, and retains both
commitments. No original spend, receipt or unknown outcome is cleared. Exhausting
the bounded policy produces a recorded pending state, not unlimited paid retries.
Auth failures and accepted jobs awaiting results do not trigger fresh POSTs.
Three consecutive 404/410 retrievals mark an accepted result unavailable; a linked
recovery can then run under the same authorization and budget.

`provider_worker.py` watches explicitly registered active jobs. It skips historical
unknown experiments, already completed jobs, successor parents and operations
whose writer still holds the lock. It retrieves accepted results or executes a
bounded authorized successor. Its state remains private. This removes the need
for an agent terminal to remain open during provider processing.

`recover_provider_operation.py` provides explicit recovery of a retained operation.
`stage_recovered_character.py` verifies the receipt and assesses recovered artwork.
A received result clears the logical transport block even when intake rejects its
artwork; rejection is recorded and ordinary quality-driven generation can continue.
Transport recovery never bypasses isolation, likeness, body, item, or rendering
fidelity gates and never publishes a draft automatically.

### Local service lifetime

`manage_dev_services.py --private-root PATH --generation-root RUN_ROOT` installs
one macOS login launcher and a private start command. The supervised API, Vite and
provider worker restart after child exits. The launcher uses the existing Terminal
access context because direct launchd children can stall opening an external
workspace. It changes no privacy permissions. Logs live under
`~/Library/Logs/Framebound`; service state and singleton locks live in the private
root. Re-running the installer is idempotent. Provider commitments and acceptance
files survive both service and agent restarts.

`continue_character_demo.py` uses a durable per-run generation limit and a retained
working state. `refinement_worker.py` resumes explicitly configured runs after
transport recovery. A pending operation consumes its original frozen request
before any new generation is planned, even if prompt defaults have since changed.
Already-assessed results are merged without generating them twice. Restarting the
worker does not reset its consumed budget. Automatic preview publication uses the
existing gates and cannot publish failed visible-item, fidelity or body-profile
checks.

Transition evidence locks cover only the ledger merge, never a remote model call.
Independent frame repairs can proceed together without losing either assessment;
negative findings stay retained. Atomic state writes use separate temporary files
so simultaneous workers cannot overwrite each other's temporary output.

A local item edit can inherit a prior pristine-qualified rendering verdict only
outside its exact changed rectangle and only when those native pixels are
byte-identical. The edited crop receives its own original-reference review. A
changed pixel outside the rectangle or an unqualified source requires a full
rendering review. This prevents stochastic reassessment of an unchanged face from
blocking a hand repair while preserving all checks on the new artwork.
