"""Actual public native repair, independent pixels and real process crash recovery."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from PIL import Image
import pytest
from framebound.v2 import domain as D,storage as S
from framebound.v2.services import auto_repair as A
from framebound.v2.services.errors import InvalidInput
from test_public_creation import public_project,cli


def setup_work(root,monkeypatch,operator='protected_restore',color=(230,80,30),width=12,attempts=3):
    project,client,headers,contract=public_project(root,monkeypatch,color,width)
    guide=client.get('/api/references').json()['motion_guides'][0]
    guide['id']='automatic-guide'
    mask=Image.new('L',(64,64),255 if operator=='translate' else 0)
    mask.save(root/'allowed.png')
    cli(project,'asset-import','--src',str(root/'allowed.png'),'--asset-id','allowed')
    guide['repair_policy']={'operators':[operator],'translation_budget_px':2,'max_local_attempts':attempts,'max_compute_steps':8}
    for entry in guide['entries']:entry['editable_mask_asset_id']='allowed'
    path=root/'automatic-guide.json';path.write_text(json.dumps(guide));cli(project,'guide-propose','--guide',str(path))
    response=client.post('/api/references/approve',json={'character_revision_id':'char','motion_guide_id':guide['id']},headers=headers)
    assert response.status_code==200,response.text
    contract['id']='automatic-contract';contract['references']['motion_guide_revision']=guide['id']
    contract['constraints']=[{'id':'anchor-check','check':'native_registration','required':True,'params':{'max_anchor_drift_px':0.25}},
                             {'id':'fixed-scope','check':'repair_protection','required':True}]
    # For restore, a tiny exterior pixel may move centroid slightly; it is a scope fault.
    if operator=='protected_restore':contract['constraints'][0]['params']={}
    path=root/'automatic-contract.json';path.write_text(json.dumps(contract));cli(project,'contract-propose','--contract',str(path))
    src=Image.open(root/'pose0.png').convert('RGBA')
    if operator=='translate':
        fault=Image.new('RGBA',src.size);fault.alpha_composite(src,(1,0))
    else:
        fault=src.copy();fault.putpixel((0,0),(251,5,19,255))
    fault.save(root/'fault.png');cli(project,'asset-import','--src',str(root/'fault.png'),'--asset-id','fault')
    cli(project,'clip-create','--contract-id',contract['id'],'--revision-id','faulty','--frames','fault,pose1','--phases','p0,p1')
    return project,client,headers,contract,src


@pytest.mark.parametrize('operator,color,width', [('protected_restore',(230,80,30),12),('translate',(60,190,90),20)])
def test_public_work_executes_pixels_and_replays_without_provider_or_human_issues(tmp_path,monkeypatch,operator,color,width):
    p,client,headers,contract,expected=setup_work(tmp_path,monkeypatch,operator,color,width)
    before=cli(p,'clip-evaluate','--revision-id','faulty');assert before['technical_status']=='fail'
    calls=[]
    def forbidden(*a,**kw):calls.append(1);raise AssertionError('automatic deterministic work attempted network')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    result=A.run_automatic(str(p),'faulty','public-work')
    assert result['status']=='technically_ready',result
    assert result['local_attempts_used']==1 and result['compute_steps_used']==1
    assert result['revision_id']!='faulty' and result['acceptance']=='unreviewed'
    assert calls==[]
    replay=cli(p,'animation-run','--revision-id','faulty','--idempotency-key','public-work')
    assert replay==result
    con=S.connect(p)
    try:
        rev=S.get(con,'clip_revisions',result['revision_id'])[0]
        frame=S.get(con,'frame_instances',rev['frame_instance_ids'][0])[0]
        asset=S.get(con,'assets',frame['asset_id'])[0]
        assert Image.open(S.blob_path(p,asset['byte_sha256'])).convert('RGBA').tobytes()==expected.tobytes()
        assert asset['operation_id']==result['operation_ids'][0] and 'fault' in asset['parent_asset_ids']
        unchanged=S.get(con,'frame_instances',rev['frame_instance_ids'][1])[0]
        assert unchanged['asset_id']=='pose1'
        events=[json.loads(r['data']) for r in con.execute('SELECT data FROM review_events')]
        assert len([e for e in events if e['action']=='machine_fault'])==1
        assert not [e for e in events if e['action'] in ('mark_issue','approve','resolve_issue')]
        assert con.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM correction_tasks').fetchone()[0]==1
    finally:con.close()
    assert cli(p,'clip-evaluate','--revision-id',result['revision_id'])['technical_status']=='pass'


@pytest.mark.parametrize('barrier',['reserved','rendered','evaluated','committed'])
def test_worker_process_death_resumes_same_attempt_without_duplicate_tasks(tmp_path,monkeypatch,barrier):
    p,_,_,_,expected=setup_work(tmp_path,monkeypatch)
    work=cli(p,'animation-start','--revision-id','faulty','--idempotency-key','crash')
    script="""import os,sys
from framebound.v2.services import auto_repair as A
def crash(stage):
 if stage==sys.argv[3]:os._exit(77)
A._checkpoint=crash
A.step_run(sys.argv[1],sys.argv[2])
"""
    process=subprocess.run([sys.executable,'-c',script,str(p),work['run_id'],barrier],capture_output=True,text=True)
    assert process.returncode==77,process.stderr
    result=cli(p,'animation-run','--revision-id','faulty','--idempotency-key','crash')
    assert result['status']=='technically_ready',result
    assert result['local_attempts_used']==1
    con=S.connect(p)
    try:
        assert con.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM correction_tasks').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM review_packets').fetchone()[0]==1
    finally:con.close()


def test_caller_budget_mask_or_new_key_cannot_authorize_or_reset(tmp_path,monkeypatch):
    p,client,headers,contract,_=setup_work(tmp_path,monkeypatch,attempts=1)
    with pytest.raises(InvalidInput,match='authorized operation'):
        A.execute_translate(str(p),'fault',1,0,'unauthorized',budget_px=10000)
    with pytest.raises(InvalidInput,match='authorized operation'):
        A.execute_protected_restore(str(p),'pose0','fault',bytes([1])*4096,'unauthorized')
    result=A.run_automatic(str(p),'faulty','first');assert result['status']=='technically_ready'
    again=A.run_automatic(str(p),'faulty','new-key')
    assert again['status']=='blocked' and 'grant exhausted' in again['blocker']
    contract['id']='widened';contract['repair_policy']={'operators':['translate'],'translation_budget_px':32}
    path=tmp_path/'widened.json';path.write_text(json.dumps(contract));cli(p,'contract-propose','--contract',str(path))
    with pytest.raises(InvalidInput,match='widen'):A.compile_plan(str(p),'widened')


def test_wrong_native_size_is_precise_blocker_not_scaled_or_success(tmp_path,monkeypatch):
    p,_,_,contract,_=setup_work(tmp_path,monkeypatch,'translate')
    Image.new('RGBA',(32,32),(255,0,0,255)).save(tmp_path/'wrong.png')
    cli(p,'asset-import','--src',str(tmp_path/'wrong.png'),'--asset-id','wrong')
    cli(p,'clip-create','--contract-id',contract['id'],'--revision-id','wrong-size','--frames','wrong,pose1','--phases','p0,p1')
    result=A.run_automatic(str(p),'wrong-size')
    assert result['status']=='blocked' and result['local_attempts_used']==0


def test_two_faults_retain_measured_internal_progress_before_ready(tmp_path,monkeypatch):
    p,_,_,contract,_=setup_work(tmp_path,monkeypatch,'translate')
    src=Image.open(tmp_path/'pose1.png').convert('RGBA');fault=Image.new('RGBA',src.size);fault.alpha_composite(src,(-1,0))
    fault.save(tmp_path/'fault2.png');cli(p,'asset-import','--src',str(tmp_path/'fault2.png'),'--asset-id','fault2')
    cli(p,'clip-create','--contract-id',contract['id'],'--revision-id','two-faults','--frames','fault,fault2','--phases','p0,p1')
    run=cli(p,'animation-start','--revision-id','two-faults')
    first=cli(p,'animation-step','--run-id',run['run_id'])
    assert first['status']=='running' and first['internal_progress'] is True
    con=S.connect(p)
    try:assert con.execute('SELECT count(*) FROM review_packets').fetchone()[0]==0
    finally:con.close()
    final=cli(p,'animation-run','--revision-id','two-faults')
    assert final['status']=='technically_ready' and final['local_attempts_used']==2


def test_approved_family_calibration_uses_same_crop_for_every_pose(tmp_path,monkeypatch):
    p,client,headers,contract,expected=setup_work(tmp_path,monkeypatch)
    guide=next(g for g in client.get('/api/references').json()['motion_guides'] if g['id']=='automatic-guide')
    guide['id']='calibrated';guide['source_calibration']={'source_width':128,'source_height':128,'crop':[0,0,128,128]}
    path=tmp_path/'calibrated.json';path.write_text(json.dumps(guide));cli(p,'guide-propose','--guide',str(path))
    assert client.post('/api/references/approve',json={'character_revision_id':'char','motion_guide_id':'calibrated'},headers=headers).status_code==200
    contract['id']='calibrated-contract';contract['references']['motion_guide_revision']='calibrated'
    path=tmp_path/'calibrated-contract.json';path.write_text(json.dumps(contract));cli(p,'contract-propose','--contract',str(path))
    for index in range(2):
        expected=Image.open(tmp_path/f'pose{index}.png').convert('RGBA')
        expected.resize((128,128),Image.Resampling.NEAREST).save(tmp_path/f'large{index}.png')
        cli(p,'asset-import','--src',str(tmp_path/f'large{index}.png'),'--asset-id',f'large{index}')
        result=cli(p,'source-calibrate','--contract-id','calibrated-contract','--source-asset-id',f'large{index}','--output-asset-id',f'native{index}')
        assert result['parent_asset_ids']==[f'large{index}']
        assert Image.open(S.blob_path(p,result['byte_sha256'])).convert('RGBA').tobytes()==expected.tobytes()
