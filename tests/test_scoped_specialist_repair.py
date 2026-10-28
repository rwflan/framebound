"""Actual scoped specialist repair through the durable controller (strict fake upstream)."""
import base64
import io
import json
from PIL import Image,ImageDraw
import pytest
from framebound.v2 import storage as S
from framebound.v2.services import auto_repair as A,jobs as J,orchestrator as O
from framebound.v2.services.errors import InvalidInput
from test_public_creation import public_project,cli


def setup_redraw(root,monkeypatch):
    p,client,headers,contract=public_project(root,monkeypatch)
    guide=client.get('/api/references').json()['motion_guides'][0];guide['id']='specialist-guide'
    editable=Image.new('L',(64,64));ImageDraw.Draw(editable).rectangle((25,16,39,45),fill=255)
    protected=Image.new('L',(64,64));protected.putpixel((0,0),255)
    for aid,image in [('editable',editable),('protected',protected)]:
        image.save(root/(aid+'.png'));cli(p,'asset-import','--src',str(root/(aid+'.png')),'--asset-id',aid)
    guide['repair_policy']={'operators':['scoped_redraw'],'generation_allowed':True,'max_provider_dispatches':1}
    for entry in guide['entries']:entry.update(editable_mask_asset_id='editable',protected_mask_asset_id='protected')
    path=root/'guide-specialist.json';path.write_text(json.dumps(guide));cli(p,'guide-propose','--guide',str(path))
    assert client.post('/api/references/approve',json={'character_revision_id':'char','motion_guide_id':guide['id']},headers=headers).status_code==200
    contract['id']='specialist-contract';contract['references']['motion_guide_revision']=guide['id']
    contract['constraints'] += [{'id':'palette-target','check':'appearance_palette','required':True,'params':{'max_drift':0.001}},
                                {'id':'scope-target','check':'repair_protection','required':True}]
    path=root/'contract-specialist.json';path.write_text(json.dumps(contract));cli(p,'contract-propose','--contract',str(path))
    intended=Image.open(root/'pose0.png').convert('RGBA');fault=intended.copy();ImageDraw.Draw(fault).rectangle((29,20,35,30),fill=(1,255,2,255))
    fault.save(root/'palette-fault.png');cli(p,'asset-import','--src',str(root/'palette-fault.png'),'--asset-id','palette-fault')
    cli(p,'clip-create','--contract-id',contract['id'],'--revision-id','palette-faulty','--frames','palette-fault,pose1','--phases','p0,p1')
    assert cli(p,'clip-evaluate','--revision-id','palette-faulty')['technical_status']=='fail'
    return str(p),intended,editable,protected


def dispatch(project,jid,transport):
    run=O.start_run(project,[jid]);step=O.run_once(project,run['run_id'],worker_id='test-specialist')
    assert step['action']=='send_ready',step
    return O.orchestrator_send(project,run['run_id'],jid,worker_id='test-specialist',fencing_token=step['fencing_token'],transport=transport)


def test_provider_receives_actual_controls_and_framework_composites_then_rechecks(tmp_path,monkeypatch):
    p,intended,editable,protected=setup_redraw(tmp_path,monkeypatch)
    monkeypatch.setenv('MODEL_API_KEY','test-not-a-live-key')
    start=A.start_run(p,'palette-faulty','specialist',offline=False)
    waiting=A.step_run(p,start['run_id']);assert waiting['status']=='awaiting_provider',waiting
    assert waiting['local_attempts_used']==1
    job=J.job_get(p,waiting['job_id'])['job'];oid=waiting['operation_id']
    with pytest.raises(InvalidInput,match='stale|foreign|authority'):
        J.submit_generation(p,{k:v for k,v in job['request_brief'].items() if not k.startswith('_frozen_')},[],'different-key')
    seen=[]
    def strict_fake(request):
        body=request['body'];blobs=[c for m in body['input'] for c in m['content'] if c['type']=='input_image']
        assert len(blobs)==6
        decoded=[base64.b64decode(c['image_url'].split(',',1)[1]) for c in blobs]
        assert (tmp_path/'editable.png').read_bytes() in decoded
        assert (tmp_path/'protected.png').read_bytes() in decoded
        assert (tmp_path/'palette-fault.png').read_bytes() in decoded
        seen.append(request)
        # Upstream changes the WHOLE exterior to an arbitrary color. The
        # framework must restore it and retain only permitted corrected pixels.
        output=Image.new('RGBA',(64,64),(90,0,250,255))
        output.paste(intended,(0,0),editable)
        buf=io.BytesIO();output.save(buf,format='PNG')
        return {'status':'completed','id':'test-response','output':[{'type':'image_generation_call','id':'test-image','result':base64.b64encode(buf.getvalue()).decode()}]}
    assert dispatch(p,waiting['job_id'],strict_fake)['action']=='succeeded'
    resumed=A.step_run(p,start['run_id']);assert resumed['internal_progress'] is True,resumed
    ready=A.step_run(p,start['run_id']);assert ready['status']=='technically_ready',ready
    assert len(seen)==1
    con=S.connect(p)
    try:
        rev=S.get(con,'clip_revisions',ready['revision_id'])[0]
        frame=S.get(con,'frame_instances',rev['frame_instance_ids'][0])[0]
        asset=S.get(con,'assets',frame['asset_id'])[0]
        assert Image.open(S.blob_path(p,asset['byte_sha256'])).convert('RGBA').tobytes()==intended.tobytes()
        assert asset['origin']=='simulated-transport' and asset['operation_id']==oid
        assert S.get(con,'assets',J.job_get(p,waiting['job_id'])['job']['output_asset_ids'][0])[0]['parent_asset_ids']
    finally:con.close()
    assert A.step_run(p,start['run_id'])==ready


def test_queued_offline_repair_cannot_be_flipped_by_new_start_settings(tmp_path,monkeypatch):
    p,_,_,_=setup_redraw(tmp_path,monkeypatch)
    start=A.start_run(p,'palette-faulty','offline')
    waiting=A.step_run(p,start['run_id']);job=J.job_get(p,waiting['job_id'])['job']
    assert job['offline'] is True
    with pytest.raises(S.ConflictError):A.start_run(p,'palette-faulty','offline',offline=False)


def test_renamed_contract_does_not_replenish_approved_reference_grant(tmp_path,monkeypatch):
    from test_automatic_execution import setup_work
    p,_,_,contract,_=setup_work(tmp_path,monkeypatch,attempts=1)
    assert A.run_automatic(str(p),'faulty','first')['status']=='technically_ready'
    contract['id']='renamed-same-authority'
    path=tmp_path/'renamed.json';path.write_text(json.dumps(contract));cli(p,'contract-propose','--contract',str(path))
    cli(p,'clip-create','--contract-id',contract['id'],'--revision-id','renamed-fault','--frames','fault,pose1','--phases','p0,p1')
    refused=A.run_automatic(str(p),'renamed-fault','another-key')
    assert refused['status']=='blocked' and 'grant exhausted' in refused['blocker']
