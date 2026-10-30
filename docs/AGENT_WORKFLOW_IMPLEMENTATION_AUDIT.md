# Agent animation workflow implementation audit

This audit tracks the original scope in `AGENT_ANIMATION_WORKFLOW_PLAN.md`.
Engineering tests are not substituted for independently reviewed generated-art
quality evidence. The workflow is implemented through the provisional broader
profile milestone; the full quality acceptance claim remains unproven until the
missing real-art evidence below is supplied and measured.

## Requirements and authoritative evidence

| Plan requirement | Implementation/evidence | Current conclusion |
|---|---|---|
| Immutable reference-free task intent, inputs, timing and policies | `v3/domain.py`, `v3/services/tasks.py`; `test_agent_tasks.py`; public CLI/MCP/HTTP creation, identity-only/prose-only tests | Implemented; no guide/reviewer event fabricated |
| Applicability/prerequisites, frozen required/advisory matrix, honest unsupported outcomes | `tasks._negotiate`, `v3/evaluate.py`, `v3/scene.py`; missing/ambiguous/occluded tests | Implemented for declared supported methods; arbitrary prose/anatomy/physics remain unsupported |
| New specification revisions with reasons; no same-ID weakening or budget reset | immutable task registration, explicit `loop.revise_task`, `test_agent_task_revision.py` | Implemented with old evidence retained, current next-task binding and version checks |
| External generation-input compilation and initial submission without per-phase approval | `tasks.compile_inputs`, `loop.submit`; public creation/HTTP→CLI tests | Implemented; external parent owns provider generation |
| Immutable revision lineage, changed/unchanged assets and actual generation metadata | explicit v3 revisions plus existing immutable asset/frame/registration types; replay/rollback tests | Implemented; unavailable metadata stays missing |
| Complete evaluation with localized useful defects, tool errors and missing measurements kept distinct | `evaluate`, `scene`, `correspondence`; defect localization/measurement tests | Implemented for the measured profiles, without artistic-completeness claims |
| Full-matrix re-evaluation, no-regression best retention, failed history, broader declared repair scope | `loop.submit`, exact grant-preservation checks; regression/oscillation/scope tests | Implemented; best selection and historical evidence are separate from latest submission |
| Persistent attempt/compute budgets, repeated outputs, oscillation, stale/concurrent submissions, process death | `loop`, `test_agent_loop.py`, `test_agent_task_revision.py`, provider recovery suites | Implemented; actual subprocess death and overlapping submissions tested |
| Durable shared feedback with exact task/revision/evaluation/assets/hashes, scope, preservation and available continuation operations | `_feedback`, interventions renderer; shared CLI/MCP/HTTP reads | Implemented; related scopes group without losing results/authority, and stopped runs return stop/state-fetch instructions |
| Saved markup and decisions, owner resolve/reopen, no automatic closure of subjective work | `interventions`, API and browser journey | Implemented; real reviewer boundary and exact bindings enforced |
| Copy/download/JSON handoff and stale rebase | `Handoff.tsx`, shared renderer, explicit rebase; browser clipboard/fallback tests | Implemented after save, with stale binding checks |
| Parent agent without project/MCP access can use portable task/pixels and return a bound correction | `portable_handoff`, CLI/MCP export/import, HTTP zip download; `test_portable_handoff.py`; real browser→disconnected-directory→CLI journey | Implemented; no credential/authority token in the package |
| Separate lifecycle, technical coverage, creative judgment, output eligibility and training labels | durable run/evaluation/completion/events, explicit parent judgment and reviewer decisions; eligibility/export negatives | Implemented; technical/agent evidence never becomes human approval |
| Run-based Interventions and Timeline grouped by project, no packet prerequisite or queue for clean unreviewed output | `services/desk.py`, `AgentDesk.tsx`, desk and browser tests | Implemented; events open exact revisions and identify source/current/best |
| Candidate-first film, optional real comparison, aligned separate checks, first chronological error centering, stable single-stage playback and responsive controls | reused Film/camera/clock, `AgentWorkspace.tsx`, real browser journey and frontend unit tests | Implemented and browser-tested; legacy reviewed-guide journey retained |
| Continuous trajectory records; manual export preview/policy/destination/validation | v3 export selection over existing publisher, `AgentExport.tsx`, browser export journey | Implemented; no automatic publication on run completion |
| Human positives, opt-in automatic view, research/withheld, no inferred preferences | shared snapshot dispatch, explicit human-comparison records, versioned consumers; label-tampering/current-decision tests | Implemented with separate files, source labels and exact decisions |
| Optional-input/source closure, pixels/evidence after moving, rights/origin/ancestry and family-safe splits | `agent_snapshot`, `agent_validate`, existing COCO/publication; moved/rights/split/recovery tests | Implemented; required missing pixels are withheld, never invented |
| Existing standard formats and consumers extended with explicit version/reader capability | shared `build_snapshot`/`validate_snapshot`, COCO and imagefolder layouts; explicit v3 example/preference readers | Implemented; old unsupported readers reject v3 semantics |
| Exact known-good source designation, timing/key preservation and unequal-count authored-time interpolation | `correspondence`, task/source validation and source tests; mapped browser playback | Implemented; source intervals are not mislabeled as same-frame references or proof of fluidity |
| Reviewed-guide/native-sprite path, reviewer boundaries, provider controls and strict old positives preserved | original v2 services, public creation/provider/export suites and legacy browser journey | Retained; full local verifier is the broad regression gate |
| Additive migrations/backups/dry runs, old evidence/labels not rewritten | separate v3 tables, schema backups, read-only task migration report, old-record serialization/snapshot tests | Implemented; older task payloads/digests are preserved through HTTP as well as services |
| First reference-free defect suite with legitimate pose/hold/occlusion counterexamples | `test_agent_loop.py`; disappearance/duplication, region flicker, discontinuity, declared contact, moving repeat and loop repairs | Engineering behavior demonstrated with procedural fixtures |
| Next scene class: camera/scale, occlusion, multiple landmarks/subjects and action/event correctness | provisional `tracked-scene-v1`; checked-in `fixtures/quality/tracked-scene-v1`; `test_tracked_scene.py` | Specific declared 2D landmark methods demonstrated; broad reliability is not claimed |
| Quantified false alarms, misses, localization and repair regressions, separate from completion | `animation-quality-benchmark`, versioned corpus/schema and checked-in fixture labels | Implemented; six procedural checks localized correctly with no misses/false alarms in that small suite |
| Actual image-generated animations and independently reviewed held-out defect labels before reliable complex-animation claims | No such reviewed corpus is present in the repository; procedural art, imported claims and test reviewers are not substitutes | **Missing evidence; provisional profile cannot be promoted or the full quality goal claimed complete** |

Module paths in the table are relative to `framebound/`; test filenames live
under `tests/`, frontend components under `web/src/`, and corpus artifacts under
`fixtures/`. Full operation arguments and explicit method limitations are in
[AGENT_LOOP.md](AGENT_LOOP.md). Legacy live provider/participant evidence remains
separate in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Verification gate

The reproducible broad gate is:

```sh
PYTHONPATH="$PWD" sh scripts/verify-local
```

It runs unittest, the full pytest suite, offline demos, stored verification,
portable export round-trip, frontend type/type-freshness/unit/build checks and
both the agent and reviewed-guide browser journeys. Live provider work remains
explicitly opt-in; skipping it is not counted as a successful participant live
observation. The full verification run passed: 421 pytest cases passed and 4 were skipped;
the unittest stage, both offline demos, stored verification, export round-trip,
frontend type/type-freshness/unit/build checks and both real browser journeys
passed. The legacy browser guard recorded zero external socket attempts. Live
specialist observation was skipped in offline mode and remains unproven. The
focused old-task HTTP serialization regression test also passes.

The standard `datasets` imagefolder loader has separately decoded a moved
reference-free automatic/research snapshot with native pixels. That check used
an isolated interpreter with working `lzma`; the checkout's default interpreter
lacks that native module. PIL-only fallback is not described as standard-loader
proof.

## Remaining acceptance evidence

Supply a corpus directory with actual generated native animation frames,
generation/provenance records and independently reviewed defect labels. Use the
versioned quality-benchmark schema to retain those actual label sources, known
requirements, counterexamples, localization and a held-out split. Compare repair
outcomes and new regressions independently. Do not infer reviewer labels from an
agent's success assertion, a simulated provider response or the procedural suite.

Until that evidence is measured, structural completion means structural validity,
declared-region/scene completion means those particular measured constraints, and
creative completion remains the named agent or human judgment. The original goal
is not marked achieved merely because the implementation tests pass.
