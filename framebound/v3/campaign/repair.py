"""Task-authored automatic repair authority and blinded comparative evidence."""
from __future__ import annotations

import hashlib
import json
import random
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import Field, StrictInt

from ...v2 import storage as S
from ...v2.services.errors import InvalidInput
from ..services import loop, tasks
from .assessment import Assessment, Binding, Category, Provenance
from .contracts import Strict, canonical, digest


from .repair_policy import AutomaticRepairPolicy

class Scope(Strict):
    slots: list[StrictInt] = Field(min_length=1,max_length=24)
    roi: tuple[StrictInt,StrictInt,StrictInt,StrictInt] | None = None


def binding_in(con, run):
    revision = loop.get_in(con,'agent_clip_revisions',run['current_revision_id'])
    evaluation = loop.get_in(con,'agent_evaluations','evaluation:'+revision['id'])
    task = tasks._get(con,run['task_id'])
    return Binding(request_sha256=task.spec_sha256,revision_sha256=digest(revision),
        timing_sha256=digest(task.spec.timing.model_dump(mode='json')),evaluation_sha256=digest(evaluation))


def authorize(project, run_id, assessment: Assessment, independent: Assessment, finding_id):
    """Reopens technical completion with exact evidence, without task revision."""
    con = loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            run = loop.get_in(con,'agent_runs',run_id)
            spec = tasks._get(con,run['task_id']).spec
            policy = spec.automatic_repair
            if not policy or not policy.enabled or run['lifecycle'] in {'cancelled','blocked'}:
                raise InvalidInput('task does not authorize automatic repair or run is stopped')
            binding = binding_in(con,run)
            for a in (assessment,independent):
                a.validate_evidence(binding,spec.timing.holds,(spec.canvas.width,spec.canvas.height))
            if assessment.provenance.execution_id == independent.provenance.execution_id:
                raise InvalidInput('independent execution required')
            f = next((f for f in assessment.findings if f.id == finding_id),None)
            if f is None or f.category not in policy.categories or f.visibility != 'supported':
                raise InvalidInput('unsupported target category or visibility')
            agreement = any(g.category == f.category and g.subject == f.subject and g.visibility == 'supported'
                and set(g.slots) == set(f.slots) and g.severity in {'material','critical'} for g in independent.findings)
            if f.severity not in {'material','critical'} or not agreement:
                raise InvalidInput('material target lacks independent corroboration')
            if not set(f.slots) <= set(policy.allowed_slots) or (f.roi is None and not policy.allow_full_frame):
                raise InvalidInput('requested edit exceeds task-authored scope')
            authority_id = 'auto-'+digest([run_id,binding.model_dump(),assessment.model_dump(),independent.model_dump(),finding_id])[:48]
            old = con.execute('SELECT data FROM agent_auto_authorities WHERE id=?',(authority_id,)).fetchone()
            if old: return json.loads(old['data'])
            previous = [json.loads(r['data']) for r in con.execute('SELECT data FROM agent_auto_authorities') if json.loads(r['data'])['run_id']==run_id]
            if len(previous) >= policy.max_attempts or any(a['candidate_revision_id'] is None for a in previous):
                raise InvalidInput('persistent automatic repair limit or outstanding authority')
            if len(run['submission_ids']) >= run['limits']['max_submissions']:
                raise InvalidInput('persistent submission limit')
            record = dict(id=authority_id,run_id=run_id,task_id=run['task_id'],baseline_revision_id=run['current_revision_id'],
                binding=binding.model_dump(),source='task_authored_automatic',scope=Scope(slots=f.slots,roi=f.roi).model_dump(),
                assessment=assessment.model_dump(mode='json'),independent=independent.model_dump(mode='json'),finding_id=f.id,
                candidate_revision_id=None,status='authorized',instruction=f'Correct {f.category} on {f.subject}: {f.observed}. '
                    f'Expected: {f.expected}. Preserve identity, props, palette, timing and every pixel outside declared support.')
            loop.insert(con,'agent_auto_authorities',record)
            run['learned_coverage_status']='repair_pending'
            run.setdefault('learned_best_revision_id',run['current_revision_id'])
            run['lifecycle']='awaiting_agent';run['stop_reason']='Task-authored automatic correction; original specification and lifetime limits retained.'
            loop.insert(con,'agent_run_events',dict(id=authority_id+'-event',run_id=run_id,task_id=run['task_id'],
                event='automatic_diagnosis_reopens_technical_completion',source='task_authored_automatic',authority_id=authority_id,
                revision_id=run['current_revision_id'],binding=binding.model_dump()))
            loop._update(con,run)
            return record
    finally:
        con.close()


def active_in(con, run_id):
    return [json.loads(r['data']) for r in con.execute('SELECT data FROM agent_auto_authorities')
        if json.loads(r['data'])['run_id']==run_id and json.loads(r['data'])['status']=='authorized']


def composite(baseline, raw_candidate, scope: Scope):
    if len(baseline) != len(raw_candidate) or any(s<0 or s>=len(baseline) for s in scope.slots):
        raise ValueError('candidate/native scope length mismatch')
    result = []
    for slot,(base,candidate) in enumerate(zip(baseline,raw_candidate)):
        if base.size != candidate.size:
            raise ValueError('normalization must be explicit before compositing')
        output = base.convert('RGBA').copy()
        if slot in scope.slots:
            roi = scope.roi or (0,0,*base.size)
            x0,y0,x1,y1=roi
            if not 0<=x0<x1<=base.width or not 0<=y0<y1<=base.height:
                raise ValueError('native scope exceeds canvas')
            output.paste(candidate.convert('RGBA').crop(roi),(x0,y0))
        result.append(output)
    return result


def preservation_in(con, project, run, images, spec):
    authorities = active_in(con,run['id'])
    if not authorities: return []
    authority = authorities[-1]
    baseline = loop.get_in(con,'agent_clip_revisions',authority['baseline_revision_id'])
    scope = Scope.model_validate(authority['scope'])
    results = []
    for slot,(aid,image) in enumerate(zip(baseline['frame_asset_ids'],images)):
        asset,_=S.get(con,'assets',aid);path=S.blob_path(project,asset['byte_sha256'])
        if S.sha256_bytes(path.read_bytes()) != asset['byte_sha256']:
            raise InvalidInput('automatic authority baseline bytes changed')
        with Image.open(path) as source: base=np.asarray(source.convert('RGBA'))
        supported=np.zeros(base.shape[:2],dtype=bool)
        if slot in scope.slots:
            x0,y0,x1,y1=scope.roi or (0,0,base.shape[1],base.shape[0]);supported[y0:y1,x0:x1]=True
        changed = None if image is None or np.asarray(image).shape!=base.shape else int(np.sum(np.any(base!=np.asarray(image),axis=2)&~supported))
        results.append(dict(id=f'auto-preservation-{slot}',family='edit_preservation',required=True,slots=[slot],
            tick_range=[sum(spec.timing.holds[:slot]),sum(spec.timing.holds[:slot+1])],outcome='unmeasured' if changed is None else 'pass' if changed==0 else 'fail',
            observed=changed,expected=0,roi=None,source='task_authored_automatic',evidence_method='exact-native-rgba-outside-task-support-v1',
            confidence=None,reason='Protected pixels must remain exact',authority_id=authority['id']))
    return results


def after_submission_in(con, run, revision_id):
    for a in active_in(con,run['id']):
        a['status']='awaiting_comparison';a['candidate_revision_id']=revision_id
        con.execute('UPDATE agent_auto_authorities SET data=? WHERE id=?',(canonical(a).decode(),a['id']))
        run['learned_coverage_status']='comparison_pending'


class Comparison(Strict):
    assignment_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    preference: Literal['A','B','tie','insufficient_evidence']
    target_improved: bool | None
    material_regression: bool | None
    evidence: str = Field(min_length=1,max_length=4000)
    assessed_categories: list[Category] = Field(min_length=1,max_length=9)
    provenance: Provenance


def blind_assignment(case_id, first_sha256, second_sha256, *, seed, reverse=False):
    values=[first_sha256,second_sha256]
    random.Random(digest([seed,case_id,first_sha256,second_sha256])).shuffle(values)
    if reverse: values.reverse()
    # Only opaque hashes/order are sent to comparator, never proposed-repair labels.
    return dict(case_id=case_id,A=values[0],B=values[1],rubric='independent-temporal-comparison-v1')


def decide(assignment, comparison: Comparison, *, candidate_sha256, target_category, preservation_passed):
    if comparison.assignment_sha256 != digest(assignment):
        raise ValueError('stale comparison assignment')
    if candidate_sha256 not in (assignment['A'],assignment['B']) or assignment['A']==assignment['B']:
        return 'unchanged'
    if comparison.preference == 'insufficient_evidence' or comparison.target_improved is None or comparison.material_regression is None:
        return 'ambiguous'
    if comparison.material_regression or not preservation_passed:
        return 'rejected'
    if target_category not in comparison.assessed_categories:
        return 'ambiguous'
    if comparison.preference == 'tie': return 'unchanged'
    chosen=assignment[comparison.preference]
    return 'accepted' if chosen==candidate_sha256 and comparison.target_improved else 'rejected'


def prepare_comparisons(project, authority_id, *, seed=0):
    con=loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            a=loop.get_in(con,'agent_auto_authorities',authority_id)
            if not a['candidate_revision_id']: raise InvalidInput('candidate not submitted')
            run=loop.get_in(con,'agent_runs',a['run_id'])
            candidate=loop.get_in(con,'agent_clip_revisions',a['candidate_revision_id'])
            rows=[]
            for baseline_id in dict.fromkeys([run['submission_ids'][0],run.get('learned_best_revision_id',a['baseline_revision_id'])]):
                baseline=loop.get_in(con,'agent_clip_revisions',baseline_id)
                assignment=blind_assignment(run['id'],digest(baseline),digest(candidate),seed=seed)
                record=dict(id=digest([authority_id,baseline_id]),authority_id=authority_id,assignment=assignment,
                    baseline_revision_id=baseline_id,candidate_revision_id=candidate['id'],candidate_sha256=digest(candidate),comparison=None,outcome=None)
                old=con.execute('SELECT data FROM agent_auto_comparisons WHERE id=?',(record['id'],)).fetchone()
                if old: record=json.loads(old['data'])
                else: loop.insert(con,'agent_auto_comparisons',record)
                rows.append(record)
            return rows
    finally: con.close()


def record_comparison(project, comparison_id, comparison: Comparison):
    con=loop.connect(project)
    try:
        with S.atomic(con):
            con.execute('BEGIN IMMEDIATE')
            record=loop.get_in(con,'agent_auto_comparisons',comparison_id)
            if record['comparison']:
                if record['comparison']!=comparison.model_dump(mode='json'): raise InvalidInput('comparison is immutable')
                return record
            a=loop.get_in(con,'agent_auto_authorities',record['authority_id']);run=loop.get_in(con,'agent_runs',a['run_id'])
            if run['current_revision_id'] != record['candidate_revision_id']: raise InvalidInput('stale candidate comparison')
            if comparison.provenance.execution_id in {a['assessment']['provenance']['execution_id'],a['independent']['provenance']['execution_id']}:
                raise InvalidInput('comparison must be a separate execution from diagnosis')
            evaluation=loop.get_in(con,'agent_evaluations','evaluation:'+record['candidate_revision_id'])
            target=next(f for f in a['assessment']['findings'] if f['id']==a['finding_id'])
            preservation=all(r['outcome']=='pass' for r in evaluation['results'] if r['family']=='edit_preservation')
            record['outcome']=decide(record['assignment'],comparison,candidate_sha256=record['candidate_sha256'],target_category=target['category'],
                preservation_passed=preservation and evaluation['technical_status']=='pass')
            record['comparison']=comparison.model_dump(mode='json')
            con.execute('UPDATE agent_auto_comparisons SET data=? WHERE id=?',(canonical(record).decode(),record['id']))
            rows=[json.loads(r['data']) for r in con.execute('SELECT data FROM agent_auto_comparisons') if json.loads(r['data'])['authority_id']==a['id']]
            required=set([run['submission_ids'][0],run.get('learned_best_revision_id',a['baseline_revision_id'])])
            if required <= {r['baseline_revision_id'] for r in rows if r['comparison']}:
                outcomes={r['outcome'] for r in rows}
                outcome='ambiguous' if 'ambiguous' in outcomes else 'rejected' if 'rejected' in outcomes else 'accepted' if outcomes=={'accepted'} else 'unchanged'
                a['status']=outcome
                con.execute('UPDATE agent_auto_authorities SET data=? WHERE id=?',(canonical(a).decode(),a['id']))
                run['learned_coverage_status']='assessed_model_comparison'
                if outcome=='accepted': run['learned_best_revision_id']=a['candidate_revision_id']
                run['lifecycle']='completed';run['stop_reason']='Automatic model comparison finished: '+outcome+'; coverage limitations retained.'
                loop._update(con,run)
            return record
    finally: con.close()
