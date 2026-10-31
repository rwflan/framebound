import base64,io
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
