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
