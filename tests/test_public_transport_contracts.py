"""Strict consuming boundaries for the new work, grants and portable pending data."""
import json
from PIL import Image
import pytest
from framebound.v2 import domain as D,storage as S
from framebound.v2.exports import build_snapshot,validate_snapshot
from framebound.v2.services import auto_repair as A,masks as M
from test_public_creation import public_project,cli
from test_scoped_specialist_repair import setup_redraw


def test_new_http_contracts_are_strict_and_operator_mutations_stay_separate(tmp_path,monkeypatch):
    project,client,headers,_=public_project(tmp_path,monkeypatch)
    assert client.post('/api/animation/runs',json={'revision_id':'base','offline':'false'}).status_code==422
    assert client.post('/api/animation/runs',json={'revision_id':'base','extra':'ignored?'}).status_code==422
    assert client.post('/api/jobs',json={'brief':{},'idempotency_key':'bad','offline':'false'}).status_code==422
    proposal={'id':'budget','targets':['contract#slot-0'],'models':['muse-image-1.0'],'max_dispatches':1}
    assert client.post('/api/provider-grants',json=proposal).status_code==403
    operator={'X-Operator-Secret':'test-operator'}
    created=client.post('/api/provider-grants',json=proposal,headers=operator)
    assert created.status_code==201,created.text
    view=client.get('/api/provider-grants/budget');assert view.status_code==200
    assert view.json()['grant']['dispatches_reserved']==0
    assert client.post('/api/provider-grants/budget/revoke',json={'expected_version':True},headers=operator).status_code==422
    revoked=client.post('/api/provider-grants/budget/revoke',json={'expected_version':view.json()['version']},headers=operator)
    assert revoked.status_code==200 and revoked.json()['active'] is False
    missing=client.get('/api/eligibility/does-not-exist')
    assert missing.status_code==422 and missing.json()['code']=='invalid_input'


def test_automatic_policy_cannot_drop_its_required_pixel_guard(tmp_path,monkeypatch):
    from framebound.v2.services.contracts import propose_contract
    from framebound.v2.services.errors import InvalidInput
    from test_automatic_execution import setup_work
    project,_,_,contract,_=setup_work(tmp_path,monkeypatch)
    contract['id']='omitted-protection';contract['constraints']=[c for c in contract['constraints'] if c['check']!='repair_protection']
    with pytest.raises(InvalidInput,match='mandatory repair_protection'):propose_contract(str(project),contract)


def test_pending_scoped_work_exports_its_actual_operation_and_job_without_output_claim(tmp_path,monkeypatch):
    project,_,_,_=setup_redraw(tmp_path,monkeypatch)
    run=A.start_run(project,'palette-faulty','pending-export');pending=A.step_run(project,run['run_id'])
    assert pending['status']=='awaiting_provider'
    out=tmp_path/'pending-snapshot';manifest=build_snapshot(project,'pending',['palette-faulty'],str(out))
    assert manifest['counts']['positives']==0
    operations=[json.loads(line) for line in (out/'closure'/'operations.jsonl').read_text().splitlines()]
    jobs=[json.loads(line) for line in (out/'closure'/'jobs.jsonl').read_text().splitlines()]
    assert len(operations)==len(jobs)==1
    assert operations[0]['status']=='awaiting_provider' and jobs[0]['offline'] is True
    assert jobs[0]['output_asset_ids']==[] and jobs[0]['dispatch_count']==0
    assert validate_snapshot(str(out))['ok']


def test_transparent_hidden_rgb_cannot_expand_a_reviewed_edit_mask(tmp_path,monkeypatch):
    project,client,headers,_=public_project(tmp_path,monkeypatch)
    cli(project,'clip-evaluate','--revision-id','base')
    issue=client.post('/api/issues',json={'clip_revision_id':'base','frame_range':[0,3],
        'roi':{'left':0,'top':0,'right':1,'bottom':1},'note':'test input'},headers=headers)
    assert issue.status_code==201,issue.text
    issue=issue.json();taskid=issue['task_id']
    path=tmp_path/'invisible-white.png';Image.new('RGBA',(64,64),(255,255,255,0)).save(path)
    cli(project,'asset-import','--src',str(path),'--asset-id','invisible-mask')
    con=S.connect(project)
    try:eventid=S.get(con,'correction_tasks',taskid)[0]['source_issue_event_id']
    finally:con.close()
    response=client.post('/api/masks',json={'issue_event_id':eventid,'mask_asset_id':'invisible-mask','covered_slots':[0]},headers=headers)
    assert response.status_code==201,response.text
    con=S.connect(project)
    try:task=D.CorrectionTask.model_validate(S.get(con,'correction_tasks',taskid)[0])
    finally:con.close()
    region=M.allowed_region(str(project),task,0)
    assert region[0]==1 and sum(region)==1


def test_operator_receipt_roundtrips_through_the_typed_http_boundary(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from framebound.v2.api.app import create_app
    from framebound.v2.services import jobs as J
    from test_v2_r3_providers import _seed
    from test_provider_recovery import uncertain,receipt
    from test_dispatch_reservations import response
    project=str(tmp_path/'receipt-project');brief=_seed(project)['brief']
    ids,pending=uncertain(project,brief,monkeypatch)
    client=TestClient(create_app(project));body=receipt(pending,provider_response=response(project))
    url=f'/api/jobs/{ids[1]}/operator-reconcile'
    assert client.post(url,json=body).status_code==403
    result=client.post(url,json=body,headers={'X-Operator-Secret':'operator-test'})
    assert result.status_code==200,result.text
    assert result.json()['status']=='succeeded'
    assert client.post(url,json=body,headers={'X-Operator-Secret':'operator-test'}).json()==result.json()
    assert J.job_get(project,ids[1])['job']['dispatch_count']==1
