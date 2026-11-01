"""Counterexamples for versioned learning, privacy, acquisition and compute gates."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image, ImageDraw

from framebound.v3.campaign.assessment import Assessment, Binding, CATEGORIES, Provenance
from framebound.v3.campaign.contracts import Prices, canonical, curriculum, digest, parse_campaign
from framebound.v3.campaign.curriculum import MVPCampaign, mvp_curriculum, protocol
from framebound.v3.campaign.features import extract
from framebound.v3.campaign.intelligence import training_labels
from framebound.v3.campaign.ledger import Ledger, Stopped
from framebound.v3.campaign.progression import admitted, readiness, release
from framebound.v3.campaign.transfer import FeatureRowV2, FeatureShard, inspect_payload, preupload


def assessment(category='temporal', *, execution='one', rubric='a', subject='actor', positive=True):
    coverage=[dict(category=c,status='not_assessed',slots=[],limitations='Engineering scope') for c in CATEGORIES]
    coverage[CATEGORIES.index(category)].update(status='present' if positive else 'absent_within_assessed_scope',slots=[0])
    return Assessment(binding=Binding(**dict.fromkeys(('request_sha256','revision_sha256','timing_sha256','evaluation_sha256'),'a'*64)),
        provenance=Provenance(provider='engineering',requested_model='synthetic',rubric_sha256=rubric*64,raw_sha256='b'*64,execution_id=execution),
        coverage=coverage,findings=[dict(id='defect',category=category,slots=[0],tick_range=[0,2],subject=subject,
            severity='material',visibility='supported',observed='Synthetic defect',expected='Synthetic correction',counterexamples='Authored hold')] if positive else [])


def metadata(first, second):
    return dict(labels=first.targets(),holds=[2],corroborating_assessments=[first.model_dump(mode='json'),second.model_dump(mode='json')])


def geometry_shard(n=24):
    rows=[]
    for index in range(n):
        target=index%2
        rows.append(FeatureRowV2(case_id=f'{index:064x}',family_id=f'{index:064x}',sequence_id=f'{index:064x}',
            split='train' if index<n-4 else 'validation',features=[[float(target)]*20,[float(target)+.01]*20],
            targets=[0]*5+[target]+[0]*3,assessed=[False]*5+[True]+[False]*3,category_weights=[.5]*5+[1.]+[.5]*3))
    return FeatureShard(schema_version='feature-only-2.0',extractor='native-geometry-v2',rows=rows)


def test_historical_contract_roundtrip_is_byte_identical():
    original=canonical(curriculum())
    assert canonical(parse_campaign(original))==original


def test_mvp_curriculum_freezes_scope_rehearsal_and_complete_final_cohort():
    config=mvp_curriculum();plan=protocol(config)
    assert Counter(c.split for c in config.cases)==dict(train=480,validation=160,test=160)
    assert len(plan['rehearsal'])==12 and len(plan['pilot'])==80 and len(plan['final'])==160
    assert len({c.treatment for c in config.cases if c.id in plan['rehearsal']})==8
    assert all(len(c.holds)==6 for c in config.cases if c.id in plan['rehearsal'])
    assert {c.subject for c in config.cases}=={'character','animal','figure','object'}
    assert all(c.complexity.entities==1 and c.action!='effects' for c in config.cases)
    broken=config.model_dump();broken['cases'][0]['complexity']['entities']=2
    with pytest.raises(ValueError,match='one isolated'):MVPCampaign.model_validate(broken)
    assert canonical(parse_campaign(canonical(config)))==canonical(config)


def test_unreleased_cases_cannot_bypass_rehearsal_by_direct_reservation(tmp_path):
    config=mvp_curriculum().model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',1000000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='Engineering fixture',account_access='Synthetic authority',image_microdollars=10000))
    allowed=admitted(ledger,config)
    sealed=next(c for c in config.cases if c.id not in allowed)
    with pytest.raises(Stopped,match='not in this release'):
        ledger.reserve(config.id,sealed.id,'generate',{},quote=10000,images=1)
    with pytest.raises(Stopped,match='unfinished'):
        release(tmp_path,config.id,dict(stage='pilot'))
    assert readiness(tmp_path,config.id)['admitted_cases']==12
    assert not ledger.status(config.id)['requests']


def test_correlated_or_different_subject_labels_never_gain_corroborated_weight():
    first=assessment();second=assessment(execution='two',rubric='c')
    labels,weights=training_labels(metadata(first,second))
    assert weights['temporal']==1. and labels['temporal']['mask']
    assert weights['identity']==.5
    other=assessment(execution='two',rubric='c',subject='another actor')
    _,weights=training_labels(metadata(first,other));assert weights['temporal']==.5
    same=assessment(execution='two',rubric='a')
    _,weights=training_labels(metadata(first,same));assert weights['temporal']==.5
    negative=assessment(execution='two',rubric='c',positive=False)
    labels,_=training_labels(metadata(first,negative));assert not labels['temporal']['mask']


def test_partial_negative_scope_remains_unknown():
    first=assessment(positive=False);second=assessment(execution='two',rubric='c',positive=False)
    row=metadata(first,second);row['holds']=[2,2]
    labels,_=training_labels(row);assert not labels['temporal']['mask']


def test_geometry_captures_motion_that_frame_means_cannot():
    frames=[]
    for x in (4,12):
        image=Image.new('RGBA',(32,32));ImageDraw.Draw(image).rectangle((x,8,x+7,15),fill=(90,110,150,255));frames.append(image)
    values=extract(frames,[2,2],loop=False,extractor='native-geometry-v2')['features']
    assert values.shape==(2,20)
    assert np.allclose(values[0,:6],values[1,:6])
    assert values[1,10]>values[0,10] and values[1,15]>0  # normalized centroid / displacement
    assert np.isfinite(values).all()


def test_geometry_wire_rejects_version_swaps_and_arbitrary_data():
    shard=geometry_shard();raw,manifest=preupload(shard)
    assert inspect_payload(raw)==shard and not manifest['contains_pixels']
    for update in ({'extractor':'native-numeric-v1'},{'schema_version':'feature-only-1.0'},{'prompt':'private'}):
        with pytest.raises(ValueError):inspect_payload(canonical(dict(shard.model_dump(),**update)))
    broken=shard.model_dump();broken['rows'][0]['category_weights'][0]=.99
    with pytest.raises(ValueError):inspect_payload(canonical(broken))


def test_repair_variants_do_not_inflate_independent_sequence_support():
    from framebound.v3.campaign.learning import eligibility
    rows=[]
    for index in range(320):
        row=geometry_shard(2).rows[0].model_dump()
        row.update(case_id=f'{index:064x}',split='train',family_id=f'{index//4:064x}',sequence_id=f'{index//4:064x}')
        rows.append(FeatureRowV2(**row))
    shard=FeatureShard(schema_version='feature-only-2.0',extractor='native-geometry-v2',rows=rows)
    assert eligibility(shard,['temporal'])['sequences']==80
    assert not eligibility(shard,['temporal'])['eligible']


def test_training_and_prediction_use_the_versioned_geometry_width():
    from framebound.v3.campaign.learning import fit,predict
    shard=geometry_shard()
    model=fit(shard,categories=['temporal'],engineering=True,steps=30)['checkpoint']
    assert len(model['mean'])==20
    assert predict(model,shard.rows[1])['scores']['temporal']>predict(model,shard.rows[0])['scores']['temporal']
    assert model['engineering_only']


def test_torch_profile_exercises_real_geometry_training_but_cannot_promote():
    pytest.importorskip('torch')
    from framebound.v3.campaign.learning import train_temporal_torch,predict
    shard=geometry_shard()
    result=train_temporal_torch(shard,categories=['temporal'],device='cpu',steps=2,profile_only=True)
    artifact=result['checkpoint']
    assert len(artifact['mean'])==20 and artifact['engineering_only']
    assert len(predict(artifact,shard.rows[0])['windows'])==2
    assert train_temporal_torch(shard,categories=['temporal'])['status']=='insufficient_support'


def test_credit_evidence_requires_current_aware_account_limits():
    from framebound.v3.campaign.compute_gate import CreditEvidence
    now=datetime.now(timezone.utc)
    values=dict(verified_at=now-timedelta(minutes=1),expires_at=now+timedelta(days=1),source='Engineering account fixture',
        restrictions='Feature-only test',available_microdollars=1000000,workspace_remaining_microdollars=1000000,net_spend_remaining_microdollars=0,pricing_source='Engineering pricing fixture',
        l4_microdollars_per_second=222,l40s_microdollars_per_second=542,cpu_microdollars_per_core_second=13.1,ram_microdollars_per_gib_second=2.22)
    assert CreditEvidence(**values).net_spend_remaining_microdollars==0
    with pytest.raises(ValueError,match='24 hours'):CreditEvidence(**dict(values,verified_at=now-timedelta(days=2)))
    with pytest.raises(ValueError,match='expired'):CreditEvidence(**dict(values,expires_at=now-timedelta(seconds=1)))


def test_modal_missing_study_never_reserves_or_calls_transport(tmp_path):
    from framebound.v3.campaign.remote import Job,submit
    from framebound.v3.campaign.learning import recipe
    config=mvp_curriculum();ledger=Ledger(tmp_path);ledger.plan(config)
    raw,_=preupload(geometry_shard());job=Job(payload_sha256=hashlib.sha256(raw).hexdigest(),
        recipe_sha256=digest(recipe('native-geometry-v2')),image_digest='sha256:'+'a'*64,purpose='profile',categories=['temporal'])
    with pytest.raises(ValueError,match='profile, account evidence'):
        submit(ledger,config.id,protocol(config)['rehearsal'][0],raw,job,lambda *_:pytest.fail('paid transport called'))
    assert ledger.status(config.id)['requests']==[]


def test_lifetime_modal_time_reservations_survive_new_campaigns(tmp_path):
    from framebound.v3.campaign.remote import Job
    ledger=Ledger(tmp_path)
    config=curriculum('engineering-time').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger.plan(config);ledger.fund(config.id,'modal',1000000,evidence='Engineering evidence')
    ids=[c.id for c in config.cases if c.stage=='pilot']
    job=Job(payload_sha256='a'*64,recipe_sha256='b'*64,image_digest='sha256:'+'c'*64)
    for cid in ids[:2]:ledger.reserve(config.id,cid,'train',dict(job=job.model_dump(mode='json')),quote=job.quote(),subsystem='modal')
    another=config.model_copy(update={'id':'engineering-time-2'});ledger.plan(another);ledger.fund(another.id,'modal',1000000,evidence='Engineering evidence')
    with pytest.raises(Stopped,match='wall allowance'):
        ledger.reserve(another.id,ids[2],'train',dict(job=job.model_dump(mode='json')),quote=job.quote(),subsystem='modal')


def test_rehearsal_receipts_unlock_pilot_without_rewriting_contract_or_spend(tmp_path):
    from test_campaign_runner import EngineeringSpecialist
    from framebound.v3.campaign.runner import Runner
    config=mvp_curriculum('engineering-mvp').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',config.api_ceiling,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='Engineering fixture',account_access='Synthetic authority',image_microdollars=10000))
    specialist=EngineeringSpecialist();runner=Runner(tmp_path,config.id,specialist)
    result=runner.run()
    assert len(result['results'])==12 and not result['deferred'],result['deferred']
    spent=ledger.status(config.id)['budgets']['api']['incurred'];sends=len(specialist.sends)
    original=canonical(ledger.config(config.id))
    released=release(tmp_path,config.id,dict(stage='pilot'))
    assert released==release(tmp_path,config.id,dict(stage='pilot'))
    assert len(admitted(ledger,config))==80
    assert canonical(ledger.config(config.id))==original
    assert ledger.status(config.id)['budgets']['api']['incurred']==spent
    assert len(specialist.sends)==sends
    assert set(protocol(config)['final']).isdisjoint(admitted(ledger,config))


def test_local_studies_reject_sealed_test_features(tmp_path):
    from framebound.v3.campaign.study import baseline
    shard=geometry_shard();data=shard.model_dump();data['rows'][-1]['split']='test'
    path=tmp_path/'sealed.json';path.write_bytes(canonical(FeatureShard.model_validate(data)))
    with pytest.raises(ValueError,match='sealed final-test'):
        baseline(tmp_path,'engineering',dict(feature_file='sealed.json',categories=['temporal']))


def test_near_duplicate_and_shared_conditioning_components_are_quarantined(tmp_path):
    from framebound.v3.campaign.leakage import exclusions
    image=Image.new('RGBA',(32,32));ImageDraw.Draw(image).ellipse((8,7,22,23),fill=(100,120,140,255));image.save(tmp_path/'a.png')
    artifact=dict(file='a.png',sha256=hashlib.sha256((tmp_path/'a.png').read_bytes()).hexdigest())
    examples=[dict(metadata=dict(id='one',family='first',split='train',frames=[artifact],conditioning=[])),
              dict(metadata=dict(id='two',family='second',split='validation',frames=[dict(artifact,sha256='f'*64)],conditioning=[]))]
    # Even a different file/byte identity cannot bypass similarity grouping.
    assert set(exclusions(examples,tmp_path))=={'one','two'}


def test_knowledge_retrieval_keeps_counterexamples_and_detects_changed_pixels(tmp_path):
    from framebound.v3.campaign.export import build
    from framebound.v3.campaign.knowledge import build as knowledge_build,retrieve
    from framebound.v3.campaign.advisory import select,query
    image=Image.new('RGBA',(32,32));ImageDraw.Draw(image).ellipse((8,7,22,23),fill=(100,120,140,255));image.save(tmp_path/'a.png')
    (tmp_path/'request.json').write_text('{"engineering":"fixture"}')
    first=assessment()
    example=dict(id='revision',sequence_id='sequence',family='family',split='train',frames=['a.png'],holds=[2],loop=False,
        request_file='request.json',conditioning_files=['a.png'],provenance={'source':'engineering'},assessment=first.model_dump(mode='json'),rights=['original'])
    dataset=build(tmp_path,'engineering',[example],version='v2')
    library=knowledge_build(tmp_path,'engineering',version='v2')
    assert library['entries']==1
    result=retrieve(tmp_path,'engineering',version='v2',categories=['temporal'])
    assert result['entries'][0]['counterexamples']=='Authored hold'
    assert not retrieve(tmp_path,'engineering',version='v2',categories=['temporal'],exclude_families=['family'])['entries']
    assert result['authority']=='advisory_only'
    entry=result['entries'][0]
    blob=__import__('pathlib').Path(dataset['path'])/entry['evidence_files'][0]['file'];blob.write_bytes(b'changed')
    with pytest.raises(ValueError,match='closure mismatch'):
        retrieve(tmp_path,'engineering',version='v2',categories=['temporal'])


def test_remote_replay_does_not_recheck_expired_account_or_repeat_send(tmp_path):
    from framebound.v3.campaign.remote import Job,execute_pure,submit
    from framebound.v3.campaign.learning import recipe
    config=curriculum('engineering-replay').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'modal',1000000,evidence='Synthetic authority')
    cid=next(c.id for c in config.cases if c.stage=='pilot')
    raw,_=preupload(geometry_shard());job=Job(payload_sha256=hashlib.sha256(raw).hexdigest(),
        recipe_sha256=digest(recipe('native-geometry-v2')),image_digest='sha256:'+'a'*64,purpose='profile',categories=['temporal'])
    row=ledger.reserve(config.id,cid,'train',dict(job=job.model_dump(mode='json'),study={}),quote=job.quote(),subsystem='modal')
    permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit)
    result=execute_pure(raw,job,lambda *_:dict(status='profile_only'))
    ledger.receive(row['id'],canonical(result),incurred=job.quote(),provider_receipt={'engineering':'receipt'})
    replayed=submit(ledger,config.id,cid,raw,job,lambda *_:pytest.fail('replayed paid work'),study=None)
    assert replayed['result']['result']['status']=='profile_only'
    assert len(ledger.status(config.id)['requests'])==1


def test_campaign_export_cannot_rehash_a_new_label_source_or_target(tmp_path):
    from framebound.v3.campaign.export import build,validate
    image=Image.new('RGBA',(16,16));ImageDraw.Draw(image).ellipse((4,4,11,11),fill='red');image.save(tmp_path/'a.png')
    (tmp_path/'request.json').write_text('{}')
    example=dict(id='revision',family='family',split='train',frames=['a.png'],holds=[2],loop=False,
        request_file='request.json',conditioning_files=[],provenance={'source':'engineering'},rights=['original'],assessment=assessment().model_dump(mode='json'))
    output=build(tmp_path,'engineering',[example],version='test')
    from pathlib import Path
    folder=Path(output['path']);file=folder/'detection.jsonl';row=json.loads(file.read_text())
    row['labels']['temporal']['target']=0
    file.write_bytes(canonical(row)+b'\n')
    manifest=json.loads((folder/'manifest.json').read_text());manifest['files']['detection.jsonl']=hashlib.sha256(file.read_bytes()).hexdigest()
    (folder/'manifest.json').write_bytes(canonical(manifest))
    with pytest.raises(ValueError,match='actual assessment'):
        validate(folder)


def test_representations_share_scoped_supervision_for_real_ablations():
    from framebound.v3.campaign.study import ablation
    row=geometry_shard().rows[0].model_dump();row['features']=[f[:8] for f in row['features']]
    numeric=FeatureShard(schema_version='feature-only-2.0',extractor='native-numeric-v1',rows=[FeatureRowV2(**row)])
    assert inspect_payload(canonical(numeric)).rows[0].category_weights==geometry_shard().rows[0].category_weights


def test_unknown_modal_outcome_blocks_replay_without_new_credit_or_send(tmp_path):
    from framebound.v3.campaign.remote import Job,submit
    from framebound.v3.campaign.learning import recipe
    config=curriculum('engineering-unknown').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'modal',1000000,evidence='Synthetic authority')
    cid=next(c.id for c in config.cases if c.stage=='pilot');raw,_=preupload(geometry_shard())
    job=Job(payload_sha256=hashlib.sha256(raw).hexdigest(),recipe_sha256=digest(recipe('native-geometry-v2')),
        image_digest='sha256:'+'a'*64,purpose='profile',categories=['temporal'])
    row=ledger.reserve(config.id,cid,'train',dict(job=job.model_dump(mode='json')),quote=job.quote(),subsystem='modal')
    permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit);ledger.unknown(row['id'],'Synthetic timeout')
    with pytest.raises(Stopped,match='unresolved'):
        submit(ledger,config.id,cid,raw,job,lambda *_:pytest.fail('unknown outcome resent'))
    assert ledger.status(config.id)['budgets']['modal']['reserved']==job.quote()


def test_opaque_acquisition_is_retained_without_inventing_a_white_key(tmp_path):
    from test_campaign_runner import EngineeringSpecialist
    from framebound.v3.campaign.runner import Runner
    config=mvp_curriculum('engineering-keyed').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config)
    runner=Runner(tmp_path,config.id,EngineeringSpecialist())
    import io
    stream=io.BytesIO();Image.new('RGB',(32,32),'white').save(stream,format='PNG');raw=stream.getvalue()
    with pytest.raises(ValueError,match='declared flat magenta'):
        runner._import_muse_media(raw,'engineering-white',declared_key=True)
    assert (tmp_path/f'campaigns/{config.id}/originals/{hashlib.sha256(raw).hexdigest()}.png').read_bytes()==raw


def test_advisory_cannot_influence_teacher_assessment(tmp_path,monkeypatch):
    from test_campaign_runner import EngineeringSpecialist
    from framebound.v3.campaign.runner import Runner
    from framebound.v3.campaign import advisory
    config=mvp_curriculum('engineering-blind').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',1000000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),
        source='Engineering fixture',account_access='Synthetic authority',image_microdollars=10000))
    marker='ADVISORY-MUST-NOT-LABEL-ITSELF'
    monkeypatch.setattr(advisory,'query',lambda *a,**k:dict(entries=[marker],authority='advisory_only'))
    specialist=EngineeringSpecialist();runner=Runner(tmp_path,config.id,specialist)
    runner.run(max_cases=1)
    assert any(marker in json.dumps(r) for r in specialist.sends if r['operation']=='repair')
    assert all(marker not in json.dumps(r) for r in specialist.sends if r['operation'] in {'diagnose','compare'})
    before=len(specialist.sends);runner.run(max_cases=1)
    # A bounded continuation progresses to another case, rather than replaying the first forever.
    assert len(specialist.sends)>before


def test_quarantine_preserves_known_acquisition_spend_and_never_resolves_unknown(tmp_path):
    from framebound.v3.campaign.progression import quarantine
    config=curriculum('engineering-quarantine').model_copy(update={'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',100000,evidence='Engineering authority')
    cid=next(c.id for c in config.cases if c.stage=='pilot')
    row=ledger.reserve(config.id,cid,'generate',{},quote=10000,images=1);permit=ledger.claim(row['id']);ledger.start_wire(row['id'],permit)
    folder=tmp_path/f'campaigns/{config.id}/reports';folder.mkdir()
    path=folder/'failure-test.json';path.write_bytes(canonical(dict(case_id=cid,error='ValueError',detail='Generated background is not the declared flat magenta key')))
    request=dict(case_id=cid,failure_report=str(path.relative_to(tmp_path)))
    ledger.unknown(row['id'],'Synthetic unknown send')
    with pytest.raises(Stopped,match='pending or unknown'):quarantine(tmp_path,config.id,request)
    ledger.receive(row['id'],b'engineering response',incurred=10000,successful_images=1,provider_receipt={'engineering':'received'})
    ledger.stop(config.id)
    result=quarantine(tmp_path,config.id,request)
    assert result['result']['outcome']=='rejected' and result['stopped']
    assert ledger.status(config.id)['budgets']['api']['incurred']==10000
    assert result==quarantine(tmp_path,config.id,request)


def test_acquisition_failure_export_moves_without_becoming_model_supervision(tmp_path):
    from framebound.v3.campaign.export import build,load,validate
    (tmp_path/'request.json').write_text('{"engineering":"failed source layout"}')
    (tmp_path/'received.json').write_text('{"engineering":"known provider receipt"}')
    failure=dict(id='failed',family='failed-family',split='train',result=dict(outcome='rejected'),
        request_file='request.json',provenance_files=['received.json'])
    output=build(tmp_path,'engineering',[],version='failure-only',acquisition_failures=[failure])
    from pathlib import Path
    folder=Path(output['path']);moved=tmp_path/'moved';folder.rename(moved)
    assert validate(moved)['ok']
    assert not load(moved,'detection')
    row=load(moved,'acquisition')[0]
    assert row['label_source']=='execution' and not row['metadata']['training_eligible']
    assert row['frames']==[] and not row['human_acceptance']


def test_local_compute_comparison_uses_fastest_successful_available_device(tmp_path,monkeypatch):
    torch=pytest.importorskip('torch')
    from framebound.v3.campaign import study
    shard=geometry_shard();(tmp_path/'features.json').write_bytes(canonical(shard))
    monkeypatch.setattr(torch.backends.mps,'is_available',lambda:True)
    clock=iter((0.,10.,20.,21.))
    from types import SimpleNamespace
    monkeypatch.setattr(study,'time',SimpleNamespace(monotonic=lambda:next(clock)))
    calls=[]
    def fake_train(shard,*,categories,device,profile_only):
        calls.append(device)
        return dict(checkpoint=dict(steps=200,seconds=10. if device=='cpu' else 1.,torch_version='engineering'))
    monkeypatch.setattr(study,'train_temporal_torch',fake_train)
    result=study.profile(tmp_path,'engineering',dict(feature_file='features.json',categories=['temporal']))
    assert calls==['cpu','mps'] and result['report']['device']=='mps'
    assert result['report']['wall_seconds']==1. and not result['report']['promoted']


def test_received_bad_key_is_negative_intake_and_quota_stops_fanout(tmp_path):
    import io,base64
    from test_campaign_runner import EngineeringSpecialist
    from framebound.v3.campaign.runner import Runner
    from framebound.v3.campaign.dispatch import Response
    config=mvp_curriculum('engineering-intake-quota');ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',1000000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='Engineering',
        account_access='Synthetic authority',image_microdollars=10000))
    class WrongKey(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            assert request['images'],'Bad intake must not receive paid semantic assessment'
            self.sends.append(request)
            image=Image.new('RGB',(64,64),'white');out=io.BytesIO();image.save(out,format='PNG')
            return Response(canonical(dict(status='completed',output=[dict(type='image_generation_call',result=base64.b64encode(out.getvalue()).decode())])),10000,1,{'engineering':'received'})
    specialist=WrongKey();result=Runner(tmp_path,config.id,specialist).run()
    assert len(specialist.sends)==4 and len(result['results'])==4
    assert result['status']['stopped'] and result['status']['cases']['rejected']==4
    assert result['status']['budgets']['api']['incurred']==40000
    assert result['status']['budgets']['api']['reserved']==0


def test_new_campaign_name_cannot_move_a_known_family_into_the_test_split(tmp_path):
    from framebound.v3.campaign.contracts import Campaign
    ledger=Ledger(tmp_path);original=curriculum('engineering-split-original');ledger.plan(original)
    value=original.model_dump();value['id']='engineering-split-renamed'
    family=value['cases'][0]['family']
    for case in value['cases']:
        if case['family']==family:case.update(split='test',stage='final')
    changed=Campaign.model_validate(value)
    with pytest.raises(ValueError,match='lifetime family'):
        ledger.plan(changed)


def test_plan_replay_preserves_a_frozen_legacy_curriculum(tmp_path):
    from framebound.v3.campaign.service import operate
    config=curriculum('engineering-historical');ledger=Ledger(tmp_path);ledger.plan(config)
    before=canonical(ledger.config(config.id))
    operate(tmp_path,'plan',campaign=config.id)
    assert canonical(ledger.config(config.id))==before


def test_closed_export_cannot_drop_a_hash_lane_and_keep_claiming_validity(tmp_path):
    from framebound.v3.campaign.export import build,validate
    output=build(tmp_path,'engineering',[],version='empty')
    from pathlib import Path
    folder=Path(output['path']);manifest=json.loads((folder/'manifest.json').read_text())
    manifest['files'].pop('detection.jsonl');(folder/'manifest.json').write_bytes(canonical(manifest))
    with pytest.raises(ValueError,match='objective lane'):validate(folder)


def test_private_reports_and_serialized_curricula_cannot_enter_git(tmp_path):
    import runpy
    from pathlib import Path
    audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check_private_boundary.py'))['audit']
    for name,value in [('readiness.json',dict(schema_version='knowledge-readiness-1.0')),
                       ('campaign.json',dict(schema_version='2.0',dataset_version='mvp-2',cases=[]))]:
        (tmp_path/name).write_bytes(canonical(value))
        assert audit(tmp_path,[name])==[name]
    (tmp_path/'schema.json').write_text('{"type":"object","properties":{"cases":{"type":"array"}}}')
    assert not audit(tmp_path,['schema.json'])


def test_frozen_final_artifacts_detect_changed_execution_sources(tmp_path):
    from framebound.v3.campaign.study import execution_sources,verify_frozen
    config=mvp_curriculum('engineering-final-freeze');ledger=Ledger(tmp_path);ledger.plan(config)
    files={};hashes={}
    for key in ('model','policy','prompts','preprocessing'):
        path=tmp_path/(key+'.json');path.write_text('{}');files[key]=path.name
        hashes[key]=hashlib.sha256(path.read_bytes()).hexdigest()
    detail=dict(execution_sources=execution_sources(),artifact_files=files,artifact_hashes=hashes,
                knowledge_version=None,knowledge_sha256=None)
    evidence=dict(config_sha256=digest(config),detail=detail)
    with ledger.db() as db:
        db.execute('INSERT INTO knowledge_releases(campaign,stage,cases,evidence,request) VALUES(?,?,?,?,?)',
            (config.id,'final','[]',canonical(evidence).decode(),'{}'))
    assert verify_frozen(tmp_path,config.id)==detail
    evidence['detail']['execution_sources']['features.py']='0'*64
    with ledger.db() as db:db.execute('UPDATE knowledge_releases SET evidence=? WHERE campaign=?',(canonical(evidence).decode(),config.id))
    with pytest.raises(ValueError,match='execution sources changed'):verify_frozen(tmp_path,config.id)


def test_zero_cash_limit_allows_applicable_credit_but_never_authorizes_cash():
    from framebound.v3.campaign.compute_gate import CreditEvidence,credit_capacity
    now=datetime.now(timezone.utc)
    credit=CreditEvidence(verified_at=now-timedelta(minutes=1),expires_at=now+timedelta(days=1),source='Engineering account evidence',
        restrictions='Credit only',available_microdollars=1000000,workspace_remaining_microdollars=2000000,
        net_spend_remaining_microdollars=0,pricing_source='Engineering prices',l4_microdollars_per_second=222,
        l40s_microdollars_per_second=542,cpu_microdollars_per_core_second=13.1,ram_microdollars_per_gib_second=2.22)
    assert credit_capacity(credit)==1000000
    assert credit_capacity(credit.model_copy(update={'available_microdollars':0,'net_spend_remaining_microdollars':2000000}))==0
    assert credit_capacity(credit.model_copy(update={'workspace_remaining_microdollars':0}))==0


def test_scoped_negative_examples_teach_counterexamples_without_inventing_defects(tmp_path):
    from framebound.v3.campaign.export import build
    from framebound.v3.campaign.knowledge import build as knowledge_build,retrieve
    image=Image.new('RGBA',(32,32));ImageDraw.Draw(image).ellipse((8,7,22,23),fill='blue');image.save(tmp_path/'a.png')
    (tmp_path/'request.json').write_text('{}')
    example=dict(id='negative',family='family',split='train',frames=['a.png'],holds=[2],loop=False,
        request_file='request.json',conditioning_files=[],provenance={'source':'engineering'},rights=['original'],
        assessment=assessment(positive=False).model_dump(mode='json'))
    build(tmp_path,'engineering',[example],version='closed')
    result=knowledge_build(tmp_path,'engineering',version='new-library',dataset_version='closed')
    assert result['entries']==1
    entry=retrieve(tmp_path,'engineering',version='new-library',categories=['temporal'])['entries'][0]
    assert entry['record_kind']=='assessed_negative' and entry['subject'] is None and entry['roi'] is None
    assert entry['expected'] is None and entry['proposed_correction'] is None
    assert not entry['human_acceptance'] and entry['slots']==[0]
