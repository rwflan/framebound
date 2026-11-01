"""Transport recovery and fixed-batch learning counterexamples, without paid calls."""
import io
import json
from datetime import datetime,timezone

import pytest

from framebound.v3.campaign.contracts import Prices,canonical,curriculum,parse_campaign
from framebound.v3.campaign.curriculum import mvp_curriculum,upskill_curriculum,protocol
from framebound.v3.campaign.dispatch import dispatch
from framebound.v3.campaign.ledger import Ledger,ProviderPending,Stopped
from framebound.v3.campaign.specialists import MuseResponses
from framebound.v3.campaign import continuation


def evidence():
    return dict(verified_at=datetime.now(timezone.utc).isoformat(),source='Engineering rates',
                account_access='Synthetic account authority',image_microdollars=10000)


def background(tmp_path):
    config=curriculum('engineering').model_copy(update={'prices':Prices(verified_at='fixture')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',100000,evidence='Engineering fixture')
    case=next(c for c in config.cases if c.stage=='pilot')
    wire=dict(model='muse-image-1.0',background=True,store=True,metadata={'framebound_binding':'a'*64},input='Synthetic image request')
    row=ledger.reserve(config.id,case.id,'generate',dict(wire=wire),quote=10000,images=1)
    return ledger,config,row


def body(state='queued',**changes):
    return dict(dict(id='resp_engineering',model='muse-image-1.0',background=True,
                     metadata={'framebound_binding':'a'*64},status=state,
                     output=[] if state!='completed' else [dict(type='image_generation_call',result='fixture')]),**changes)


def test_acceptance_is_durable_before_get_and_receipt_replays_without_io(tmp_path,monkeypatch):
    ledger,config,row=background(tmp_path);calls=[]
    def urlopen(req,timeout):
        calls.append(req.get_method())
        if req.get_method()=='GET':assert json.loads(ledger.request(row['id'])['acceptance'])['id']=='resp_engineering'
        return io.BytesIO(canonical(body('queued' if req.get_method()=='POST' else 'completed')))
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    specialist=MuseResponses(key='engineering-only')
    dispatch(ledger,row['id'],specialist)
    assert calls==['POST','GET']
    assert ledger.request(row['id'])['incurred']==10000
    assert dispatch(Ledger(tmp_path),row['id'],specialist)['successful_images']==1
    assert calls==['POST','GET']


def test_pending_restart_only_retrieves_same_response(tmp_path,monkeypatch):
    ledger,config,row=background(tmp_path);calls=[]
    def urlopen(req,timeout):
        calls.append(req.get_method());return io.BytesIO(canonical(body('queued' if req.get_method()=='POST' else 'completed')))
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    first=MuseResponses(key='engineering-only')
    monkeypatch.setattr(first,'retrieve',lambda *a,**k:(_ for _ in ()).throw(ProviderPending('Still running')))
    with pytest.raises(ProviderPending):dispatch(ledger,row['id'],first)
    assert Ledger(tmp_path).request(row['id'])['state']=='provider_pending'
    assert ledger.status(config.id)['budgets']['api']['reserved']==10000
    with pytest.raises(Stopped):ledger.finish_case(config.id,row['case_id'],'ambiguous',{'outcome':'ambiguous'})
    dispatch(Ledger(tmp_path),row['id'],MuseResponses(key='engineering-only'))
    assert calls==['POST','GET']
    assert ledger.status(config.id)['budgets']['api']['reserved']==0


def test_missing_acceptance_is_never_reposted_and_isolation_keeps_spend(tmp_path,monkeypatch):
    ledger,config,row=background(tmp_path);calls=[]
    def urlopen(req,timeout):calls.append(req.get_method());raise TimeoutError('Synthetic lost acknowledgement')
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    specialist=MuseResponses(key='engineering-only')
    with pytest.raises(TimeoutError):dispatch(ledger,row['id'],specialist)
    isolated=ledger.isolate_unknown(config.id,row['id'],dict(source='Engineering operator',reason='No recoverable provider ID'))
    assert isolated==dict(request_id=row['id'],state='unknown_provider_outcome',reserved=10000,incurred=None,
                         research_excluded=True,retry_permitted=False,provider_outcome_resolved=False)
    with pytest.raises(Stopped):dispatch(Ledger(tmp_path),row['id'],specialist)
    assert calls==['POST']
    assert ledger.status(config.id)['budgets']['api']['reserved']==10000
    assert ledger.status(config.id)['isolated_unknown_requests']==[row['id']]
    with pytest.raises(ValueError,match='immutable'):
        ledger.isolate_unknown(config.id,row['id'],dict(source='Changed',reason='No evidence'))


def test_oversized_body_is_rejected_before_wire_start(tmp_path,monkeypatch):
    ledger,config,row=background(tmp_path)
    # A second frozen attempt is not used: create the oversized shape at source.
    other=tmp_path/'other';ledger,config,row=background(other)
    request=json.loads(ledger.request(row['id'])['request'])
    request['payload']['wire']['input']='x'*1048576
    specialist=MuseResponses(key='engineering-only')
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:pytest.fail('Paid I/O forbidden'))
    with pytest.raises(ValueError,match='1 MiB'):specialist.preflight(request)
    assert ledger.request(row['id'])['state']=='reserved'


@pytest.mark.parametrize('changes',[{'id':'../steal'},{'model':'another-model'},{'metadata':{}},{'background':False}])
def test_mismatched_acknowledgement_never_becomes_a_receipt(tmp_path,monkeypatch,changes):
    ledger,config,row=background(tmp_path)
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:io.BytesIO(canonical(body(**changes))))
    with pytest.raises(ValueError):dispatch(ledger,row['id'],MuseResponses(key='engineering-only'))
    saved=ledger.request(row['id'])
    assert saved['state']=='unknown_provider_outcome' and not saved['acceptance'] and not saved['receipt']
    assert saved['reserved']==10000
    observations=list((tmp_path/'campaigns'/config.id/'originals').glob('observed-*'))
    assert len(observations)==1 and observations[0].read_bytes()==canonical(body(**changes))


def test_new_recipe_is_disjoint_and_old_v2_bytes_are_preserved():
    original=mvp_curriculum().model_dump(mode='json')
    assert 'transport' not in original and 'assessment_policy' not in original
    assert canonical(parse_campaign(original))==canonical(original)
    new=upskill_curriculum('independent-study')
    assert new.transport=='background-images-v1' and new.assessment_policy=='independent-coverage-v2'
    assert not {c.family for c in new.cases}&{c.family for c in mvp_curriculum().cases}
    assert len(protocol(new)['rehearsal'])==12
    for family in {c.family for c in new.cases}:
        cases=[c for c in new.cases if c.family==family]
        assert len({c.request.split('Complexity')[0].split('. ',1)[0] for c in cases})==1
    assert canonical(parse_campaign(canonical(new)))==canonical(new)


def test_fixed_batch_resume_does_not_add_unattempted_cases(tmp_path,monkeypatch):
    config=mvp_curriculum('workflow-fixture');ledger=Ledger(tmp_path);ledger.plan(config)
    calls=[];pending_id=[]
    class FakeRunner:
        def __init__(self,*args):pass
        def run(self,*,max_cases,case_ids):
            calls.append(list(case_ids));assert max_cases==2
            if len(calls)==1:
                ledger.finish_case(config.id,case_ids[0],'ambiguous',{'outcome':'ambiguous'})
                row=ledger.reserve(config.id,case_ids[1],'generate',{'wire':dict(model='muse-image-1.0',background=True,
                    metadata={'framebound_binding':'a'*64})},quote=10000,images=1)
                permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit)
                ledger.record_acceptance(row['id'],body());ledger.pending(row['id'],'Fixture waiting');pending_id.append(row['id'])
            else:
                ledger.receive(pending_id[0],b'fixture',incurred=10000,successful_images=1,provider_receipt={'fixture':True})
                ledger.finish_case(config.id,case_ids[1],'ambiguous',{'outcome':'ambiguous'})
            return dict(status=ledger.status(config.id),deferred={})
    monkeypatch.setattr('framebound.v3.campaign.runner.Runner',FakeRunner)
    monkeypatch.setattr(continuation,'close',lambda *a:dict(studies={},dataset_version='fixture'))
    monkeypatch.setattr(continuation,'cohort_evidence',lambda *a:dict(passed=True))
    request=dict(batch='fixed-001',max_cases=2,allocation_microdollars=100000,evidence=evidence())
    first=continuation.step(tmp_path,config.id,request,object());assert first['status']=='waiting_for_response'
    with pytest.raises(Stopped,match='unfinished fixed batch'):
        continuation.step(tmp_path,config.id,dict(request,batch='sneak-extra-cases'),object())
    second=continuation.step(tmp_path,config.id,request,object());assert second['status']=='completed'
    assert calls[0]==calls[1]
    assert ledger.status(config.id)['cases']==dict(ambiguous=2,planned=798)
    assert continuation.step(tmp_path,config.id,request,object())==second and len(calls)==2
    with pytest.raises(ValueError,match='immutable'):
        continuation.step(tmp_path,config.id,dict(request,max_cases=3),object())


def test_isolated_family_ancestry_cannot_create_another_paid_send(tmp_path):
    ledger,config,row=background(tmp_path)
    permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit);ledger.unknown(row['id'],'Fixture unknown')
    ledger.isolate_unknown(config.id,row['id'],dict(source='Fixture operator',reason='Permanent exclusion'))
    source=next(c for c in config.cases if c.id==row['case_id'])
    derived=source.model_copy(update={'id':'new-case','family':'new-name','ancestry':[source.family]})
    other=config.model_copy(update={'id':'derived-campaign','cases':[derived]});ledger.plan(other)
    ledger.fund(other.id,'api',100000,evidence='Fixture funding')
    with pytest.raises(Stopped,match='unknown family'):
        ledger.reserve(other.id,derived.id,'generate',{'wire':{'model':'engineering'}},quote=10000,images=1)
    assert ledger.request(row['id'])['state']=='unknown_provider_outcome'
    assert ledger.status(config.id)['budgets']['api']['reserved']==10000


def test_final_release_prevents_controller_development_collection(tmp_path):
    config=mvp_curriculum('final-fixture');ledger=Ledger(tmp_path);ledger.plan(config)
    with ledger.db() as db:
        db.execute('INSERT INTO knowledge_releases(campaign,stage,cases,evidence,request) VALUES(?,?,?,?,?)',
                   (config.id,'final','[]','{}','{}'))
    assert continuation.plan(tmp_path,config.id)['next_action']=='final_evaluation_only'
    result=continuation.step(tmp_path,config.id,dict(batch='after-freeze',allocation_microdollars=100000,
                              evidence=evidence()),object())
    assert result['status']=='final_evaluation_only' and not ledger.status(config.id)['requests']


def test_pending_request_still_blocks_release(tmp_path):
    from framebound.v3.campaign.progression import release
    config=mvp_curriculum('pending-fixture');ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',100000,evidence=evidence())
    cid=protocol(config)['rehearsal'][0]
    row=ledger.reserve(config.id,cid,'generate',{'wire':dict(model='muse-image-1.0',background=True,
                        metadata={'framebound_binding':'a'*64})},quote=10000,images=1)
    permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit)
    ledger.record_acceptance(row['id'],body());ledger.pending(row['id'],'Fixture waiting')
    assert continuation.plan(tmp_path,config.id)['next_action']=='retrieve_accepted_response'
    with pytest.raises(Stopped,match='provider outcomes'):
        release(tmp_path,config.id,dict(stage='pilot'))


def test_complete_step_closes_real_pipeline_and_replay_sends_nothing(tmp_path):
    from test_campaign_runner import EngineeringSpecialist
    from framebound.v3.campaign.dispatch import Response
    class BackgroundEngineering(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            original=super().execute(request,timeout=timeout)
            if not request['images']:return original
            import base64,hashlib
            from PIL import Image
            raw=json.loads(original.raw)
            image=Image.open(io.BytesIO(base64.b64decode(raw['output'][0]['result']))).convert('RGBA')
            # Distinct family pixels are essential; a fixture must not bypass
            # the exporter's real cross-split duplicate refusal.
            color=tuple(hashlib.sha256(request['family'].encode()).digest()[:3])+(255,)
            distinct=Image.new('RGBA',image.size,color);distinct.putalpha(image.getchannel('A'))
            stream=io.BytesIO();distinct.save(stream,format='PNG')
            raw['output'][0]['result']=base64.b64encode(stream.getvalue()).decode()
            return Response(canonical(raw),original.incurred,original.successful_images,original.receipt)
        def execute_with_acceptance(self,request,*,timeout,on_acceptance):
            wire=request['payload']['wire'];rid='resp_'+request['case_id'].replace('-','_')+'_'+str(len(self.sends))
            ack=dict(id=rid,model=wire['model'],metadata=wire['metadata'],background=True,status='queued')
            on_acceptance(ack)
            original=self.execute(request,timeout=timeout);raw=json.loads(original.raw)
            raw.update(ack,status='completed')
            return Response(canonical(raw),original.incurred,original.successful_images,dict(original.receipt,response_id=rid))
    config=upskill_curriculum('pipeline-fixture');ledger=Ledger(tmp_path);ledger.plan(config)
    specialist=BackgroundEngineering()
    request=dict(batch='pipeline-001',max_cases=2,allocation_microdollars=2000000,evidence=evidence())
    result=continuation.step(tmp_path,config.id,request,specialist)
    assert result['status']=='completed',result.get('deferred')
    assert result['batch_evidence']['passed'] and result['knowledge_closure_valid']
    assert result['export']['manifest']['schema_version']=='animation-training-2.0'
    assert result['new_modal_jobs']==0 and result['model_promoted'] is False
    sends=len(specialist.sends)
    assert continuation.step(tmp_path,config.id,request,specialist)==result
    assert len(specialist.sends)==sends
    assert not ledger.status(config.id)['budgets']['api']['reserved']


def test_incompatible_adapter_is_rejected_before_send_permit(tmp_path):
    ledger,config,row=background(tmp_path)
    class LegacyOnly:
        def execute(self,*a,**k):pytest.fail('No paid send authorized')
    with pytest.raises(ValueError,match='no send performed'):dispatch(ledger,row['id'],LegacyOnly())
    assert ledger.request(row['id'])['state']=='reserved'


def test_crash_after_acceptance_recovers_with_get_only(tmp_path,monkeypatch):
    ledger,config,row=background(tmp_path);calls=[]
    def urlopen(req,timeout):
        calls.append(req.get_method());return io.BytesIO(canonical(body('queued' if req.get_method()=='POST' else 'completed')))
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    original=MuseResponses(key='engineering-only')
    monkeypatch.setattr(original,'retrieve',lambda *a,**k:(_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):dispatch(ledger,row['id'],original)
    assert ledger.request(row['id'])['acceptance']
    dispatch(Ledger(tmp_path),row['id'],MuseResponses(key='engineering-only'))
    assert calls==['POST','GET']


def test_custom_adapter_cannot_attach_another_response_receipt(tmp_path):
    from framebound.v3.campaign.dispatch import Response
    ledger,config,row=background(tmp_path)
    class WrongReceipt:
        def execute_with_acceptance(self,request,*,timeout,on_acceptance):
            on_acceptance(body());return Response(b'wrong',0,0,{'response_id':'resp_another'})
    with pytest.raises(ValueError,match='receipt does not match'):
        dispatch(ledger,row['id'],WrongReceipt())
    assert ledger.request(row['id'])['receipt'] is None
    assert ledger.status(config.id)['budgets']['api']['reserved']==10000


def test_actual_validation_rejection_is_received_without_inventing_acceptance(tmp_path,monkeypatch):
    from urllib.error import HTTPError
    ledger,config,row=background(tmp_path);calls=[]
    raw=canonical({'error':{'type':'invalid_request_error','message':'Fixture invalid parameter','param':'background'}})
    def urlopen(req,timeout):
        calls.append(req.get_method());raise HTTPError(req.full_url,400,'Bad Request',{},io.BytesIO(raw))
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    dispatch(ledger,row['id'],MuseResponses(key='engineering-only'))
    saved=ledger.request(row['id'])
    assert saved['state']=='received' and saved['incurred']==0 and saved['acceptance'] is None
    assert ledger.artifact(row['id'])[0]==raw
    assert json.loads(saved['receipt'])['provider']['not_accepted'] is True
    dispatch(ledger,row['id'],MuseResponses(key='engineering-only'))
    assert calls==['POST']
