import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from framebound.v2.api.app import create_app
from framebound.v2.services.authz import Actor
from framebound.v2.services.sessions import create_session
from framebound.v2.services.errors import AuthorizationError
from framebound.v3.services import training as T

REVIEWER=Actor(type='reviewer',id='test')
KEYS=dict(meta_api_key='meta-private-value',modal_token_id='modal-private-id',modal_token_secret='modal-private-secret')
SETUP=dict(id='walk-model',name='Walking consistency',focus='motion',budget_dollars=5)

@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setenv('FRAMEBOUND_TRAINING_HOME',str(tmp_path/'private'))
    return tmp_path/'project'


def test_credentials_are_private_and_public_status_never_echoes_them(project):
    with pytest.raises(AuthorizationError):T.configure(project,Actor(type='orchestrator',id='agent'),KEYS)
    status=T.configure(project,REVIEWER,KEYS)
    assert status['meta']['configured'] and status['modal']['configured']
    assert not any(v in json.dumps(status) for v in KEYS.values())
    file=T.home(project)/'providers.json'
    assert file.stat().st_mode & 0o777==0o600
    assert json.loads(file.read_text())==KEYS
    T.configure(project,REVIEWER,dict(meta_api_key=''))
    assert not T.providers(project)['meta']['configured']
    assert T.providers(project)['modal']['configured']
    with pytest.raises(ValueError,match='both'):T.configure(project,REVIEWER,dict(modal_token_secret=''))


def test_create_requires_explicit_start_and_preserves_settings(project,monkeypatch):
    calls=[];monkeypatch.setattr(T,'launch',lambda *a:calls.append(a))
    row=T.create(project,REVIEWER,SETUP)
    assert row['status']=='ready' and not calls
    assert T.create(project,REVIEWER,SETUP)==row
    with pytest.raises(ValueError,match='different'):T.create(project,REVIEWER,dict(SETUP,budget_dollars=6))
    with pytest.raises(ValueError,match='Meta'):T.start(project,REVIEWER,SETUP['id'],dict(confirm_spend=True,confirm_standard_rates=True))
    T.configure(project,REVIEWER,KEYS)
    with pytest.raises(ValueError):T.start(project,REVIEWER,SETUP['id'],dict(confirm_spend=False,confirm_standard_rates=True))
    T.start(project,REVIEWER,SETUP['id'],dict(confirm_spend=True,confirm_standard_rates=True))
    assert len(calls)==1
    assert not (T.home(project)/'data').exists()


def test_http_auth_validation_and_secret_redaction(project,monkeypatch):
    client=TestClient(create_app(str(project)))
    assert client.put('/v3/settings/providers',json=KEYS).status_code==403
    token=create_session(str(project),'reviewer')['session_token'];headers={'X-Session-Token':token}
    response=client.put('/v3/settings/providers',json=KEYS,headers=headers)
    assert response.status_code==200
    assert not any(v in response.text for v in KEYS.values())
    malformed=client.put('/v3/settings/providers',json=dict(KEYS,extra='secret-unexpected'),headers=headers)
    assert malformed.status_code==422
    assert 'secret-unexpected' not in malformed.text
    assert client.post('/v3/training',json=SETUP,headers=headers).status_code==200
    assert client.get('/v3/training').json()['runs'][0]['name']==SETUP['name']
    assert client.get('/v3/training/missing').status_code==422


def test_worker_freezes_exact_step_then_closes_on_gate(project,monkeypatch):
    from framebound.v3.campaign import service
    T.configure(project,REVIEWER,KEYS);T.create(project,REVIEWER,SETUP)
    evidence=dict(verified_at='2026-11-02T00:00:00+00:00',source='test quote',account_access='test account',image_microdollars=10000,segmentation_microdollars=2500)
    monkeypatch.setattr(T,'account_evidence',lambda key:evidence)
    calls=[]
    def operation(root,action,**kwargs):
        if action=='upskill-plan':
            return dict(next_action='collect_fixed_batch',stage='rehearsal',reasons=[])
        calls.append(kwargs['request'])
        return dict(status='blocked')
    monkeypatch.setattr(service,'operate',operation)
    T.run(project,SETUP['id'])
    assert len(calls)==1
    assert calls[0]['batch']=='b001' and calls[0]['max_cases']==12
    assert calls[0]['allocation_microdollars']==1500000
    assert T.snapshot(project,SETUP['id'])['status']=='blocked'
    from framebound.v3.campaign.ledger import Ledger
    Ledger(T.home(project)/'data').stop('learn-walk-model')
    with pytest.raises(ValueError,match='failed cohorts'):T.start(project,REVIEWER,SETUP['id'],dict(confirm_spend=True,confirm_standard_rates=True))
    saved=T.home(project)/'data/campaigns/learn-walk-model/upskill/b001/journey-step.json'
    assert json.loads(saved.read_text())==calls[0]
    assert saved.stat().st_mode & 0o777==0o600


def test_worker_never_exposes_transport_exception_secrets(project,monkeypatch):
    T.configure(project,REVIEWER,KEYS);T.create(project,REVIEWER,SETUP)
    def fail(_):raise RuntimeError('Authorization: Bearer '+KEYS['meta_api_key'])
    monkeypatch.setattr(T,'account_evidence',fail)
    T.run(project,SETUP['id'])
    row=T.snapshot(project,SETUP['id'])
    assert row['status']=='blocked'
    assert KEYS['meta_api_key'] not in json.dumps(row)


def test_symlink_and_repository_storage_rejected(project,tmp_path,monkeypatch):
    T.configure(project,REVIEWER,KEYS)
    source=T.home(project)/'providers.json';source.unlink();source.symlink_to(tmp_path/'elsewhere')
    with pytest.raises(ValueError,match='symlink'):T.configure(project,REVIEWER,KEYS)
    monkeypatch.setenv('FRAMEBOUND_TRAINING_HOME',str(Path(__file__).resolve().parents[1]/'private-test'))
    with pytest.raises(ValueError,match='outside'):T.home(project)


def test_pause_drains_batch_and_restart_resumes_only_active_journeys(project,monkeypatch):
    calls=[];monkeypatch.setattr(T,'launch',lambda *args:calls.append(args))
    T.create(project,REVIEWER,SETUP)
    T.update(project,SETUP['id'],status='collecting')
    paused=T.pause(project,REVIEWER,SETUP['id'])
    assert paused['pause_requested'] and paused['status']=='collecting'
    T.resume_saved(project)
    assert len(calls)==1
    T.update(project,SETUP['id'],status='blocked')
    T.resume_saved(project)
    assert len(calls)==1


def test_unknown_acceptance_cannot_resume_and_reservation_stays_booked(project,monkeypatch):
    from framebound.v3.campaign.ledger import Ledger
    from framebound.v3.campaign.curriculum import upskill_curriculum
    T.configure(project,REVIEWER,KEYS);T.create(project,REVIEWER,SETUP)
    ledger=Ledger(T.home(project)/'data');ledger.plan(upskill_curriculum('learn-walk-model'))
    # Inspect the exact durable unknown state rather than inventing a receipt.
    with ledger.db() as db:
        db.execute("INSERT INTO requests(id,campaign,case_id,operation,binding,request,subsystem,reserved,images,state) VALUES('unknown','learn-walk-model','case','diagnose','bound','{}','api',116736,0,'unknown_provider_outcome')")
    T.update(project,SETUP['id'],status='blocked')
    monkeypatch.setattr(T,'launch',lambda *args:pytest.fail('Unknown acceptance must not restart'))
    with pytest.raises(ValueError,match='unknown acceptance'):T.start(project,REVIEWER,SETUP['id'],dict(confirm_spend=True,confirm_standard_rates=True))
    assert T.snapshot(project,SETUP['id'])['reserved_dollars']==0.116736


def test_focus_uses_actual_category_support_and_real_checkpoint_experiment(project,monkeypatch):
    from framebound.v3.campaign.transfer import FeatureRow,FeatureShard
    from framebound.v3.campaign.contracts import canonical
    from framebound.v3.campaign import study
    T.create(project,REVIEWER,dict(SETUP,focus='identity'))
    root=T.home(project)/'data';folder=root/'campaigns/learn-walk-model/features';folder.mkdir(parents=True)
    rows=[FeatureRow(case_id=f'{n:064x}',family_id=f'{n//4:064x}',split='train' if n<300 else 'validation',
        features=[[float(n%2)]*8],targets=[n%2]+[0]*8,assessed=[True]+[False]*8) for n in range(340)]
    feature=folder/'features.json';feature.write_bytes(canonical(FeatureShard(rows=rows)))
    # The profile call is plumbing here; real local profiler is covered separately.
    def profile(root,campaign,request):
        path=root/'profile.json';path.write_text('{}');return {'path':str(path)}
    monkeypatch.setattr(study,'profile',profile)
    result={'studies':{'geometry':{'features':{'path':str(feature)}}}}
    reviewed=T.review_support(project,SETUP['id'],result)
    assert set(reviewed['support'])=={'identity','parts','prop','artifacts'}
    assert reviewed['model']['categories']==['identity']
    assert reviewed['model']['checkpoint_count']==6 and reviewed['training_eligible']
    assert not reviewed['model']['promoted']
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(T.model_artifact(project,SETUP['id']))) as archive:
        assert len(archive.namelist())==7
        assert json.loads(archive.read('model-card.json'))['gate']['eligible']
    assert not reviewed['support']['parts']['gate']['eligible']


def test_multiple_journeys_add_authorizations_without_erasing_history(project,monkeypatch):
    from framebound.v3.campaign import service
    from framebound.v3.campaign.ledger import Ledger
    T.configure(project,REVIEWER,KEYS)
    monkeypatch.setattr(T,'account_evidence',lambda key:dict(verified_at='2026-11-02T00:00:00+00:00',source='test',account_access='test',image_microdollars=10000,segmentation_microdollars=2500))
    monkeypatch.setattr(service,'operate',lambda *a,**k:dict(next_action='evidence_review',stage='rehearsal',reasons=['Fixture stops before collection']))
    T.create(project,REVIEWER,SETUP);T.run(project,SETUP['id'])
    prior=Ledger(T.home(project)/'data')
    with prior.db() as db:
        db.execute("INSERT INTO requests(id,campaign,case_id,operation,binding,request,subsystem,reserved,incurred,images,state) VALUES('history','learn-walk-model','case','generate','old-binding','{}','api',2000000,2000000,1,'received')")
        db.execute("INSERT INTO requests(id,campaign,case_id,operation,binding,request,subsystem,reserved,images,state) VALUES('old-unknown','learn-walk-model','case2','diagnose','old-unknown-binding','{}','api',100000,0,'unknown_provider_outcome')")
    second=dict(SETUP,id='other',budget_dollars=7)
    T.create(project,REVIEWER,second);T.run(project,'other')
    ledger=Ledger(T.home(project)/'data')
    with ledger.db() as db:
        caps=[r[0] for r in db.execute('SELECT ceiling FROM api_budget_authorizations ORDER BY id')]
        assert caps==[5000000,12000000]
    assert ledger.config('learn-walk-model').api_ceiling==5000000
    assert ledger.config('learn-other').api_ceiling==7000000
    assert T.snapshot(project,'other')['workspace_budget_dollars']==12
    assert T.snapshot(project,'other')['workspace_committed_dollars']==2.1
    assert T.snapshot(project,SETUP['id'])['spent_dollars']==2
    assert T.snapshot(project,SETUP['id'])['reserved_dollars']==0.1


def test_worker_replays_saved_batch_and_moves_rehearsal_to_pilot(project,monkeypatch):
    from framebound.v3.campaign import service
    T.configure(project,REVIEWER,KEYS);T.create(project,REVIEWER,SETUP)
    monkeypatch.setattr(T,'account_evidence',lambda key:dict(verified_at='2026-11-02T00:00:00+00:00',source='test',account_access='test',image_microdollars=10000,segmentation_microdollars=2500))
    monkeypatch.setattr(T,'review_support',lambda *a,**k:{})
    calls=[]
    def operation(root,action,**kw):
        if action=='upskill-plan':return dict(next_action='collect_fixed_batch',stage='rehearsal' if not calls else 'pilot',reasons=[])
        calls.append(kw['request'])
        return dict(status='completed' if len(calls)==1 else 'blocked')
    monkeypatch.setattr(service,'operate',operation)
    T.run(project,SETUP['id'])
    assert [(r['batch'],r['max_cases']) for r in calls]==[('b001',12),('b002',20)]
    assert calls[1]['allocation_microdollars']==5000000 # own five-dollar ceiling
    before=json.dumps(calls[0],sort_keys=True)
    calls.clear();T.run(project,SETUP['id'])
    assert json.dumps(calls[0],sort_keys=True)==before


def test_credit_only_compute_uses_saved_modal_pair_and_stops_when_local_is_faster(project,monkeypatch):
    from datetime import datetime,timedelta,timezone
    import hashlib
    import modal
    from framebound.v3.campaign import study,remote,modal_worker
    from framebound.v3.campaign.ledger import Ledger
    from framebound.v3.campaign.curriculum import upskill_curriculum
    from framebound.v3.campaign.contracts import canonical
    T.configure(project,REVIEWER,KEYS);T.create(project,REVIEWER,SETUP)
    root=T.home(project)/'data';ledger=Ledger(root);ledger.plan(upskill_curriculum('learn-walk-model'))
    feature=root/'features.json';feature.write_bytes(b'engineering payload')
    T.write(T.home(project)/'candidate-walk-model.json',dict(feature_file='features.json',categories=['temporal'],
        baseline_file='baseline.json',local_profile_file='profile.json'))
    threads=[]
    class Thread:
        def __init__(self,**kw):threads.append(kw)
        def start(self):pass
    monkeypatch.setattr(T.threading,'Thread',Thread)
    setup=dict(available_credit_dollars=10,workspace_remaining_dollars=10,
        expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),source='Engineering operator dashboard credit',
        image_digest='sha256:'+'0'*64,confirm_compute=True,confirm_standard_rates=True)
    T.update(project,'walk-model',training_eligible=True,status='support_review')
    T.configure_compute(project,REVIEWER,'walk-model',setup)
    calls=[]
    class Client:
        def hello(self):calls.append('authenticated')
    client=Client()
    def from_credentials(identifier,secret):
        assert identifier==KEYS['modal_token_id'] and secret==KEYS['modal_token_secret']
        return client
    monkeypatch.setattr(modal.Client,'from_credentials',from_credentials)
    monkeypatch.setattr(modal_worker,'ModalTransport',lambda **kw:kw['client'])
    def plan(root,campaign,request):
        purpose=request['purpose'];calls.append('plan-'+purpose)
        job=remote.Job(payload_sha256=hashlib.sha256(feature.read_bytes()).hexdigest(),recipe_sha256='1'*64,
            image_digest=setup['image_digest'],purpose=purpose,categories=['temporal'],seconds=300,startup_seconds=120,replay_seconds=300)
        return dict(admitted=purpose=='profile',job=job.model_dump(),reasons=[] if purpose=='profile' else ['Modal did not improve end-to-end runtime by at least 25%; retain local compute'])
    monkeypatch.setattr(study,'compute_plan',plan)
    def submit(ledger,campaign,case_id,raw,job,transport,**kw):
        assert transport is client and kw['study']['credit_file'].endswith('credit.json')
        calls.append('send-'+job.purpose)
        with ledger.db() as db:
            db.execute("INSERT INTO requests(id,campaign,case_id,operation,binding,request,subsystem,reserved,incurred,images,state) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ('profile-request',campaign,case_id,'train','profile-binding',json.dumps({'attempt':0}),'modal',job.quote(),job.quote(),0,'received'))
        return dict(result={'result':{'status':'profile_only'}},receipt={})
    monkeypatch.setattr(remote,'submit',submit)
    T.run_compute(project,'walk-model')
    assert calls==['authenticated','plan-profile','send-profile','plan-train']
    row=T.snapshot(project,'walk-model')
    assert row['compute_status']=='local_preferred' and row['status']=='completed'
    assert row['compute_history']==[dict(purpose='profile',request_id='profile-request',status='received')]
    assert not row['model_promoted']
    credit=json.loads((root/'campaigns/learn-walk-model/journey-compute/credit.json').read_text())
    assert credit['net_spend_remaining_microdollars']==0
    assert credit['available_microdollars']==10000000


def test_real_campaign_engine_closes_rehearsal_and_releases_pilot_offline(project,monkeypatch):
    """Full service/ledger/controller wiring, with explicitly synthetic providers."""
    import base64,hashlib,io
    from datetime import datetime,timezone
    from PIL import Image
    from test_campaign_runner import EngineeringSpecialist
    from framebound.v3.campaign import specialists,curriculum,service
    from framebound.v3.campaign.contracts import canonical
    from framebound.v3.campaign.dispatch import Response
    from framebound.v3.campaign.ledger import Ledger
    original=curriculum.upskill_curriculum
    # Segmentation has its own integration tests. This exercises the real
    # rehearsal/release engine with the legacy alpha fixture, never paid masks.
    monkeypatch.setattr(curriculum,'upskill_curriculum',lambda campaign,**kw:original(campaign))
    class Offline(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            result=super().execute(request,timeout=timeout);body=json.loads(result.raw)
            if request['images']:
                im=Image.open(io.BytesIO(base64.b64decode(body['output'][0]['result']))).convert('RGBA')
                distinct=Image.new('RGBA',im.size,tuple(hashlib.sha256(request['family'].encode()).digest()[:3])+(255,));distinct.putalpha(im.getchannel('A'))
                data=io.BytesIO();distinct.save(data,format='PNG');body['output'][0]['result']=base64.b64encode(data.getvalue()).decode()
            elif request['operation']=='diagnose':
                parsed=json.loads(body['output'][0]['text']);parsed['findings']=[]
                for item in parsed['coverage']:item['status']='absent_within_assessed_scope'
                body['output'][0]['text']=json.dumps(parsed)
            return Response(canonical(body),result.incurred,result.successful_images,result.receipt)
        def execute_stream(self,request,*,timeout,on_acceptance,on_observation):
            result=self.execute(request,timeout=timeout);wire=request['payload']['wire']
            rid='resp_engineering_'+str(len(self.sends))
            ack=dict(id=rid,model=wire['model'],metadata=wire['metadata'],status='queued')
            on_acceptance(ack);body=json.loads(result.raw);body.update(ack,status='completed');on_observation(canonical(body))
            return Response(canonical(body),result.incurred,result.successful_images,dict(result.receipt,response_id=rid))
    provider=Offline();monkeypatch.setattr(specialists,'MuseResponses',lambda **kw:provider)
    monkeypatch.setattr(T,'account_evidence',lambda key:dict(verified_at=datetime.now(timezone.utc).isoformat(),source='Engineering fixture rates',account_access='Synthetic offline provider',image_microdollars=10000))
    T.configure(project,REVIEWER,KEYS);T.create(project,REVIEWER,SETUP)
    real_operate=service.operate
    def operate(root,action,**kw):
        result=real_operate(root,action,**kw)
        if action=='upskill-step' and kw['request']['batch']=='b002':
            # The actual second batch released the pilot; pause after its drain.
            T.update(project,SETUP['id'],pause_requested=True)
        return result
    monkeypatch.setattr(service,'operate',operate)
    T.run(project,SETUP['id'])
    root=T.home(project)/'data';ledger=Ledger(root)
    first=json.loads((root/'campaigns/learn-walk-model/upskill/b001/result.json').read_text())
    assert first['status']=='completed' and first['batch_evidence']['passed']
    assert first['batch_evidence']['scoped_assessed']==12
    assert first['knowledge_closure_valid']
    with ledger.db() as db:
        assert db.execute("SELECT 1 FROM knowledge_releases WHERE campaign='learn-walk-model' AND stage='pilot'").fetchone()
    assert (root/'campaigns/learn-walk-model/upskill/b002/request.json').is_file()
    assert provider.sends and all(r['campaign']=='learn-walk-model' for r in provider.sends)
