# Muse execution and generation provenance

External agents submit optional typed attribution under `generation_metadata.provenance` through the existing `agent-run-submit`, `agent_run_submit`, HTTP submission and portable correction response. Old metadata remains unknown; provider/model names are never inferred from filenames or prose.

`RevisionProvenance` v1 records an external parent execution identity, the frozen named style board, and ordered generation events. Parent fields separate requested and observed model/version, Muse Code harness/version, session, requested/effective Contributor mode, and evidence hash. External parent claims cannot claim local provider observation. Parent changes append `parent_changed` events alongside immutable revisions without changing limits or old attribution.

Generation events retain requested/observed image models, provider job and request/response IDs, prompt SHA-256, ordered conditioning asset/hash/role bindings, explicit conditioning eligibility and basis, original output hashes, receipts, edit ancestry and ordered postprocessing hashes. Only original or explicitly cleared inputs can be recorded as supplied conditioning. Research boards remain analysis, not known-good motion sources or automatic conditioning authority.

Every referenced blob must exist and match its hash. Materialized assets must trace to original bytes through the recorded transformations. Locally observed attribution additionally requires a successful live job, its actual response receipt, matching output assets, models, prompt digest and ordered conditioning hashes. Simulated transport and external assertions cannot pass that gate. Output validation and human acceptance remain separate.

Use `framebound.v3.provenance.RevisionProvenance.model_json_schema()` for the complete input shape. The `TaskSpec.style_board` binding and optional `InputBinding.byte_sha256` are additive; missing values on older tasks are unknown. Effective Contributor mode and observed model/version stay unknown unless evidence supports them. The current orchestration session is Codex; a separately invoked Muse session is recorded as such rather than relabeling Codex as Muse.

Actual Muse generation remains pending until Muse Image is accessible. No independent human labels or completed pilot are claimed by this implementation.
