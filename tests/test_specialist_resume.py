"""Pending specialist work resumes its paid stages without an internal critic."""
import base64
import json
import subprocess
import sys
from pathlib import Path
import pytest
from framebound.v2 import recorded_run as RR,storage as S
from framebound.v2.services import jobs as J
from test_public_creation import public_project
from test_v2_r3_providers import _pack_bits,_sam_line


def test_pending_bundle_resumes_preserved_generation_and_never_resends_paid_stage(tmp_path,monkeypatch):
    project,_,_,_=public_project(tmp_path,monkeypatch)
    monkeypatch.delenv('MODEL_API_KEY',raising=False);monkeypatch.delenv('META_API_KEY',raising=False)
    out=tmp_path/'bundle.json'
    arguments=dict(contract_id='contract',slot=0,baseline_revision_id='base',new_revision_id='specialist-result',offline=False,idempotency_key='persistent')
    pending=RR.run_recorded(str(project),str(out),**arguments)
    assert pending['status']=='blocked'
    monkeypatch.setenv('MODEL_API_KEY','test-not-live')
    calls=[]
    def fake(request):
        body=request['body'];calls.append(body['model'])
        if body['model']=='sam-3.1':
            raster=bytes(1 if 2<=i%64<6 and 2<=i//64<6 else 0 for i in range(4096))
            text=_sam_line(0,[(0,(2,2,6,6,64,64),(64,64,'~',base64.b85encode(_pack_bits(raster)).decode()))])
            return {'status':'completed','id':'test-sam','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}
        return {'status':'completed','id':'test-image-'+str(len(calls)),'output':[{'type':'image_generation_call','id':'test-image','result':base64.b64encode((tmp_path/'pose0.png').read_bytes()).decode()}]}
    original=RR._native_output
    def interrupted(*args,**kwargs):raise RuntimeError('test process boundary after paid response')
    monkeypatch.setattr(RR,'_native_output',interrupted)
    with pytest.raises(RuntimeError,match='after paid response'):RR.run_recorded(str(project),str(out),transport=fake,**arguments)
    assert calls==['muse-image-1.0']
    monkeypatch.setattr(RR,'_native_output',original)
    result=RR.run_recorded(str(project),str(out),transport=fake,**arguments)
    assert result['status']=='recorded',result
    assert calls==['muse-image-1.0','muse-image-1.0','sam-3.1']
    assert {cap['capability'] for cap in result['capabilities']}=={'image-generation','image-edit','sam-segmentation'}
    assert result['origin']=='provider-simulated' and result['acceptance']=='unreviewed'
    assert RR.run_recorded(str(project),str(out),transport=fake,**arguments)==result
    assert len(calls)==3
    history=list(out.with_name(out.name+'.history').glob('*.json'))
    assert any(json.loads(path.read_text())['status']=='blocked' for path in history)


def test_explicit_offline_workflow_needs_new_identity_for_live_queueing(tmp_path,monkeypatch):
    project,_,_,_=public_project(tmp_path,monkeypatch);out=tmp_path/'bundle.json'
    arguments=dict(contract_id='contract',slot=0,baseline_revision_id='base',new_revision_id='new',idempotency_key='offline')
    assert RR.run_recorded(str(project),str(out),offline=True,**arguments)['status']=='blocked'
    with pytest.raises(S.ConflictError,match='offline workflow'):
        RR.run_recorded(str(project),str(out),offline=False,**arguments)


def test_live_config_is_persistent_and_never_seeds_or_approves_project(tmp_path):
    work=tmp_path/'participant'
    script=str(Path(__file__).resolve().parents[1]/'scripts'/'live_spike.py')
    first=subprocess.run([sys.executable,script,str(work)],capture_output=True,text=True)
    assert first.returncode==3 and 'PENDING' in first.stdout
    configuration=(work/'live-config.json').read_bytes()
    second=subprocess.run([sys.executable,script,str(work)],capture_output=True,text=True)
    assert second.returncode==3
    assert (work/'live-config.json').read_bytes()==configuration
    assert not list(work.rglob('framebound.sqlite3'))


def test_edit_cannot_reference_unrecorded_or_foreign_provider_response(tmp_path,monkeypatch):
    from framebound.v2.services.errors import InvalidInput
    from framebound.v2.services.briefs import compile_reference_brief
    project,_,_,_=public_project(tmp_path,monkeypatch)
    brief=compile_reference_brief(str(project),'contract',0)['brief']
    with pytest.raises(InvalidInput,match='durable successful response'):
        J.submit_generation(str(project),brief,[],'invented-edit',provider_settings={'previous_response_id':'invented-response'})
