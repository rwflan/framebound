# Local Muse corpus workflow

Corpus media, reference identities, source URLs, reference boards, generation prompts, receipts, model labels, measurements and snapshots belong in an external local directory. None belong in the repository. The framework accepts explicit manifest paths; it does not bundle or download a corpus.

Use Muse Image for artwork generation and editing, with an external Muse Spark session for generation orchestration and automated annotation. Record requested versus observed parent/image models and versions, harness/session identity, Contributor setting, actual request/response evidence and immutable hashes. Unknown attribution stays unknown. Research access does not confer conditioning or training rights.

Freeze reference/identity families and development versus held-out assignments before generation. Calibrate each local style board, then create locomotion, acting, interaction and effects clips. Preserve original outputs and failed requests. Enforce finite call, cost, time and pixel ceilings and at most two variants per base. Unknown provider outcomes require reconciliation before another dispatch.

Import sheets using `scripts/import_muse_corpus.py --manifest /external/local/base_manifest.json --project /external/local/project --review /external/local/review.json`. The importer verifies Muse receipts and source hashes, records deterministic crops/resampling and preserves edit-parent frames outside the declared repair slots. Corrections retain the original family run and remaining budget.

Automated model labels and corrections are the default. Human oversight is minimal and optional, never a generation or training gate. Model judgments retain confidence, disagreements, legitimate animation counterexamples and unmeasured coverage; they do not become human ground truth. Current structural measurements do not establish arbitrary anatomy, acting or painterly quality.

Portable snapshots retain revision provenance, reference/output ancestry and reader capabilities. `load_model_annotations` and `load_model_corrections` expose model supervision and exact parent/candidate frames without requiring human acceptance. Benchmark reports show per-family misses, false alarms, localization, correction regressions and unmeasured checks. Missing labels and unsupported checks remain explicit. This workflow prepares measured learning data; it does not claim to train model weights automatically.
