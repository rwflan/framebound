# Portable snapshots and training consumers

`export` captures one immutable source state. An identical request replays that historical state after checking completion, file hashes and portable semantics. Use a new snapshot name and destination to export current decisions. A matching manifest alone does not establish a valid snapshot.

Publication uses an owned sibling staging directory and hidden publication journal. The journal pins SQLite through a real backup, records staging/manifest identity, and recovers before or after the single directory rename and DB recording. Incomplete staging is preserved on interruption. Unrelated output is refused. No directory is emptied and repopulated. The private frozen DB stays under the source project’s backups directory; the sibling journal stores publication identity. Publish only the completed snapshot directory.

The completed directory contains only selected media, necessary revision parents/comparisons, referenced controls, ancestry, measurements, operations, review records and linked provider artifacts. An unrelated job or provider note is absent. All read helpers consume the frozen connection. Derived provenance and family grouping follow parent edges; default positive rows reject disallowed ancestor rights, simulated output, unresolved derivations and procedural ancestry unless explicitly opted into the labeled research policy.

Move the completed directory anywhere and run:

```
framebound dataset-validate --snapshot /path/to/moved-snapshot
```

The validator needs no source DB. It decodes COCO masks against actual image pixels, materializes Hugging Face ImageFolder positives, verifies typed asset/operation/control/job relationships and rechecks positive policy from portable ancestry and current captured review decisions. An export archive is not a signed attestation against an attacker rewriting its entire history; it is an independently checkable captured dataset.

COCO and ImageFolder are standard views. `temporal.jsonl`, repair closure and `framebound-preference-v1` are project-specific contracts. No universal trainer compatibility is claimed.

```python
from framebound.v2.exports.dpo_adapter import decoded_batch
batch = decoded_batch('/path/to/moved-snapshot', batch_size=1)
assert batch['format'] == 'framebound-preference-v1'
chosen_sequence = batch['chosen'][0]       # list of uint8 [height,width,4] arrays
rejected_sequence = batch['rejected'][0]   # independently decoded rejected art
contract = batch['conditioning'][0]['contract']
controls = batch['conditioning'][0]['images']  # identity/style/phase/support arrays
```

The adapter accepts explicit human comparison packets, validates image hashes, and materializes actual RGBA pixels. Variable sequence lengths remain explicit lists. The consuming trainer owns padding, loss masks, tensor placement and optimization. Empty preferences raise rather than invent a pair. These routines do not train a model or convert technical ranking into human preference.

Behavioral receipts are in `tests/test_snapshot_publication.py`: real process death at pinned/staged/published/recorded barriers, post-pin review changes, replay corruption refusal, unrelated-note absence, moved provenance tamper and a nonempty decoded training batch.
