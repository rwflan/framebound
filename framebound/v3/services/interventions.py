"""Saved human corrections and revision-bound handoffs; reviewer authority is explicit."""
import json
import uuid

import numpy as np
from pydantic import Field, StrictBool, model_validator

from ...v2 import domain as D, storage as S
from ...v2.services.authz import require_reviewer
from ...v2.services.errors import InvalidInput
from ...v2.media.canonical import load_native_image
from . import loop, tasks


class MarkRequest(D.Strict):
    id: str = Field(min_length=1, max_length=60)
    revision_id: str = Field(min_length=1, max_length=90)
    evaluation_id: str = Field(min_length=1, max_length=128)
    desired_outcome: str = Field(min_length=1, max_length=1000)
    tick_range: tuple[D.StrictInt, D.StrictInt]
    roi: D.Roi | None = None
    authorize_edit_scope: StrictBool = False

    @model_validator(mode='after')
    def valid_range(self):
        if not 0 <= self.tick_range[0] < self.tick_range[1]:
            raise ValueError('tick range must be nonempty and half-open')
        return self


class ResolveRequest(D.Strict):
    expected_version: D.StrictInt = Field(ge=1)
    revision_id: str = Field(min_length=1, max_length=90)
    evaluation_id: str = Field(min_length=1, max_length=128)
    note: str = Field(default='', max_length=2000)


class DecisionRequest(D.Strict):
    id: str = Field(min_length=1, max_length=60)
    revision_id: str = Field(min_length=1, max_length=90)
    evaluation_id: str = Field(min_length=1, max_length=128)
    action: str = Field(pattern='^(approve|reject|needs_changes)$')
    comparison_revision_id: str | None = None
    comparison_evaluation_id: str | None = None
    note: str = Field(default='', max_length=1000)


    @model_validator(mode='after')
    def valid_preference(self):
        if bool(self.comparison_revision_id)!=bool(self.comparison_evaluation_id):
            raise ValueError('explicit comparison requires both revision and evaluation identities')
        if self.comparison_revision_id and (self.action!='approve' or self.comparison_revision_id==self.revision_id):
            raise ValueError('preference must explicitly approve one revision over a different compared revision')
        return self


def open_in(con, run_id):
    return [json.loads(row['data']) for row in con.execute('SELECT data FROM agent_interventions')
            if json.loads(row['data'])['run_id'] == run_id
            and json.loads(row['data'])['correction']['status'] not in {'resolved', 'cancelled'}]


def _bound(con, run, revision_id, evaluation_id):
    if revision_id != run['current_revision_id']:
        raise S.StaleRevisionError('inspected revision is historical; fetch current state before saving this action')
    revision = loop.get_in(con, 'agent_clip_revisions', revision_id)
    if revision['task_id']!=run['task_id']:
        raise S.StaleRevisionError('run task changed; submit a new-task candidate before saving a markup or decision')
    evaluation = loop.get_in(con, 'agent_evaluations', evaluation_id)
    if revision['run_id'] != run['id'] or evaluation['revision_id'] != revision_id:
        raise S.StaleRevisionError('evaluation and revision bindings differ')
    return revision, evaluation


def _event_in(con, run, actor, action, revision_id, evaluation_id, *, note='', intervention_id=None, event_id=None):
    event_id = event_id or f'human:{uuid.uuid4().hex}'
    event = dict(schema_version='3.0', id=event_id, run_id=run['id'], task_id=run['task_id'],
                 project_id=run['project_id'], animation_id=run['animation_id'],
                 revision_id=revision_id, evaluation_id=evaluation_id, event=action,
                 source='human' if actor.type == 'reviewer' else 'external_agent',
                 actor_id=actor.id, note=note, intervention_id=intervention_id,
                 created_at=D.utcnow(), ordinal=run['version']+1)
    loop.insert(con, 'agent_run_events', event)
    return event


def augment_in(con, bundle, run=None):
    """Same durable object feeds automatic correction and human handoff rendering."""
    run = run or loop.get_in(con, 'agent_runs', bundle['run_id'])
    revision = loop.get_in(con, 'agent_clip_revisions', bundle['baseline_revision_id'])
    evaluation = loop.get_in(con, 'agent_evaluations', bundle['evaluation_id'])
    for mark in open_in(con, bundle['run_id']):
        slots = mark['slots']
        bundle['targets'].append(dict(id=mark['id'], check_id='subjective_correction',
            priority=0, outcome='unresolved', observation_source='human', slots=slots,
            frame_ids=[revision['frame_instance_ids'][i] for i in slots], display_numbers=[i+1 for i in slots],
            tick_range=mark['tick_range'], coordinate_space='native_px', roi=mark['roi'],
            observed=None, expected=mark['correction']['desired_outcome'],
            evidence_assets=[evaluation['evidence']['assets'][i] for i in slots],
            desired_outcome=mark['correction']['desired_outcome'], uncertainty=None,
            suggested_operation='correct_then_request_owner_resolution',
            edit_scope_authorized=mark['authorize_edit_scope'],
            permission_baseline_revision_id=run.get('edit_baseline_revision_id', mark['correction']['baseline_revision_id']),
            resolution_owner=mark['owner'], status=mark['correction']['status']))
    from ..feedback import groups
    bundle['correction_groups']=groups(bundle)
    bundle['bundle_version']=2
    return bundle


def save_feedback_in(con, run, bundle_id):
    rid = run['current_revision_id']
    revision = loop.get_in(con, 'agent_clip_revisions', rid)
    evaluation = loop.get_in(con, 'agent_evaluations', f'evaluation:{rid}')
    task = tasks._get(con, revision['task_id'])
    bundle = loop._feedback(run, task, revision, evaluation, [])
    if task.id!=run['task_id']:
        bundle['next_task_id']=run['task_id'];bundle['next_spec_sha256']=run['spec_sha256']
    bundle['id'] = bundle_id
    bundle['supersedes_feedback_id'] = run.get('feedback_id', f'feedback:{rid}')
    if bundle['continuation']['operation']=='agent_run_submit':
        bundle['continuation']['arguments']['feedback_id'] = bundle_id
    augment_in(con, bundle, run)
    loop.insert(con, 'agent_feedback', bundle)
    run['feedback_id'] = bundle_id
    return bundle


def mark(project, actor, run_id, payload):
    require_reviewer(actor, 'mark_issue')
    request = MarkRequest.model_validate(payload)
    con = loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run = loop.get_in(con, 'agent_runs', run_id)
            semantic = request.model_dump(mode='json')
            old = con.execute('SELECT data FROM agent_interventions WHERE id=?', (request.id,)).fetchone()
            if old:
                record = json.loads(old['data'])
                if record['request'] != semantic or record['owner'] != actor.id or record['run_id'] != run_id:
                    raise S.ConflictError('intervention ID is already bound to another saved action')
                return dict(record, feedback=loop.get_in(con, 'agent_feedback', record['handoff_id']))
            revision, evaluation = _bound(con, run, request.revision_id, request.evaluation_id)
            if run['lifecycle'] == 'cancelled':
                raise InvalidInput('a cancelled run cannot receive a new correction')
            spec = tasks._get(con, run['task_id']).spec
            if request.tick_range[1] > spec.timing.total_ticks():
                raise InvalidInput('markup range exceeds authored timing')
            if request.roi and (request.roi.right > spec.canvas.width or request.roi.bottom > spec.canvas.height):
                raise InvalidInput('markup region exceeds native canvas')
            starts = [sum(spec.timing.holds[:i]) for i in range(len(spec.timing.holds))]
            slots = [i for i, start in enumerate(starts)
                     if start < request.tick_range[1] and start + spec.timing.holds[i] > request.tick_range[0]]
            correction = D.CorrectionTask(id=request.id, source_issue_event_id=f'mark:{request.id}',
                baseline_revision_id=request.revision_id, baseline_evaluation_id=request.evaluation_id,
                origin='human', desired_outcome=request.desired_outcome,
                scope=f'authored ticks [{request.tick_range[0]}, {request.tick_range[1]})', status='open')
            record = dict(schema_version='3.0', id=request.id, run_id=run_id, task_id=run['task_id'],
                          request=semantic, owner=actor.id, correction=correction.model_dump(mode='json'),
                          tick_range=list(request.tick_range), slots=slots,
                          roi=request.roi.model_dump() if request.roi else None,
                          authorize_edit_scope=request.authorize_edit_scope,
                          candidate_revision_id=None, version=1, created_at=D.utcnow(),
                          handoff_id=f'handoff:{request.id}:1')
            loop.insert(con, 'agent_interventions', record)
            _event_in(con, run, actor, 'mark_issue', request.revision_id, request.evaluation_id,
                      note=request.desired_outcome, intervention_id=request.id, event_id=f'mark:{request.id}')
            if request.authorize_edit_scope:
                run.setdefault('edit_baseline_revision_id', request.revision_id)
            if run['lifecycle'] != 'blocked':
                run['lifecycle'] = 'awaiting_agent'
                run['stop_reason'] = 'Saved human correction requires an agent revision and explicit owner resolution.'
            bundle = save_feedback_in(con, run, record['handoff_id'])
            loop._update(con, run)
        return dict(record, feedback=bundle)
    finally:
        con.close()


def get(project, intervention_id):
    con = loop.connect(project)
    try:
        return loop.get_in(con, 'agent_interventions', intervention_id)
    finally:
        con.close()


def after_submission_in(con, run, revision_id, preservation_passed):
    for mark in open_in(con, run['id']):
        correction = D.CorrectionTask.model_validate(mark['correction'])
        correction.status = D.CorrectionStatus.AWAITING_COMPARISON
        correction.attempt_ids.append(revision_id)
        mark['correction'] = correction.model_dump(mode='json')
        mark['candidate_revision_id'] = revision_id
        mark['version'] += 1
        con.execute('UPDATE agent_interventions SET data=? WHERE id=?', (json.dumps(mark), mark['id']))
    if preservation_passed and run.get('edit_baseline_revision_id'):
        run['edit_baseline_revision_id'] = revision_id


def preservation_in(con, project, run, images, spec):
    grants = [m for m in open_in(con, run['id']) if m['authorize_edit_scope']]
    if not grants:
        return []
    baseline = loop.get_in(con, 'agent_clip_revisions', run['edit_baseline_revision_id'])
    results = []
    for slot, (aid, image) in enumerate(zip(baseline['frame_asset_ids'], images)):
        outcome, observed = 'unmeasured', None
        try:
            asset, _ = S.get(con, 'assets', aid)
            blob = S.blob_path(project, asset['byte_sha256'])
            if S.sha256_bytes(blob.read_bytes()) != asset['byte_sha256']:
                raise ValueError('baseline bytes changed')
            original = load_native_image(blob)
            if image is not None and original.size == image.size:
                support = np.zeros((image.height, image.width), dtype=bool)
                for grant in grants:
                    if slot in grant['slots']:
                        roi = grant['roi'] or dict(left=0, top=0, right=image.width, bottom=image.height)
                        support[roi['top']:roi['bottom'], roi['left']:roi['right']] = True
                delta = np.any(np.asarray(original) != np.asarray(image), axis=2)
                observed = int(np.sum(delta & ~support))
                outcome = 'pass' if observed == 0 else 'fail'
        except (OSError, ValueError, KeyError):
            pass
        start = sum(spec.timing.holds[:slot])
        results.append(dict(id=f'edit-preservation-{slot}', family='edit_preservation', required=True,
            slots=[slot], tick_range=[start, start+spec.timing.holds[slot]], outcome=outcome,
            observed=observed, expected=0, roi=None, source='reviewer_authorized_scope',
            evidence_method='exact-canonical-rgba-outside-saved-support-v1', confidence=None,
            reason='Preserve all pixels outside explicitly authorized native edit support, including other frames. Spatial markup alone does not authorize edits.',
            baseline_revision_id=baseline['id'], grant_ids=[m['id'] for m in grants]))
    return results


def render(bundle, *, portable=False):
    """Portable text contains only saved, user-visible instruction and evidence fields."""
    lines = [f"Continue animation run {bundle['run_id']} in project {bundle['project_id']}.",
             f"Task {bundle['task_id']} targets revision {bundle['baseline_revision_id']}, evaluation {bundle['evaluation_id']}.",
             f"Saved feedback: {bundle['id']}; specification digest: {bundle['spec_sha256']}.",
             ('Open manifest.json and resolve asset IDs through its packaged assets map. Verify the saved hashes before editing.' if portable else 'First fetch agent_run_get and task_get. Verify the current revision and saved feedback ID before editing.'), '']
    if bundle.get('next_task_id'):
        lines.append(f"Task policy explicitly revised: {'read the packaged task' if portable else 'fetch'} {bundle['next_task_id']} with digest {bundle['next_spec_sha256']} before the next submission. Old evaluation evidence remains bound to the old task.")
    lines.append(f"Disposition: {bundle['disposition']}. {bundle.get('reason') or ''}")
    if bundle['disposition']=='blocked':
        lines.append('This run is stopped. Fetch agent_run_get for the recorded blocker and report it; do not submit or reset limits under a new run name.')
        return '\n'.join(lines)+'\n'
    if bundle['disposition']=='complete' and not bundle['targets']:
        lines.append('The named policy is satisfied; no further edit is requested. Creative status: '+bundle['creative_status']+'.')
        return '\n'.join(lines)+'\n'
    for target in sorted(bundle['targets'], key=lambda t: (t['priority'], min(t['slots']), t['id'])):
        lines.append(f"Target {target['id']}: frames {', '.join(map(str,target['display_numbers']))}, ticks [{target['tick_range'][0]}, {target['tick_range'][1]}).")
        lines.append('Requested correction: '+target['desired_outcome'])
        lines.append('Observed: '+json.dumps(target.get('observed'))+'; expected: '+json.dumps(target.get('expected'))+'.')
        if target.get('roi'):
            lines.append('Native pixel region: '+json.dumps(target['roi'],sort_keys=True))
        if target.get('edit_scope_authorized'):
            lines.append('Edit support is explicitly authorized only for the saved range/region; preserve pixels outside it.')
        for asset in target['evidence_assets']:
            lines.append(f"Evidence asset {asset['id']}: sha256 {asset['byte_sha256']}; {('assets/'+asset['byte_sha256']+'.png') if portable else asset.get('blob_path', asset.get('http_path', 'resolve with project access'))}")
        lines.append('')
    lines.append('Preserve: '+('; '.join(bundle['preserve']) or 'the task requirements and unchanged assets')+'.')
    lines.append('Preserve exact authored timing: '+json.dumps(bundle['timing'],sort_keys=True)+'.')
    lines.append(f"Remaining submission budget: {bundle['remaining_submissions']}. Correction text does not override execution permissions or limits.")
    if portable:
        lines.append('Return response.json beside the corrected native PNG files. Keep asset_id entries for unchanged frames; replace changed entries with file paths relative to response.json.')
        lines.append('Response format: '+json.dumps(dict(revision_id='<new immutable ID>',frames=[dict(asset_id='<unchanged asset ID>'),dict(file='corrected.png',rights='unknown',source_kind='generated')],generation_metadata=None),sort_keys=True))
        lines.append('The complete ordered frames list must match the task holds. Record actual rights and available generation metadata; do not invent either.')
        lines.append('The project owner imports the returned directory with: framebound agent-handoff-import --project <project-directory> --manifest <unpacked-manifest.json> --response <response.json>.')
        lines.append('Import rechecks the current saved bindings and edit limits, then evaluates the full clip. Pasted text and this manifest are not authorization tokens. If scope is insufficient, return the concrete blocker.')
        return '\n'.join(lines)+'\n'
    lines.append('Without MCP, fetch state with framebound agent-run-get --project <project-directory> --run-id '+bundle['run_id']+' and framebound task-get --project <project-directory> --task-id '+bundle.get('next_task_id',bundle['task_id'])+'.')
    lines.append('Import changed assets with asset_import, reuse unchanged asset IDs, then call agent_run_submit with:')
    lines.append(json.dumps(bundle['continuation']['arguments'],sort_keys=True))
    lines.append('CLI equivalent: framebound agent-run-submit --project <project-directory> --submission <JSON-file-with-these-arguments>.')
    lines.append('Re-evaluate the full clip using the returned feedback. Human corrections stay open until their configured owner resolves them.')
    lines.append('If bindings are stale, fetch current feedback and request an explicit rebase; do not apply this instruction to another revision.')
    return '\n'.join(lines)+'\n'


def handoff(project, feedback_id):
    con = loop.connect(project)
    try:
        bundle = loop.get_in(con, 'agent_feedback', feedback_id)
        run = loop.get_in(con, 'agent_runs', bundle['run_id'])
        current = run.get('feedback_id', f"feedback:{run['current_revision_id']}")
        stale = bundle['baseline_revision_id'] != run['current_revision_id'] or feedback_id != current
        return dict(bundle=bundle, text=render(bundle), stale=stale,
                    current_revision_id=run['current_revision_id'], current_feedback_id=current,
                    reason='Saved instructions target an older revision or superseded action; fetch current feedback before editing.' if stale else None)
    finally:
        con.close()


def approved_in(con, run_id, revision_id, evaluation_id, run=None):
    run = run or loop.get_in(con, 'agent_runs', run_id)
    decision_id = run.get('human_decision_id')
    if not decision_id:
        return False
    event = loop.get_in(con, 'agent_run_events', decision_id)
    return (event['event'] == 'approve' and event['source'] == 'human'
            and event['revision_id'] == revision_id and event['evaluation_id'] == evaluation_id)


def reconcile_in(con, run, event_id):
    rid = run['current_revision_id']
    evaluation = loop.get_in(con, 'agent_evaluations', f'evaluation:{rid}')
    spec = tasks._get(con, run['task_id']).spec
    passed = evaluation['technical_status'] == 'pass' and evaluation['coverage'] == 'complete'
    if open_in(con, run['id']):
        run['lifecycle'] = 'awaiting_decision' if passed else 'awaiting_agent'
        run['stop_reason'] = 'Saved human corrections remain unresolved.'
    elif passed and ((spec.completion.id == 'technical-unreviewed-v1' and spec.intervention != 'explicit_review') or approved_in(con, run['id'], rid, evaluation['id'], run)):
        run['lifecycle'], run['stop_reason'] = 'completed', 'Declared requirements and exact task completion policy are satisfied.'
        run['best_revision_id'] = rid
        loop.insert(con, 'agent_completions', dict(schema_version='3.0', id=f'completion:{event_id}',
            run_id=run['id'], task_id=run['task_id'], revision_id=rid, evaluation_id=evaluation['id'],
            policy=spec.completion.model_dump(), evidence_digest=evaluation['evidence_digest'],
            creative_status=run['creative_status'], output_eligibility='human-reviewed' if approved_in(con,run['id'],rid,evaluation['id'],run) else 'automatic-technical',
            quality_scope='declared camera/landmark constraints; semantics unverified' if spec.profile=='tracked-scene-v1' else 'declared-region constraints' if spec.profile=='fixed-subject-v1' else 'structural only; animation quality not verified'))
    elif passed:
        run['lifecycle'], run['stop_reason'] = 'awaiting_decision', 'Exact-revision human decision required by task policy.'
    elif len(run['submission_ids']) >= run['limits']['max_submissions'] or run['no_progress_count'] >= run['limits']['max_unchanged']:
        run['lifecycle'], run['stop_reason'] = 'blocked', 'Persistent submission or no-progress limit reached.'
    else:
        run['lifecycle'], run['stop_reason'] = 'awaiting_agent', 'Continue from the saved required-check feedback.'


def _owner(actor, mark):
    require_reviewer(actor, 'resolve_issue')
    if actor.id != mark['owner']:
        from ...v2.services.errors import AuthorizationError
        raise AuthorizationError('only this correction owner may resolve or reopen it')


def resolve(project, actor, intervention_id, payload, *, reopen=False):
    request = ResolveRequest.model_validate(payload)
    con = loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            mark = loop.get_in(con, 'agent_interventions', intervention_id)
            _owner(actor, mark)
            if mark['version'] != request.expected_version:
                raise S.StaleRevisionError('intervention changed; fetch its current version before deciding')
            run = loop.get_in(con, 'agent_runs', mark['run_id'])
            _, evaluation = _bound(con, run, request.revision_id, request.evaluation_id)
            if run['lifecycle'] == 'cancelled':
                raise InvalidInput('cancelled runs cannot be resumed by resolving or reopening a correction')
            correction = D.CorrectionTask.model_validate(mark['correction'])
            if reopen:
                if correction.status != 'resolved':
                    raise InvalidInput('only a resolved correction can be reopened')
                correction.status = D.CorrectionStatus.REOPENED
                correction.resolution_event_id = None
            else:
                if correction.status in {'resolved', 'cancelled'}:
                    raise InvalidInput('correction is already closed')
                if mark['candidate_revision_id'] != request.revision_id:
                    raise S.StaleRevisionError('resolution must inspect the actual submitted replacement revision')
                correction.status = D.CorrectionStatus.RESOLVED
            event = _event_in(con, run, actor, 'reopen_issue' if reopen else 'resolve_issue',
                request.revision_id, request.evaluation_id, note=request.note, intervention_id=intervention_id)
            if not reopen:
                correction.resolution_event_id = event['id']
            mark['correction'], mark['version'] = correction.model_dump(mode='json'), mark['version']+1
            con.execute('UPDATE agent_interventions SET data=? WHERE id=?', (json.dumps(mark), intervention_id))
            # A reopen changes the exact baseline only by this explicit owner action.
            if reopen and mark['authorize_edit_scope']:
                run['edit_baseline_revision_id'] = request.revision_id
            reconcile_in(con, run, event['id'])
            mark['handoff_id'] = f"handoff:{intervention_id}:{mark['version']}"
            bundle = save_feedback_in(con, run, mark['handoff_id'])
            con.execute('UPDATE agent_interventions SET data=? WHERE id=?', (json.dumps(mark), intervention_id))
            loop._update(con, run)
        return dict(mark, feedback=bundle)
    finally:
        con.close()


def decision(project, actor, run_id, payload):
    require_reviewer(actor, 'approve')
    request = DecisionRequest.model_validate(payload)
    con = loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run = loop.get_in(con, 'agent_runs', run_id)
            event_id = f'decision:{request.id}'
            existing = con.execute('SELECT data FROM agent_run_events WHERE id=?', (event_id,)).fetchone()
            if existing:
                event = json.loads(existing['data'])
                if DecisionRequest.model_validate(event.get('request')).model_dump(mode='json') != request.model_dump(mode='json') or event['actor_id'] != actor.id or event['run_id'] != run_id:
                    raise S.ConflictError('decision ID is already bound to another reviewer action')
                return dict(event=event, feedback=loop.get_in(con,'agent_feedback',f'handoff:{event_id}'))
            _bound(con, run, request.revision_id, request.evaluation_id)
            if run['lifecycle']=='cancelled':
                raise InvalidInput('cancelled runs cannot be completed by a decision')
            event = _event_in(con, run, actor, request.action, request.revision_id,
                             request.evaluation_id, note=request.note, event_id=event_id)
            event['request'] = request.model_dump(mode='json')
            con.execute('UPDATE agent_run_events SET data=? WHERE id=?', (json.dumps(event), event_id))
            if request.comparison_revision_id:
                chosen=loop.get_in(con,'agent_clip_revisions',request.revision_id)
                rejected=loop.get_in(con,'agent_clip_revisions',request.comparison_revision_id)
                rejected_eval=loop.get_in(con,'agent_evaluations',request.comparison_evaluation_id)
                if rejected['task_id']!=chosen['task_id'] or rejected['run_id']!=run_id or rejected_eval['revision_id']!=rejected['id']:
                    raise InvalidInput('explicit preference needs distinct same-task revisions and their actual evaluations')
                preference=dict(schema_version='3.0',id=f'preference:{request.id}',run_id=run_id,task_id=chosen['task_id'],
                    chosen_revision_id=chosen['id'],chosen_evaluation_id=request.evaluation_id,
                    rejected_revision_id=rejected['id'],rejected_evaluation_id=rejected_eval['id'],
                    decision_event_id=event_id,source='human_comparison',actor_id=actor.id,note=request.note,created_at=D.utcnow())
                loop.insert(con,'agent_preferences',preference)
                _event_in(con,run,actor,'prefer_revision',chosen['id'],request.evaluation_id,
                          note=f"Explicitly preferred over {rejected['id']}. {request.note}",event_id=f'preference-event:{request.id}')
            run['creative_status'] = {'approve':'human_approved','reject':'human_rejected','needs_changes':'human_needs_changes'}[request.action]
            run['human_decision_id'] = event_id
            if request.action != 'approve':
                spec = tasks._get(con, run['task_id']).spec
                cid = f'decision-task:{request.id}'
                correction = D.CorrectionTask(id=cid, source_issue_event_id=event_id,
                    baseline_revision_id=request.revision_id, baseline_evaluation_id=request.evaluation_id,
                    origin='human', desired_outcome=request.note or f'Reviewer decision: {request.action}; obtain the concrete requested change before editing.',
                    scope='entire authored clip', status='open')
                loop.insert(con,'agent_interventions',dict(schema_version='3.0',id=cid,run_id=run_id,task_id=run['task_id'],
                    request=request.model_dump(mode='json'),owner=actor.id,correction=correction.model_dump(mode='json'),
                    tick_range=[0,spec.timing.total_ticks()],slots=list(range(len(spec.timing.holds))),roi=None,
                    authorize_edit_scope=False,candidate_revision_id=None,version=1,created_at=D.utcnow(),handoff_id=f'handoff:{event_id}'))
            reconcile_in(con, run, event_id)
            # Rejection asks for work even if technical checks happen to pass.
            if request.action != 'approve' and run['lifecycle'] != 'blocked':
                run['lifecycle'],run['stop_reason']='awaiting_agent','Reviewer requested changes; retain the exact saved note and task limits.'
            bundle=save_feedback_in(con,run,f'handoff:{event_id}')
            loop._update(con,run)
        return dict(event=event,feedback=bundle)
    finally:
        con.close()


def rebase(project, actor, feedback_id, *, expected_revision_id, expected_feedback_id):
    """An explained, explicit new bundle; never silently retarget pasted instructions."""
    require_reviewer(actor, 'mark_issue')
    con=loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            old=loop.get_in(con,'agent_feedback',feedback_id)
            run=loop.get_in(con,'agent_runs',old['run_id'])
            if (run['current_revision_id'] != expected_revision_id or
                run.get('feedback_id',f"feedback:{run['current_revision_id']}") != expected_feedback_id):
                raise S.StaleRevisionError('run changed while rebase was being prepared')
            if old['task_id'] != run['task_id']:
                raise S.StaleRevisionError('task specification changed; negotiate new instructions instead of rebasing old constraints')
            event=_event_in(con,run,actor,'handoff_rebase',expected_revision_id,
                f'evaluation:{expected_revision_id}',note=f"Explicit rebase of {feedback_id}; current requirements and open corrections reloaded.")
            bundle=save_feedback_in(con,run,f"handoff:{event['id']}")
            loop._update(con,run)
        return bundle
    finally:con.close()


def agent_satisfied(project, actor, run_id, *, revision_id, evaluation_id, note=''):
    """Explicit parent-agent judgment never creates reviewer authority or closes human work."""
    if actor.type != 'orchestrator' or not actor.id:
        from ...v2.services.errors import AuthorizationError
        raise AuthorizationError('parent-agent judgment requires an orchestrator principal')
    if not isinstance(note, str) or len(note) > 2000:
        raise InvalidInput('agent judgment note must be text up to 2000 characters')
    con = loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run = loop.get_in(con,'agent_runs',run_id)
            _bound(con,run,revision_id,evaluation_id)
            if run['lifecycle']=='cancelled':
                raise InvalidInput('cancelled runs cannot be resumed by agent judgment')
            event = _event_in(con,run,actor,'agent_satisfied',revision_id,evaluation_id,note=note)
            run['agent_satisfaction_event_id']=event['id']
            # Existing exact human acceptance/rejection remains a distinct and stronger label.
            if not run['creative_status'].startswith('human_'):
                run['creative_status']='agent_satisfied'
            bundle=save_feedback_in(con,run,f"handoff:{event['id']}")
            loop._update(con,run)
        return dict(event=event,feedback=bundle)
    finally:con.close()
