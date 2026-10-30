"""External-agent loop: atomic submissions, immutable evidence, bounded durable progress."""
from pathlib import Path
import json

from ...v2 import domain as D, storage as S
from ...v2.media.canonical import load_native_image
from ...v2.services.errors import InvalidInput
from .. import evaluate as E
from . import tasks

TABLES = ('agent_runs', 'agent_clip_revisions', 'agent_evaluations', 'agent_feedback', 'agent_completions', 'agent_run_events', 'agent_interventions')


def connect(project):
    con = tasks._connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            existing = {r['name'] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if any(table not in existing for table in TABLES):
                tasks.backup_database(project, 'before-agent-interventions-v3.sqlite3'
                                      if 'agent_runs' in existing else 'before-agent-loop-v3.sqlite3')
            for table in TABLES:
                con.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    except Exception:
        con.close()
        raise
    return con


def get_in(con, table, rid):
    row = con.execute(f'SELECT data FROM {table} WHERE id=?', (rid,)).fetchone()
    if row is None:
        raise InvalidInput(f'unknown {table}/{rid}')
    return json.loads(row['data'])


def insert(con, table, record):
    con.execute(f'INSERT INTO {table}(id,data) VALUES(?,?)', (record['id'], json.dumps(record, sort_keys=True)))


def start(project, task_id, run_id):
    con = connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            task = tasks._get(con, task_id)
            existing = con.execute('SELECT data FROM agent_runs WHERE id=?', (run_id,)).fetchone()
            if existing:
                run = json.loads(existing['data'])
                if run['task_id'] != task_id:
                    raise S.ConflictError('run ID is bound to a different task')
                return run
            # One durable budget for the whole animation family, including specification revisions.
            family = [json.loads(r['data']) for r in con.execute('SELECT data FROM agent_runs')]
            if any(r['project_id'] == task.spec.project_id and r['animation_id'] == task.spec.animation_id for r in family):
                raise S.ConflictError('animation already has a run; resuming or revising must retain its budget')
            run = dict(schema_version='3.0', id=run_id, task_id=task_id, spec_sha256=task.spec_sha256,
                       project_id=task.spec.project_id, animation_id=task.spec.animation_id,
                       lifecycle='awaiting_agent', current_revision_id=None, best_revision_id=None,
                       submission_ids=[], fingerprints=[], no_progress_count=0,
                       limits=task.spec.limits.model_dump(), created_at=D.utcnow(), version=1,
                       stop_reason=None, creative_status='unreviewed')
            insert(con, 'agent_runs', run)
            insert(con, 'agent_run_events', dict(id=f'{run_id}:started', run_id=run_id,
                project_id=run['project_id'], animation_id=run['animation_id'], task_id=task_id,
                event='started', revision_id=None, source='external_agent', created_at=D.utcnow(), ordinal=1))
        return run
    finally:
        con.close()


def get(project, run_id):
    con = connect(project)
    try:
        run = get_in(con, 'agent_runs', run_id)
        run['remaining_submissions'] = max(0, run['limits']['max_submissions'] - len(run['submission_ids']))
        run['feedback'] = (get_in(con, 'agent_feedback', run.get('feedback_id', f"feedback:{run['current_revision_id']}"))
                           if run['current_revision_id'] else None)
        return run
    finally:
        con.close()


def _update(con, run):
    run['version'] += 1
    con.execute('UPDATE agent_runs SET data=? WHERE id=?', (json.dumps(run, sort_keys=True), run['id']))


def _score(evaluation):
    rank = {'pass': 0, 'not_applicable': 0, 'fail': 1, 'unmeasured': 2, 'error': 3}
    return sum(rank[r['outcome']] for r in evaluation['results'] if r['required'])


def submit(project, run_id, revision_id, frame_asset_ids, *, parent_revision_id=None,
           feedback_id=None, presented_holds=None, generation_metadata=None):
    if not isinstance(revision_id, str) or not 1 <= len(revision_id) <= 90:
        raise InvalidInput('revision ID must contain 1–90 characters')
    if presented_holds is not None:
        D.Timing(holds=presented_holds)
    con = connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run = get_in(con, 'agent_runs', run_id)
            task = tasks._get(con, run['task_id'])
            spec = task.spec
            holds = presented_holds if presented_holds is not None else spec.timing.holds
            request = dict(run_id=run_id, task_id=task.id, frame_asset_ids=frame_asset_ids,
                           parent_revision_id=parent_revision_id, feedback_id=feedback_id,
                           presented_holds=holds, generation_metadata=generation_metadata)
            request_digest = E.digest(request)
            previous = con.execute('SELECT data FROM agent_clip_revisions WHERE id=?', (revision_id,)).fetchone()
            if previous:
                rev = json.loads(previous['data'])
                if rev['request_digest'] != request_digest:
                    raise S.ConflictError('revision ID is already bound to a different submission')
                return get_in(con, 'agent_feedback', f'feedback:{revision_id}')
            if run['lifecycle'] in {'completed', 'cancelled', 'blocked'}:
                raise InvalidInput(f"run is {run['lifecycle']}: {run['stop_reason']}")
            if len(run['submission_ids']) >= run['limits']['max_submissions']:
                raise InvalidInput('persistent submission budget exhausted')
            if parent_revision_id != run['current_revision_id']:
                raise S.StaleRevisionError('submission parent differs from current revision; fetch current feedback and explicitly rebase')
            if parent_revision_id and feedback_id != run.get('feedback_id', f'feedback:{parent_revision_id}'):
                raise S.StaleRevisionError('child submission must bind current saved feedback')
            if len(frame_asset_ids) != len(spec.timing.holds):
                raise InvalidInput('frame count must equal the frozen authored hold count')
            from . import interventions as I
            if parent_revision_id and spec.repair_scope == 'declared_regions' and not any(m['authorize_edit_scope'] for m in I.open_in(con, run_id)):
                raise InvalidInput('declared-region edit permissions need a saved intervention grant; full-clip permission cannot be inferred')
            if spec.canvas.width * spec.canvas.height * len(frame_asset_ids) > run['limits'].get('max_evaluation_pixels', 16777216):
                raise InvalidInput('frozen evaluation pixel budget exceeded; negotiate a new task before allocating frames')
            images, manifest, fids = [], [], []
            for slot, aid in enumerate(frame_asset_ids):
                try:
                    asset, _ = S.get(con, 'assets', aid)
                except KeyError as exc:
                    raise InvalidInput(f'missing imported asset {aid}') from exc
                blob = S.blob_path(project, asset['byte_sha256'])
                image = None
                if blob.is_file() and S.sha256_bytes(blob.read_bytes()) == asset['byte_sha256']:
                    try:
                        image = load_native_image(blob)
                    except (OSError, ValueError):
                        pass
                images.append(image)
                manifest.append(dict(id=aid, byte_sha256=asset['byte_sha256'], pixel_sha256=asset.get('pixel_sha256'),
                                     blob_path=str(blob.relative_to(Path(project))), http_path=f'/api/asset/{aid}'))
                fid = f'{revision_id}:frame:{slot}'
                fi = D.FrameInstance(id=fid, clip_revision_id=revision_id, slot=slot, asset_id=aid,
                                     phase=f'task-slot-{slot}', hold_ticks=spec.timing.holds[slot],
                                     registration_id=f'{fid}:registration', source_drawing_id=aid,
                                     derivation_recipe='external-agent:submission')
                S.stage(con, fi)
                S.stage(con, D.Registration(id=fi.registration_id, frame_instance_id=fid,
                                            pixels_baked=True, verified_by='external-import'))
                fids.append(fid)
            results, evidence, evidence_digest = E.evaluate(spec, images, manifest, holds)
            preservation = I.preservation_in(con, project, run, images, spec)
            results.extend(preservation)
            for result in results:
                result['required'] = True
            required_by_check = {check: any(r.required for r in task.requirements if r.check == check)
                                 for check in {r.check for r in task.requirements}}
            for result in results:
                result['required'] = (True if result['family'] in {'media', 'timing', 'edit_preservation'}
                                      else required_by_check.get(result['family'], True))
            for requirement in task.requirements:
                if requirement.applicability != 'supported':
                    results.append(dict(id=f'gap:{requirement.id}', family=requirement.check,
                                        required=requirement.required, slots=list(range(len(images))),
                                        tick_range=[0, spec.timing.total_ticks()], outcome='unmeasured',
                                        observed=None, expected=None, roi=None, source='capability_registry',
                                        evidence_method='task-negotiator-v2', confidence=None,
                                        reason=requirement.limitation))
            evidence['results'] = results
            evidence_digest = E.digest(evidence)
            evaluation = dict(schema_version='3.0', id=f'evaluation:{revision_id}', revision_id=revision_id,
                              task_id=task.id, results=results, evidence=evidence, evidence_digest=evidence_digest,
                              evaluator=E.VERSION, created_at=D.utcnow())
            required = [r for r in results if r['required']]
            evaluation['technical_status'] = ('error' if any(r['outcome'] == 'error' for r in required) else
                'fail' if any(r['outcome'] == 'fail' for r in required) else
                'incomplete' if any(r['outcome'] == 'unmeasured' for r in required) else 'pass')
            evaluation['coverage'] = 'complete' if all(r['outcome'] not in {'error', 'unmeasured'} for r in required) else 'partial'
            revision = dict(schema_version='3.0', id=revision_id, frame_instance_ids=fids,
                            frame_asset_ids=frame_asset_ids, task_id=task.id, run_id=run_id,
                            parent_revision_id=parent_revision_id, targeted_feedback_id=feedback_id,
                            generation_metadata=generation_metadata, request_digest=request_digest,
                            changed_slots=list(range(len(images))), created_at=D.utcnow())
            if parent_revision_id:
                parent = get_in(con, 'agent_clip_revisions', parent_revision_id)
                revision['changed_slots'] = [i for i, (a, b) in enumerate(zip(parent['frame_asset_ids'], frame_asset_ids)) if a != b]
            insert(con, 'agent_clip_revisions', revision)
            insert(con, 'agent_evaluations', evaluation)
            fingerprint = E.digest([a['pixel_sha256'] or a['byte_sha256'] for a in manifest])
            run['no_progress_count'] = run['no_progress_count'] + 1 if fingerprint in run['fingerprints'] else 0
            run['fingerprints'].append(fingerprint)
            run['submission_ids'].append(revision_id)
            run['current_revision_id'] = revision_id
            run['creative_status'] = 'unreviewed'
            regression_ids = []
            if run['best_revision_id']:
                best = get_in(con, 'agent_evaluations', f"evaluation:{run['best_revision_id']}")
                old_pass = {r['id'] for r in best['results'] if r['required'] and r['outcome'] == 'pass'}
                regression_ids = [r['id'] for r in results if r['id'] in old_pass and r['outcome'] not in {'pass', 'not_applicable'}]
            else:
                best = None
            if best is None or (_score(evaluation) < _score(best) and not regression_ids):
                run['best_revision_id'] = revision_id
            passed = evaluation['technical_status'] == 'pass' and evaluation['coverage'] == 'complete'
            I.after_submission_in(con, run, revision_id, all(r['outcome']=='pass' for r in preservation))
            if passed and I.open_in(con, run_id):
                run['lifecycle'], run['stop_reason'] = 'awaiting_decision', 'Technical checks passed; saved human corrections require explicit owner resolution.'
            elif passed and spec.intervention != 'explicit_review' and spec.completion.id == 'technical-unreviewed-v1':
                run['lifecycle'], run['stop_reason'] = 'completed', 'Declared requirements met under technical-unreviewed-v1.'
            elif passed:
                run['lifecycle'], run['stop_reason'] = 'awaiting_decision', 'Exact-revision human decision required by the task policy.'
            elif run['no_progress_count'] >= run['limits']['max_unchanged']:
                run['lifecycle'], run['stop_reason'] = 'blocked', 'Repeated output or oscillation; persistent no-progress limit reached.'
            elif len(run['submission_ids']) >= run['limits']['max_submissions']:
                run['lifecycle'], run['stop_reason'] = 'blocked', 'Persistent submission budget exhausted.'
            elif any(r['required'] and r['outcome'] in {'unmeasured', 'error'} for r in results):
                run['lifecycle'], run['stop_reason'] = 'awaiting_input', 'Obtain the missing evidence or recover the failed tool before claiming success.'
            else:
                run['lifecycle'], run['stop_reason'] = 'awaiting_agent', None
            feedback = _feedback(run, task, revision, evaluation, regression_ids)
            I.augment_in(con, feedback, run)
            insert(con, 'agent_feedback', feedback)
            run['feedback_id'] = feedback['id']
            if run['lifecycle'] == 'completed':
                insert(con, 'agent_completions', dict(id=f'completion:{revision_id}', schema_version='3.0',
                    run_id=run_id, task_id=task.id, policy=spec.completion.model_dump(),
                    revision_id=revision_id, evaluation_id=evaluation['id'], evidence_digest=evidence_digest,
                    creative_status='unreviewed', output_eligibility='automatic-technical',
                    quality_scope='declared-region constraints' if spec.profile == 'fixed-subject-v1' else 'structural only; animation quality not verified'))
            insert(con, 'agent_run_events', dict(id=f'{run_id}:submission:{revision_id}', run_id=run_id,
                project_id=run['project_id'], animation_id=run['animation_id'], task_id=task.id,
                event='completed' if run['lifecycle']=='completed' else 'evaluated', revision_id=revision_id,
                evaluation_id=evaluation['id'], feedback_id=feedback['id'],
                source='framework', created_at=D.utcnow(), ordinal=run['version']+1))
            _update(con, run)
            return feedback
    finally:
        con.close()


def _feedback(run, task, revision, evaluation, regressions):
    spec = task.spec
    targets = []
    for result in evaluation['results']:
        if result['outcome'] in {'pass', 'not_applicable'}:
            continue
        targets.append(dict(id=f"issue:{run['id']}:{result['id']}", priority=0 if result['required'] else 2,
            check_id=result['id'], outcome=result['outcome'], observation_source=result['source'],
            slots=result['slots'], frame_ids=[revision['frame_instance_ids'][s] for s in result['slots']],
            display_numbers=[s + 1 for s in result['slots']], tick_range=result['tick_range'],
            coordinate_space='native_px', roi=result['roi'], observed=result['observed'], expected=result['expected'],
            evidence_assets=[evaluation['evidence']['assets'][s] for s in result['slots']],
            desired_outcome=result['reason'], uncertainty=result['confidence'],
            suggested_operation='recover_media_or_evidence' if result['outcome'] in {'error', 'unmeasured'} else 'regenerate_within_task_scope'))
    return dict(schema_version='3.0', bundle_version=1, id=f"feedback:{revision['id']}",
        project_id=task.spec.project_id, animation_id=task.spec.animation_id, run_id=run['id'], task_id=task.id,
        spec_sha256=task.spec_sha256, baseline_revision_id=revision['id'], evaluation_id=evaluation['id'],
        evidence_digest=evaluation['evidence_digest'], disposition='complete' if run['lifecycle'] == 'completed' else
        'blocked' if run['lifecycle'] == 'blocked' else 'awaiting_decision' if run['lifecycle'] == 'awaiting_decision' else 'awaiting_input' if run['lifecycle'] == 'awaiting_input' else 'continue',
        reason=run['stop_reason'], technical_status=evaluation['technical_status'], coverage=evaluation['coverage'],
        creative_status=run['creative_status'], best_revision_id=run['best_revision_id'], current_revision_id=revision['id'],
        targets=targets, regressions=regressions, preserve=spec.preserve,
        allowed_changes=spec.allowed_changes, repair_scope=spec.repair_scope,
        timing=spec.timing.model_dump(), remaining_submissions=run['limits']['max_submissions']-len(run['submission_ids']),
        verification='Re-evaluate the complete declared matrix, including neighbours and loop boundaries; frozen bounds cannot be weakened.',
        continuation=dict(operation='agent_run_submit', arguments=dict(run_id=run['id'], parent_revision_id=revision['id'],
            feedback_id=f"feedback:{revision['id']}", revision_id='<new immutable ID>', frame_asset_ids='<complete ordered imported asset IDs>')))


def eligibility(project, run_id):
    """Current output usability is separate from historical evaluation and human acceptance."""
    con = connect(project)
    try:
        run = get_in(con, 'agent_runs', run_id)
        rid = run['best_revision_id']
        reasons = []
        if not rid:
            return dict(eligible=False, reasons=['No evaluated revision.'], creative_status=run['creative_status'])
        evaluation = get_in(con, 'agent_evaluations', f'evaluation:{rid}')
        for asset in evaluation['evidence']['assets']:
            path = S.blob_path(project, asset['byte_sha256'])
            if not path.is_file() or S.sha256_bytes(path.read_bytes()) != asset['byte_sha256']:
                reasons.append(f"missing_or_changed_asset:{asset['id']}")
        if evaluation['technical_status'] != 'pass' or evaluation['coverage'] != 'complete':
            reasons.append('Required technical matrix is not complete and passing.')
        spec = tasks._get(con, run['task_id']).spec
        from . import interventions as I
        if spec.completion.id == 'human-reviewed-v1' and not I.approved_in(con, run_id, rid, evaluation['id']):
            reasons.append('Human-reviewed policy requires an exact saved reviewer decision.')
        if I.open_in(con, run_id):
            reasons.append('Saved human corrections remain unresolved.')
        if run['lifecycle'] != 'completed':
            reasons.append(f"Run lifecycle is {run['lifecycle']}.")
        return dict(schema_version='3.0', eligible=not reasons, policy=spec.completion.id,
                    revision_id=rid, evaluation_id=evaluation['id'], evidence_digest=evaluation['evidence_digest'],
                    creative_status=run['creative_status'], reasons=reasons,
                    quality_scope='declared regions and events only' if spec.profile=='fixed-subject-v1' else 'structural only; animation quality not verified')
    finally:
        con.close()


def cancel(project, run_id, reason):
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidInput('cancellation requires an explicit reason')
    con = connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run = get_in(con, 'agent_runs', run_id)
            if run['lifecycle'] == 'cancelled':
                return run
            if run['lifecycle'] == 'completed':
                raise InvalidInput('a completed run cannot be cancelled retroactively')
            run['lifecycle'], run['stop_reason'] = 'cancelled', reason
            insert(con, 'agent_run_events', dict(id=f'{run_id}:cancelled', run_id=run_id,
                project_id=run['project_id'], animation_id=run['animation_id'], task_id=run['task_id'],
                event='cancelled', revision_id=run['current_revision_id'], source='external_agent',
                reason=reason, created_at=D.utcnow(), ordinal=run['version']+1))
            _update(con, run)
        return run
    finally:
        con.close()


def revision_get(project, revision_id):
    con = connect(project)
    try:
        return dict(revision=get_in(con, 'agent_clip_revisions', revision_id),
                    evaluation=get_in(con, 'agent_evaluations', f'evaluation:{revision_id}'),
                    feedback=get_in(con, 'agent_feedback', f'feedback:{revision_id}'))
    finally:
        con.close()
