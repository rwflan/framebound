import base64
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import multiprocessing
import pytest
from framebound.v2 import storage as S
from framebound.v2.services import jobs as J,orchestrator as O
from framebound.v2.services.errors import InvalidInput
from test_v2_r3_providers import _seed

def setup(project,key,brief,run_id=None):
    jid=J.submit_generation(project,brief,[],key).artifacts[0]['id']
    rid=run_id or O.start_run(project,[jid])['run_id']
    claim=J.job_claim(project,jid,'worker',expected_version=J.job_get(project,jid)['version'])
    return rid,jid,claim

def response(project):
    con=S.connect(project)
    try:raw=S.blob_path(project,S.get(con,'assets','f0')[0]['byte_sha256']).read_bytes()
    finally:con.close()
    return {'status':'completed','id':'fixture-response','output':[{'type':'image_generation_call','id':'fixture-image','result':base64.b64encode(raw).decode()}]}

def send(project,ids,transport):
    rid,jid,claim=ids
    return O.orchestrator_send(project,rid,jid,worker_id='worker',fencing_token=claim['fencing_token'],transport=transport)


def _held_process_send(project,ids,entered,release,results):
    import os
    os.environ['MODEL_API_KEY']='test-no-network'
    def fake(req):
        entered.set()
        if not release.wait(15):raise AssertionError('test process release timeout')
        return response(project)
    try:results.put(send(project,ids,fake))
    except Exception as exc:results.put({'error':repr(exc)})


def test_same_claim_is_exclusive_across_processes(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    ids=setup(p,'process-claim',brief);ctx=multiprocessing.get_context('spawn')
    entered=ctx.Event();release=ctx.Event();results=ctx.Queue()
    worker=ctx.Process(target=_held_process_send,args=(p,ids,entered,release,results));worker.start()
    calls=[]
    try:
        assert entered.wait(15)
        with pytest.raises(InvalidInput,match='in flight'):send(p,ids,lambda req:calls.append(1))
    finally:release.set()
    result=results.get(timeout=15);worker.join(15)
    if worker.is_alive():worker.terminate();worker.join();pytest.fail('held worker did not terminate')
    assert result['action']=='succeeded',result
    assert calls==[] and J.job_get(p,ids[1])['job']['dispatch_count']==1

def test_same_valid_claim_cannot_dispatch_twice_while_first_is_in_transport(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    ids=setup(p,'same-claim',brief);entered=threading.Event();release=threading.Event();calls=[]
    def first(req):
        calls.append('first');entered.set();assert release.wait(10);return response(p)
    def second(req):calls.append('second');return response(p)
    with ThreadPoolExecutor(2) as pool:
        running=pool.submit(send,p,ids,first)
        assert entered.wait(10)
        try:
            with pytest.raises(InvalidInput,match='in flight'):send(p,ids,second)
        finally:release.set()
        assert running.result()['action']=='succeeded'
    assert calls==['first']
    assert J.job_get(p,ids[1])['job']['dispatch_count']==1

def test_two_claimed_jobs_share_one_reserved_run_unit(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    jobs=[J.submit_generation(p,brief,[],f'job-{i}').artifacts[0]['id'] for i in range(2)]
    rid=O.start_run(p,jobs,max_attempts=1)['run_id']
    ids=[(rid,j,J.job_claim(p,j,'worker',expected_version=J.job_get(p,j)['version'])) for j in jobs]
    entered=threading.Event();release=threading.Event();calls=[]
    def first(req):calls.append(0);entered.set();assert release.wait(10);return response(p)
    with ThreadPoolExecutor(2) as pool:
        running=pool.submit(send,p,ids[0],first);assert entered.wait(10)
        try:
            with pytest.raises(InvalidInput,match='ceiling'):send(p,ids[1],lambda req:calls.append(1))
        finally:release.set()
        assert running.result()['action']=='succeeded'
    assert calls==[0]
    con=S.connect(p)
    try:assert S.get(con,'runs',rid)[0]['attempts_used']==1
    finally:con.close()

def test_target_units_count_sends_once_and_new_keys_cannot_reset(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network');calls=[]
    for i in range(4):
        ids=setup(p,f'key-{i}',brief)
        def fake(req):calls.append(i);return response(p)
        if i<3:assert send(p,ids,fake)['action']=='succeeded'
        else:
            with pytest.raises(InvalidInput,match='target attempt ceiling'):send(p,ids,fake)
    assert calls==[0,1,2]

@pytest.mark.parametrize('cap',['usd-0','NaN','Infinity','-1'])
def test_invalid_or_zero_money_ceiling_never_enters_transport(tmp_path,monkeypatch,cap):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    ids=setup(p,'cap',brief);monkeypatch.setenv('FRAMEBOUND_SPEND_CEILING',cap);calls=[]
    with pytest.raises(InvalidInput):send(p,ids,lambda req:calls.append(req))
    assert calls==[]
    assert J.job_get(p,ids[1])['job']['dispatch_count']==0

def test_wire_model_is_frozen_and_explicit_retry_setting_conflicts(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    monkeypatch.setenv('FRAMEBOUND_IMAGE_MODEL','model-original');ids=setup(p,'frozen',brief)
    monkeypatch.setenv('FRAMEBOUND_IMAGE_MODEL','model-changed');models=[]
    def fake(req):models.append(req['body']['model']);return response(p)
    assert send(p,ids,fake)['action']=='succeeded'
    assert models==['model-original']
    assert J.submit_generation(p,brief,[],'frozen').artifacts[0]['id']==ids[1]
    with pytest.raises(S.ConflictError):J.submit_generation(p,brief,[],'frozen',provider_settings={'model':'changed'})
