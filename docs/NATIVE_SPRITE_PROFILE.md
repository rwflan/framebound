# Native sprite profile v1

`CompiledAnimationPlan.profile = native_sprite_v1` is a fixed-canvas raster workflow. It compiles an immutable contract and the exact active human approval of that contract's guide. It does not infer character anatomy or intended action from arbitrary prose.

## Inputs and authority

Create the project and character through `project-create` and `character-propose`, or the matching MCP tools. Import distinct identity and style assets and independent PNG phase references. Propose one guide entry per named phase. Repeated slots may reuse a phase; ambiguous duplicate guide entries are refused. All references use the character's native canvas.

The guide declares an approved repair policy and optional editable/protected masks per phase. Selected mask pixels have normalized luminance above 127; RGB hidden behind zero alpha is normalized before use. Protected support wins over editable support. With no editable mask, the entire frame is protected relative to the independent guide baseline. Masks, source calibration and policy are displayed with the art in References and included in approval hashes. An automatic contract must require `repair_protection`; it can narrow the guide's policy, never widen it.

The contract declares canvas, phase schedule, frame holds, applicable measurements, their thresholds and any required world/contact/feature/transition annotations. `animation-compile` returns the frozen per-slot controls and required check matrix. Missing references, changed bytes, revoked approval, non-native art or unavailable measurements refuse execution or produce explicit incomplete coverage.

## Measurement and repair

| Measurement | Comparison and threshold | Temporal scope | Automatic response |
|---|---|---|---|
| Native registration | Exact dimensions and native materialization; optional alpha-centroid drift bound `max_anchor_drift_px` | Every applicable frame | Integer translation only when whitelisted; approved composed displacement and clipping bounds apply |
| Repair protection | Literal RGBA difference from the independent guide outside effective editable support, including protected pixels; required count is zero | Every slot in the compiled plan | Whitelisted protected restoration; measured violation count must strictly fall |
| Silhouette area/width/height | Candidate versus independent same-phase alpha silhouette; explicit `max_fraction` | Per frame | Scoped redraw when authorized; otherwise a measured blocker |
| Palette | Candidate/reference color distribution with declared `max_drift` | Per frame | Scoped redraw when authorized |
| Phase correspondence | Declared raster region/grid against independent phase references and explicit alternatives | Declared slots | Scoped redraw when authorized |
| Cadence | Presented holds equal the frozen timing contract | Full clip | Block on mismatch |
| Contacts, sliding, visible spans, local pulse, loop seams and transitions | Check-specific supplied annotations, regions and numeric tolerances | Declared slots, pairs or world ticks | Measure and block unsupported automatic correction |

Only declared checks execute. A passing centroid or palette check does not imply correct anatomy. An explicitly unmeasured or partial required check blocks readiness. Technical completion requires the whole required matrix to pass with complete coverage. Improved intermediate revisions remain inspectable internal progress. The engine never creates artistic approval.

Every attempt consumes the persisted reference-approval/phase grant. Renaming a contract or using another request key cannot replenish it. Operator output records its actual parents, source job, controls, scope and origin. Local attempts and provider dispatches have separate ceilings. The external orchestrator sends a queued scoped provider job through the normal controller and resumes `animation-step`; the framework applies the native composite and performs the full independent recheck.

## Limits and reproducible examples

Translation does not rotate, scale individual poses, invent anatomy or solve arbitrary retargeting. Protected restoration copies only the guide-controlled support. Redraw can propose new pixels only within reviewed editable support. Occluded features need supplied coverage/annotations; ambiguous visual meaning is not filled in by another model.

`source-calibrate` supports one reviewed source size, crop and uniform nearest-neighbour scale for the family, retaining raw ancestry. It does not estimate a new fit for each pose. Nonzero legacy registration transforms require native rematerialization and new evaluation. Native playback, checks and export consume the same canonical pixels.

`web/e2e/setup.py` creates two visibly different procedural character families through actual MCP tools, while `web/e2e/journey.mjs` supplies labeled test reviewer approval through the desk. `tests/test_automatic_execution.py` also executes translation/restoration against literal expected pixels and restarts workers at four barriers. `tests/test_scoped_specialist_repair.py` exercises source/mask transmission and exact scoped composition using a labeled simulated upstream. These are reusable profile examples rather than participant art or live-provider claims.
