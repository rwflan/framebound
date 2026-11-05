import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from framebound.v3.campaign.dispatch import Response
from scripts.provider_operation import run,authorize_recovery


def request():return dict(payload=dict(wire=dict(model='muse-image-1.0',stream=True,store=True,input=[])),quote=10000)


class Adapter:
    def __init__(self,fail=None):self.posts=0;self.gets=0;self.fail=fail
    def execute_stream(self,req,*,timeout,on_acceptance,on_observation):
        self.posts+=1
        if self.fail=='unknown':raise TimeoutError('No acceptance received')
        on_acceptance(dict(id='resp_retained',model='muse-image-1.0',status='in_progress'))
        on_observation(b'data: retained acceptance\n\n')
        if self.fail=='accepted':raise TimeoutError('Stream interrupted')
        return self._result(req,b'{"id":"resp_retained","model":"muse-image-1.0","status":"completed"}')
    def retrieve(self,req,acceptance,*,timeout):
        assert acceptance['id']=='resp_retained';self.gets+=1
        return self._result(req,b'{"id":"resp_retained","model":"muse-image-1.0","status":"completed"}')
    def _result(self,req,raw):return Response(raw,10000,1,dict(response_id='resp_retained',cost_basis='provider usage and frozen rate'))


def test_accepted_stream_survives_interruption_without_another_post(tmp_path):
    adapter=Adapter('accepted');folder=tmp_path/'op';req=request()
    with pytest.raises(TimeoutError):run(folder,req,adapter)
    assert (folder/'acceptance.json').exists() and (folder/'stream.sse').exists()
    run(folder,req,adapter);run(folder,req,adapter)
    assert adapter.posts==1 and adapter.gets==1
    assert json.loads((folder/'status.json').read_text())['status']=='terminal_result'
    changed=request();changed['payload']['wire']['input']=['changed']
    with pytest.raises(ValueError,match='immutable'):run(folder,changed,adapter)


def test_unknown_creation_is_not_reposted_and_linked_recovery_keeps_its_commitment(tmp_path):
    root=tmp_path;folder=root/'private'/'parent';adapter=Adapter('unknown')
    with pytest.raises(TimeoutError):run(folder,request(),adapter)
    frozen=(folder/'request.json').read_bytes()
    with pytest.raises(FileExistsError):run(folder,request(),adapter)
    assert adapter.posts==1
    link=authorize_recovery(root,'parent','successor',authorization='Explicit user instruction',max_recovery_microdollars=20000)
    assert link['original_status']=='acceptance_unknown'
    # A second distinct successor is allowed, but not a third or an infinite chain.
    second=root/'private'/'successor';(second/'request.json').write_bytes(frozen)
    authorize_recovery(root,'successor','second',authorization='Standing bounded instruction',max_recovery_microdollars=20000)
    third=root/'private'/'second';(third/'request.json').write_bytes(frozen)
    with pytest.raises(ValueError,match='count'):authorize_recovery(root,'second','third',authorization='same',max_recovery_microdollars=20000)
    assert (folder/'request.json').read_bytes()==frozen and not (folder/'response.json').exists()


def test_concurrent_resumption_and_lost_cost_receipt_never_repeat_paid_creation(tmp_path):
    adapter=Adapter();folder=tmp_path/'op';req=request()
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:run(folder,req,adapter),range(2)))
    assert adapter.posts==1
    (folder/'receipt.json').unlink();run(folder,req,adapter)
    assert adapter.posts==1 and json.loads((folder/'receipt.json').read_text())['incurred_microdollars']==10000


def test_authorized_automatic_successor_unblocks_sender_without_reposting_parent(tmp_path,monkeypatch):
    import scripts.build_movement_demo as demo
    from framebound.v3.experiment_costs import summarize
    (tmp_path/'config.json').write_text(json.dumps(dict(durable_provider_transport='stream',provider_recovery_policy=dict(authorization='User approved bounded recovery',max_successors_per_parent=2,max_recovery_microdollars=1000000))))
    count=[]
    class Flaky(Adapter):
        def preflight(self,req):pass
        def execute_stream(self,req,**kwargs):
            count.append(req['payload']['wire']['metadata']['framebound_operation'])
            if len(count)==1:raise TimeoutError('Unknown acceptance')
            return super().execute_stream(req,**kwargs)
    adapter=Flaky();monkeypatch.setattr(demo,'MuseResponses',lambda:adapter);monkeypatch.setattr(demo,'refresh_costs',lambda *a,**k:None)
    first=demo.send(tmp_path,'logical-op','muse-image-1.0','approved prompt',[])
    assert first==demo.send(tmp_path,'logical-op','muse-image-1.0','approved prompt',[])
    assert len(count)==2 and count[0]!=count[1]
    assert not (tmp_path/'private/logical-op/response.json').exists()
    ledger=summarize([tmp_path])['summary']
    assert ledger['observed_microdollars']==10000 and ledger['unreconciled_reserve_microdollars']==10000


def test_pending_worker_resumes_only_registered_jobs_and_never_reposts_accepted(tmp_path,monkeypatch):
    import scripts.provider_worker as worker
    folder=tmp_path/'private/active';adapter=Adapter('accepted')
    with pytest.raises(TimeoutError):run(folder,request(),adapter)
    (folder/'job.json').write_text('{}')
    old=tmp_path/'private/historical';old.mkdir();(old/'request.json').write_text(json.dumps(dict(wire=request()['payload']['wire'],committed_microdollars=10000)))
    monkeypatch.setattr(worker,'MuseResponses',lambda:adapter);monkeypatch.setattr(worker,'refresh_costs',lambda *a,**k:None)
    worker.tick(tmp_path)
    assert adapter.posts==1 and adapter.gets==1
    assert not (old/'response.json').exists()


def test_expired_accepted_result_is_distinct_from_unknown_creation(tmp_path):
    import urllib.error
    folder=tmp_path/'private/op';adapter=Adapter('accepted')
    with pytest.raises(TimeoutError):run(folder,request(),adapter)
    def unavailable(*args,**kwargs):raise urllib.error.HTTPError('https://provider/retained',404,'Not found',{},None)
    adapter.retrieve=unavailable
    for _ in range(3):
        with pytest.raises(urllib.error.HTTPError):run(folder,request(),adapter)
    assert json.loads((folder/'status.json').read_text())['status']=='accepted_result_unavailable'
    assert adapter.posts==1
    link=authorize_recovery(tmp_path,'op','new-op',authorization='User standing recovery policy')
    assert link['original_status']=='accepted_result_unavailable'


def test_recovered_but_bad_artwork_clears_transport_block_without_accepting_image(tmp_path,monkeypatch):
    import hashlib
    import scripts.stage_recovered_character as staging
    from test_character_consistency import policy
    root=tmp_path;folder=root/'private/recovered';folder.mkdir(parents=True)
    raw=b'retained provider output';(folder/'response.json').write_bytes(raw)
    (folder/'receipt.json').write_text(json.dumps(dict(response_sha256=hashlib.sha256(raw).hexdigest())))
    parent=root/'private/parent';parent.mkdir();(parent/'request.json').write_bytes(b'original immutable commitment')
    (folder/'recovery.json').write_text(json.dumps(dict(recovery_of='parent',parent_request_sha256=hashlib.sha256((parent/'request.json').read_bytes()).hexdigest())))
    state_path=root/'state.json';state_path.write_text(json.dumps(dict(frames={'run':dict(image='original.png',blocked_generation_operation='parent')})))
    monkeypatch.setattr(staging,'load_config',lambda root:({},dict(minimum_subject_span=1100),dict(canvas=[1000,1000]),tmp_path))
    monkeypatch.setattr(staging,'initialize',lambda root:policy())
    def bad_intake(*args):raise ValueError('Opaque background')
    monkeypatch.setattr(staging,'decode',bad_intake)
    result=staging.stage(root,state_path,'run','recovered')['frames']['run']
    assert 'blocked_generation_operation' not in result
    assert result['image']=='original.png' and result['recovery_candidate_status']=='intake_rejected'
    assert result['historical_unknown_operations']==['parent']


def test_explicit_resume_uses_frozen_wire_and_get_even_when_new_defaults_change(tmp_path,monkeypatch):
    import framebound.v3.campaign.specialists as specialists
    from scripts.recover_provider_operation import resume
    adapter=Adapter('accepted');req=request();req['payload']['wire']['max_output_tokens']=1234
    with pytest.raises(TimeoutError):run(tmp_path/'private/op',req,adapter)
    original=adapter.retrieve
    def retrieve(frozen,*args,**kwargs):
        assert frozen['payload']['wire']['max_output_tokens']==1234
        return original(frozen,*args,**kwargs)
    adapter.retrieve=retrieve
    monkeypatch.setattr(specialists,'MuseResponses',lambda:adapter)
    import scripts.build_movement_demo as builder
    monkeypatch.setattr(builder,'refresh_costs',lambda *a,**k:None)
    resume(tmp_path,'op')
    assert adapter.posts==1 and adapter.gets==1
