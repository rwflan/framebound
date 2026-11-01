import base64,io,json
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from framebound.v3.services import studio,loop
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError,InvalidInput
from framebound.v2 import storage as S
from framebound.v3.campaign.dispatch import Response
from framebound.v3.campaign.contracts import canonical
from test_agent_loop import setup

REVIEWER=Actor(type='reviewer',id='engineering-reviewer')
def prepared(tmp_path):
    project,spec,frames=setup(tmp_path);loop.submit(project,'run','base',frames)
    cid=studio.seed(project,'base');studio.allocate(project,100000)
    return project,cid
class Fake:
    def __init__(self):self.calls=0
    def execute(self,request,*,timeout):
        self.calls+=1;out=io.BytesIO();im=Image.new('RGBA',(96,64));draw=ImageDraw.Draw(im)
        for i in range(6):draw.rectangle((i%3*32+8,i//3*32+8,i%3*32+24,i//3*32+24),fill='blue')
        im.save(out,format='PNG')
        return Response(canonical(dict(status='completed',output=[dict(type='image_generation_call',result=base64.b64encode(out.getvalue()).decode())])),10000,1,{'id':'TEST-ONLY'})
def test_iterate_markup_approval_and_stale_duplicate(tmp_path):
    p,c=prepared(tmp_path);req=dict(id='feedback-one',version_id='base',text='Keep the prop visible',strokes=[dict(slot=1,tool='highlighter',color='#ffaa00',width=2,points=[[1,1],[3,3]])])
    first=studio.submit(p,REVIEWER,c,req);assert studio.submit(p,REVIEWER,c,req)==first
    fake=Fake();studio.drain(p,fake);view=studio.snapshot(p,c);assert len(view['versions'])==2
    assert view['feedback'][0]['state']=='completed' and fake.calls==1
    with pytest.raises(S.StaleRevisionError):studio.submit(p,REVIEWER,c,dict(req,id='stale'))
    current=view['case']['current'];studio.submit(p,REVIEWER,c,dict(id='feedback-two',version_id=current,text='Adjust the pose'))
    with pytest.raises(InvalidInput):studio.approve(p,REVIEWER,c,current)
    studio.drain(p,fake);view=studio.snapshot(p,c);assert len(view['versions'])==3
    approval=studio.approve(p,REVIEWER,c,view['case']['current']);assert approval['source']=='human'
    assert studio.snapshot(p,c)['case']['status']=='approved'
    assert studio.approve(p,REVIEWER,c,view['case']['current'])==approval
    assert fake.calls==2

def test_unknown_send_is_not_retried_or_approved(tmp_path):
    p,c=prepared(tmp_path);studio.submit(p,REVIEWER,c,dict(id='unknown',version_id='base',text='Fix pose'))
    class Timeout:
        def execute(self,*a,**kw):raise TimeoutError('synthetic lost response')
    studio.drain(p,Timeout());assert studio.snapshot(p,c)['feedback'][0]['state']=='unknown'
    f=Fake();studio.drain(p,f);assert f.calls==0
    with pytest.raises(InvalidInput):studio.approve(p,REVIEWER,c,'base')
    assert studio.snapshot(p)['budget']['reserved']==10000

def test_authority_bounds_and_budget(tmp_path):
    p,c=prepared(tmp_path)
    with pytest.raises(AuthorizationError):studio.submit(p,Actor(type='orchestrator',id='agent'),c,dict(id='x',version_id='base',text='x'))
    with pytest.raises(InvalidInput):studio.submit(p,REVIEWER,c,dict(id='x',version_id='base',text='x',strokes=[dict(slot=9,tool='pen',color='#000000',width=1,points=[[0,0]])]))
    studio.allocate(p,0)
    with pytest.raises(InvalidInput):studio.submit(p,REVIEWER,c,dict(id='x',version_id='base',text='x'))

def test_received_result_can_resume_without_second_send(tmp_path,monkeypatch):
    p,c=prepared(tmp_path);studio.submit(p,REVIEWER,c,dict(id='resume',version_id='base',text='Fix pose'))
    fake=Fake();original=studio.write_derived
    def interrupted(*a,**kw):raise RuntimeError('synthetic interruption after receipt')
    monkeypatch.setattr(studio,'write_derived',interrupted);studio.drain(p,fake)
    assert studio.snapshot(p,c)['feedback'][0]['state']=='failed' and fake.calls==1
    monkeypatch.setattr(studio,'write_derived',original)
    with studio.db(p) as con:
        row=studio.get(con,'feedback','resume');row['state']='queued';studio.put(con,'feedback',row,True)
    studio.drain(p,fake)
    assert fake.calls==1 and studio.snapshot(p,c)['feedback'][0]['state']=='completed'

def test_versioned_receipt_reprocessing_does_not_send_or_erase_old_take(tmp_path):
    p,c=prepared(tmp_path);studio.submit(p,REVIEWER,c,dict(id='alpha-fix',version_id='base',text='Fix pose'))
    fake=Fake();studio.drain(p,fake);before=studio.snapshot(p,c)
    studio.reprocess_received(p,'alpha-fix');studio.drain(p,fake);after=studio.snapshot(p,c)
    assert fake.calls==1 and len(after['versions'])==len(before['versions'])+1
    assert after['versions'][-1]['parent']==before['case']['current']
    assert after['case']['current'].endswith('-alpha-v3')
    assert studio.snapshot(p)['budget']['spent']==10000

def test_status_summary_exposes_work_without_feedback_payload_and_hides_superseded_failures(tmp_path):
    p,c=prepared(tmp_path)
    studio.submit(p,REVIEWER,c,dict(id='status-job',version_id='base',text='Private feedback'))
    view=studio.snapshot(p)
    assert view['work'][0]['state']=='queued'
    assert 'request' not in view['work'][0] and 'Private feedback' not in str(view['work'])
    class Timeout:
        def execute(self,*a,**kw):raise TimeoutError('lost receipt')
    studio.drain(p,Timeout())
    assert studio.snapshot(p)['work'][0]['state']=='unknown'
    assert studio.snapshot(p)['budget']['reserved']==10000
    with studio.db(p) as con:
        row=studio.get(con,'feedback','status-job');row.update(state='failed',superseded_by='new-take');studio.put(con,'feedback',row,True)
    assert studio.snapshot(p)['work']==[]

def test_bundled_frame_issues_generate_once_and_keep_native_scope_and_marks(tmp_path):
    p,c=prepared(tmp_path)
    request=dict(id='bundle',version_id='base',issues=[
        dict(id='prop',slots=[0,1],text='Keep the prop visible'),
        dict(id='foot',slots=[2],text='Keep the planted foot still')],
        strokes=[dict(slot=2,tool='pen',color='#ffaa00',width=2,points=[[1,1],[3,3]])])
    row=studio.submit(p,REVIEWER,c,request)
    assert row['quote']==10000 and studio.snapshot(p)['budget']['reserved']==10000
    assert studio.submit(p,REVIEWER,c,request)==row
    class Capture(Fake):
        def execute(self,request,**kw):
            self.payload=request
            return super().execute(request,**kw)
    fake=Capture();studio.drain(p,fake)
    view=studio.snapshot(p,c)
    assert fake.calls==1 and len(view['versions'])==2
    assert view['feedback'][0]['request']['issues']==request['issues']
    assert view['feedback'][0]['request']['strokes']==request['strokes']
    payload=fake.payload['payload']['wire']['input'][0]['content'][0]['text']
    assert 'Keep the prop visible' in payload and 'Keep the planted foot still' in payload
    assert '"slots":[0,1]' in payload and '"slots":[2]' in payload
    assert studio.snapshot(p)['budget']['spent']==10000
    with pytest.raises(S.StaleRevisionError):studio.submit(p,REVIEWER,c,dict(request,id='stale-bundle'))
    approval=studio.approve(p,REVIEWER,c,view['case']['current'])
    assert approval['source']=='human'
    handoff=json.loads((Path(approval['handoff_path'])/'handoff.json').read_text())
    assert handoff['feedback'][0]['request']['issues']==request['issues']
    assert handoff['feedback'][0]['request']['strokes']==request['strokes']
    assert len(handoff['provider_attempts'])==1

@pytest.mark.parametrize('issues',[
    [dict(id='x',slots=[9],text='Out of bounds')],
    [dict(id='x',slots=[0,0],text='Duplicate frames')],
    [dict(id='x',slots=[],text='No frames')],
    [dict(id='x',slots=[-1],text='Negative frame')],
    [dict(id='x',slots=[True],text='Boolean frame')],
    [dict(id='x',slots=[0],text=' ')],
    [dict(id='x',slots=[0],text='one'),dict(id='x',slots=[1],text='two')],
    [dict(id='x',slots=[0],text='x'*8000),dict(id='y',slots=[1],text='y')],
])
def test_invalid_bundles_reserve_nothing(tmp_path,issues):
    from pydantic import ValidationError
    p,c=prepared(tmp_path)
    with pytest.raises((InvalidInput,ValidationError)):
        studio.submit(p,REVIEWER,c,dict(id='bad-bundle',version_id='base',issues=issues))
    assert studio.snapshot(p)['budget']['reserved']==0
    assert studio.snapshot(p,c)['feedback']==[]

def test_legacy_feedback_idempotence_after_bundle_schema_addition(tmp_path):
    p,c=prepared(tmp_path);request=dict(id='legacy',version_id='base',text='Fix pose')
    row=studio.submit(p,REVIEWER,c,request)
    with studio.db(p) as con:
        row['request'].pop('issues');studio.put(con,'feedback',row,True)
    assert studio.submit(p,REVIEWER,c,request)==row
    assert studio.snapshot(p)['budget']['reserved']==10000

def test_review_reason_is_bound_to_each_take_and_does_not_inherit_parent_checks(tmp_path):
    p,c=prepared(tmp_path)
    baseline=studio.snapshot(p,c)
    assert baseline['case']['review']['technical_status']=='pass'
    assert baseline['case']['review']['kind']=='first_review'
    studio.submit(p,REVIEWER,c,dict(id='review-reasons',version_id='base',issues=[dict(id='boot',slots=[1,2],text='Fix the boots')]))
    studio.drain(p,Fake());view=studio.snapshot(p,c);current=view['versions'][-1]
    assert current['review']['version_id']==current['id']
    assert current['review']['technical_status']=='not_run' and current['review']['findings']==[]
    assert current['review']['kind']=='correction_review'
    assert current['review']['prior_issues']==[dict(id='boot',slots=[1,2],text='Fix the boots')]
    assert current['review']['feedback_baseline']=='base'
    assert view['versions'][0]['review']['technical_status']=='pass'
    assert studio.snapshot(p)['cases'][0]['review']==view['case']['review']
    studio.approve(p,REVIEWER,c,current['id'])
    approved=studio.snapshot(p,c)
    assert approved['case']['review']['kind']=='approved'
    assert approved['versions'][0]['review']['kind']=='first_review'


def test_replacement_explains_first_review_without_fabricating_findings():
    case=dict(reason='Isolated 2D replacement · review requested')
    version=dict(id='new',parent='old',intake=dict(eligible=True))
    parent_evaluation=dict(id='evaluation:old',revision_id='old',results=[dict(outcome='fail')])
    context=studio.review_context(case,version,parent_evaluation,[],[])
    assert context['kind']=='unassessed' and context['technical_status']=='not_run'
    assert context['findings']==[] and context['evaluation_id'] is None
    assert 'have not run' in context['summary'] and 'Human approval' in context['summary']


def test_review_reason_shows_failed_frames_measurements_and_coverage_gaps(tmp_path):
    from test_agent_loop import import_frames
    p,_,_=setup(tmp_path);bad=import_frames(tmp_path,'faulty',{'kind':'flicker'})
    loop.submit(p,'run','faulty',bad);c=studio.seed(p,'faulty')
    context=studio.snapshot(p,c)['case']['review']
    assert context['kind']=='findings' and context['evaluation_id']=='evaluation:faulty'
    finding=next(f for f in context['findings'] if f['check_id']=='appearance-1')
    assert finding['outcome']=='fail' and finding['slots']==[1]
    assert finding['observed'] is not None and finding['expected'] is not None
    assert finding['source']=='procedural'
    assert 'Appearance' in context['label'] and 'Frames 2.' in context['summary']
    v=dict(id='partial',intake=dict(eligible=True))
    e=dict(id='evaluation:partial',revision_id='partial',technical_status='error',coverage='partial',results=[
        dict(id='missing',family='media',slots=[2],reason='Decode failed',outcome='error',source='deterministic'),
        dict(id='gap',family='feature',slots=[1],reason='Feature not measured',outcome='unmeasured',source='deterministic')])
    context=studio.review_context({},v,e,[],[])
    assert context['kind']=='findings' and len(context['findings'])==2
    assert 'errors' in context['label'] and 'unmeasured' in context['label']


def test_review_reason_retains_exclusion_instead_of_calling_it_an_animation_defect():
    v=dict(id='excluded',intake=dict(eligible=False,frames=[dict(reasons=['background_present'])]))
    context=studio.review_context({},v,None,[],[])
    assert context['kind']=='excluded' and context['intake_reasons']==['background_present']
    assert context['technical_status']=='not_run' and context['findings']==[]


def test_replacement_without_findings_is_browsable_without_an_intervention(tmp_path):
    from framebound.v2.services.assets import import_asset
    from framebound.v3.services import desk
    p,_,_=setup(tmp_path)
    matte=tmp_path/'matte.png';Image.new('RGBA',(8,8),'white').save(matte)
    import_asset(p,str(matte),'matte',source_kind='procedural')
    loop.submit(p,'run','excluded',['matte']*3)
    c=studio.seed(p,'excluded');studio.allocate(p,100000)
    assert studio.snapshot(p,c)['case']['needs_intervention']
    assert desk.snapshot(p)['runs'][0]['needs_intervention']
    studio.replace(p,REVIEWER,c,dict(id='new-isolated',version_id='excluded',category='character',description='A walking blue sprite'))
    studio.drain(p,Fake())
    view=studio.snapshot(p,c)
    assert view['case']['status']=='review' and view['case']['review']['kind']=='unassessed'
    assert not view['case']['needs_intervention']
    assert not studio.snapshot(p)['cases'][0]['needs_intervention']
    run=desk.snapshot(p)['runs'][0]
    assert not run['needs_intervention']
    assert run['current_revision_id']=='excluded'  # Frozen source history is intact.
    assert desk.revision(p,'excluded')['evaluation']['technical_status']=='fail'
    assert view['versions'][0]['review']['needs_intervention']
    assert view['case']['current']!=view['versions'][0]['id']
    studio.submit(p,REVIEWER,c,dict(id='human-issue',version_id=view['case']['current'],text='Correct the boots'))
    assert studio.snapshot(p,c)['case']['needs_intervention']
    assert desk.snapshot(p)['runs'][0]['needs_intervention']
    studio.drain(p,Fake())
    view=studio.snapshot(p,c)
    assert view['case']['review']['kind']=='correction_review' and view['case']['needs_intervention']
    studio.approve(p,REVIEWER,c,view['case']['current'])
    assert not studio.snapshot(p,c)['case']['needs_intervention']
    assert not desk.snapshot(p)['runs'][0]['needs_intervention']


def test_unknown_feedback_acceptance_stays_actionable_and_reserved(tmp_path):
    p,c=prepared(tmp_path)
    assert not studio.snapshot(p,c)['case']['needs_intervention']
    studio.submit(p,REVIEWER,c,dict(id='attention-unknown',version_id='base',text='Correct the hand'))
    class Timeout:
        def execute(self,*a,**kw):raise TimeoutError('lost response')
    studio.drain(p,Timeout())
    assert studio.snapshot(p,c)['case']['needs_intervention']
    before=studio.snapshot(p)['budget'];fake=Fake();studio.drain(p,fake)
    assert not fake.calls and studio.snapshot(p)['budget']==before
    assert before['reserved']==10000
