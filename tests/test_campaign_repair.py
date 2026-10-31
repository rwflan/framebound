import numpy as np
import pytest
from PIL import Image

from framebound.v3.campaign.assessment import Provenance
from framebound.v3.campaign.contracts import digest
from framebound.v3.campaign.repair import Scope, Comparison, blind_assignment, composite, decide


def test_raw_is_retained_and_only_authorized_pixels_are_composited():
    base = [Image.new('RGBA',(8,8),'red') for _ in range(3)]
    raw = [Image.new('RGBA',(8,8),'blue') for _ in range(3)]
    output = composite(base,raw,Scope(slots=[1],roi=(2,2,4,4)))
    assert np.array_equal(np.asarray(base[0]),np.asarray(output[0]))
    assert np.sum(np.any(np.asarray(base[1])!=np.asarray(output[1]),axis=2)) == 4
    assert raw[1].getpixel((0,0)) == (0,0,255,255)


def test_blinding_ties_uncertainty_regressions_and_original_preferred():
    assignment=blind_assignment('case','a'*64,'b'*64,seed=1)
    reverse=blind_assignment('case','a'*64,'b'*64,seed=1,reverse=True)
    assert assignment['A']==reverse['B']
    p=Provenance(provider='engineering',requested_model='test',rubric_sha256='a'*64,raw_sha256='b'*64,execution_id='test')
    c=Comparison(assignment_sha256=digest(assignment),preference='A',target_improved=True,material_regression=False,evidence='Test-only comparison',assessed_categories=['parts'],provenance=p)
    kw=dict(candidate_sha256=assignment['A'],target_category='parts',preservation_passed=True)
    assert decide(assignment,c,**kw)=='accepted'
    for update,result in [({'preference':'B'},'rejected'),({'preference':'tie'},'unchanged'),({'material_regression':True},'rejected'),({'material_regression':None},'ambiguous')]:
        assert decide(assignment,c.model_copy(update=update),**kw)==result


def test_task_authored_diagnosis_reopens_completed_without_revising_task(tmp_path):
    from framebound.v3.campaign import repair as R
    from framebound.v3.campaign.assessment import abstention, Assessment
    from framebound.v3.services import loop, tasks
    from test_agent_loop import setup
    project,spec,good=setup(tmp_path)
    # A new immutable task authorizes automatic corrections at creation time.
    spec.update(id='auto-task',animation_id='auto-animation',repair_scope='declared_regions',
        automatic_repair=dict(enabled=True,categories=['parts'],allowed_slots=[0],allow_full_frame=True))
    tasks.create(project,spec);loop.start(project,'auto-task','auto-run')
    loop.submit(project,'auto-run','auto-base',good)
    before=loop.get(project,'auto-run');assert before['lifecycle']=='completed'
    con=loop.connect(project)
    try: binding=R.binding_in(con,before)
    finally: con.close()
    p=Provenance(provider='engineering',requested_model='test',rubric_sha256='a'*64,raw_sha256='b'*64,execution_id='diagnosis-1')
    a=abstention(binding,p,list(range(len(good))),'Synthetic scope only').model_dump()
    a['coverage'][1].update(status='present',slots=[0])
    a['findings']=[dict(id='f',category='parts',slots=[0],tick_range=[0,1],subject='actor',severity='material',
        visibility='supported',observed='Synthetic observation',expected='Synthetic repair',counterexamples='Synthetic occlusion considered')]
    a=Assessment.model_validate(a)
    independent=a.model_copy(update={'provenance':p.model_copy(update={'execution_id':'diagnosis-2'})})
    authority=R.authorize(project,'auto-run',a,independent,'f')
    run=loop.get(project,'auto-run')
    assert run['task_id']==before['task_id'] and run['submission_ids']==before['submission_ids']
    assert run['lifecycle']=='awaiting_agent' and authority['source']=='task_authored_automatic'
    assert R.authorize(project,'auto-run',a,independent,'f')==authority
    loop.submit(project,'auto-run','auto-candidate',good,parent_revision_id='auto-base',feedback_id=run['feedback_id'])
    comparisons=R.prepare_comparisons(project,authority['id'])
    row=comparisons[0]
    c=Comparison(assignment_sha256=digest(row['assignment']),preference='tie',target_improved=False,material_regression=False,
        evidence='Engineering tie',assessed_categories=['parts'],provenance=p.model_copy(update={'execution_id':'comparator'}))
    result=R.record_comparison(project,row['id'],c)
    assert result['outcome']=='unchanged'
    assert loop.get(project,'auto-run')['learned_best_revision_id']=='auto-base'
