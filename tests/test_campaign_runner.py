import base64
import io
import json

from PIL import Image,ImageDraw

from framebound.v3.campaign.contracts import Prices,canonical,curriculum
from framebound.v3.campaign.dispatch import Response
from framebound.v3.campaign.ledger import Ledger
from framebound.v3.campaign.runner import Runner
from framebound.v3.campaign.assessment import CATEGORIES


class EngineeringSpecialist:
    def __init__(self): self.sends=[]
    def execute(self,request,*,timeout):
        self.sends.append(request)
        op=request['operation']
        if request['images']:
            image=Image.new('RGBA',(96,64) if op!='anchor' else (64,64))
            draw=ImageDraw.Draw(image)
            for slot in range(6 if op!='anchor' else 1):
                x=slot%3*32 if op!='anchor' else 0;y=slot//3*32 if op!='anchor' else 0
                draw.rectangle((x+8,y+8,x+24,y+24),fill=(50,60,70,255))
            stream=io.BytesIO();image.save(stream,format='PNG')
            body=dict(status='completed',output=[dict(type='image_generation_call',result=base64.b64encode(stream.getvalue()).decode())])
        else:
            if op=='diagnose':
                coverage=[dict(category=c,status='absent_within_assessed_scope',slots=list(range(6)),limitations='Synthetic engineering coverage') for c in CATEGORIES]
                findings=[]
                if request['attempt']<2:
                    coverage[1]['status']='present';coverage[1]['slots']=[0]
                    findings=[dict(id='f',category='parts',slots=[0],tick_range=[0,2],subject='actor',severity='material',visibility='supported',
                        observed='Engineering inserted defect',expected='Engineering correction',counterexamples='Test-only observation, no real Muse evidence')]
                text=dict(coverage=coverage,findings=findings)
            else:text=dict(preference='tie',target_improved=False,material_regression=False,evidence='Synthetic tie',assessed_categories=['parts'])
            body=dict(status='completed',output=[dict(type='output_text',text=json.dumps(text))])
        return Response(canonical(body),request['quote'],int(request['images']>0),dict(response_id='TEST-ONLY-'+str(len(self.sends)),observed_model=request['payload']['requested_model']))


def test_single_anchor_wire_preserves_key_and_separates_animation(tmp_path):
    from datetime import datetime,timezone
    from framebound.v3.campaign.curriculum import upskill_curriculum,protocol
    config=upskill_curriculum('single-anchor-fixture',source_policy='single-anchor-keyed-v2')
    ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',2000000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),
        source='synthetic engineering rate evidence',account_access='test fixture',image_microdollars=10000))
    cid=protocol(config)['rehearsal'][0]
    class StreamingFixture(EngineeringSpecialist):
        def execute_stream(self,request,*,timeout,on_acceptance,on_observation):
            return self.execute(request,timeout=timeout)
    specialist=StreamingFixture();runner=Runner(tmp_path,config.id,specialist)
    result=runner.run(max_cases=1,case_ids=[cid])
    assert not result['status']['stopped'],result.get('deferred')
    anchor=next(q for q in specialist.sends if q['operation']=='anchor')
    anchor_text=anchor['payload']['wire']['input'][0]['content'][0]['text']
    assert 'exactly ONE' in anchor_text and 'ANIMATION EXERCISE:' not in anchor_text
    generated=next(q for q in specialist.sends if q['operation']=='generate')
    content=generated['payload']['wire']['input'][0]['content']
    assert 'x=128..383' in content[0]['text'] and 'ANIMATION EXERCISE:' in content[0]['text']
    image_item=next(c for c in content if c['type']=='input_image')
    with Image.open(io.BytesIO(base64.b64decode(image_item['image_url'].split(',',1)[1]))) as im:
        assert im.convert('RGBA').getpixel((0,0))==(255,0,255,255)
    derivation=generated['payload']['conditioning_derivations'][0]
    assert derivation['alpha_backdrop']['operator']=='explicit-conditioning-key-backdrop-v1'
    assert derivation['source_sha256']!=derivation['output_sha256']
    diagnose=next(q for q in specialist.sends if q['operation']=='diagnose')
    teacher_text=diagnose['payload']['wire']['input'][0]['content'][0]['text']
    assert 'end_exclusive' in teacher_text and 'nonempty limitations' in teacher_text
    sent=len(specialist.sends);runner.run(max_cases=1,case_ids=[cid])
    assert len(specialist.sends)==sent


def configured(tmp_path):
    config=curriculum('engineering')
    case=next(c for c in config.cases if c.stage=='pilot' and len(c.holds)==6)
    config=config.model_copy(update={'cases':[case],'prices':Prices(verified_at='engineering',source='test-only')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',1000000,evidence='synthetic engineering authority')
    return config,case


def test_unattended_repair_retains_tie_and_replay_sends_nothing(tmp_path):
    config,case=configured(tmp_path);specialist=EngineeringSpecialist();runner=Runner(tmp_path,config.id,specialist)
    result=runner.run()
    assert result['results'][case.id]['outcome']=='unchanged',result
    assert len(specialist.sends)==7 # anchor, base, two diagnoses, repair, diagnosis, comparison
    assert runner.run()['results'][case.id]['outcome']=='unchanged'
    assert len(specialist.sends)==7
    assert not result['status']['budgets']['api']['reserved']


def test_crash_after_comparison_before_terminal_commit_does_not_send_again(tmp_path,monkeypatch):
    config,case=configured(tmp_path);specialist=EngineeringSpecialist();runner=Runner(tmp_path,config.id,specialist)
    original=runner.ledger.finish_case
    def crash(*args,**kwargs): raise RuntimeError('injected before terminal commit')
    monkeypatch.setattr(runner.ledger,'finish_case',crash)
    first=runner.run();assert first['status']['stopped']
    count=len(specialist.sends)
    monkeypatch.setattr(runner.ledger,'finish_case',original)
    runner.ledger.resume(config.id)
    result=runner.run()
    assert result['results'][case.id]['outcome']=='unchanged',result
    assert len(specialist.sends)==count


def test_workflow_exports_close_actual_receipts_and_failed_candidate(tmp_path):
    from framebound.v3.campaign.export import export_campaign,validate
    config,case=configured(tmp_path);runner=Runner(tmp_path,config.id,EngineeringSpecialist())
    runner.run()
    result=export_campaign(tmp_path,config.id)
    assert validate(result['path'])['ok']
    assert result['manifest']['counts']['detection']==2
    assert result['manifest']['counts']['editing']==0
    rows=[json.loads(line) for line in (__import__('pathlib').Path(result['path'])/'detection.jsonl').read_text().splitlines()]
    assert all(row['provenance_artifacts'] for row in rows)


def test_crash_during_materialization_reconsumes_original_paid_result(tmp_path,monkeypatch):
    config,case=configured(tmp_path);specialist=EngineeringSpecialist();runner=Runner(tmp_path,config.id,specialist)
    original=runner._save;injected=[False]
    def crash(area,name,raw):
        if area=='canonical' and not injected[0]:
            injected[0]=True;raise RuntimeError('injected before native import completes')
        return original(area,name,raw)
    monkeypatch.setattr(runner,'_save',crash)
    assert runner.run()['status']['stopped']
    assert len(specialist.sends)==2
    runner.ledger.resume(config.id)
    result=runner.run()
    assert result['results'][case.id]['outcome']=='unchanged',result
    assert sum(r['operation']=='generate' for r in specialist.sends)==1


def test_historical_split_names_preserve_test_and_exclude_unsplit():
    from framebound.v3.campaign.replay import historical_split
    assert historical_split('dev')=='train'
    assert historical_split('test')=='test'
    assert historical_split('held_out')=='test'
    assert historical_split('unsplit') is None


def test_webp_provider_outputs_are_normalized_without_regeneration(tmp_path):
    import hashlib
    from framebound.v2 import storage as S
    config,case=configured(tmp_path)
    class WebPSpecialist(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            response=super().execute(request,timeout=timeout)
            if not request['images']:return response
            body=json.loads(response.raw);item=body['output'][0]
            with Image.open(io.BytesIO(base64.b64decode(item['result']))) as image:
                stream=io.BytesIO();image.convert('RGBA').save(stream,format='WEBP',lossless=True)
            item['result']=base64.b64encode(stream.getvalue()).decode()
            return Response(canonical(body),response.incurred,response.successful_images,response.receipt)
    specialist=WebPSpecialist();runner=Runner(tmp_path,config.id,specialist)
    result=runner.run()
    assert result['results'][case.id]['outcome']=='unchanged',result
    assert len(specialist.sends)==7
    with runner.ledger.db() as db:anchor_id=db.execute("SELECT id FROM requests WHERE operation='anchor'").fetchone()[0]
    raw,_=runner.ledger.artifact(anchor_id)
    original=base64.b64decode(json.loads(raw)['output'][0]['result'])
    assert S.blob_path(runner.project,hashlib.sha256(original).hexdigest()).read_bytes()==original
    with S.connect(runner.project) as con:
        assets=[json.loads(row['data']) for row in con.execute('SELECT data FROM assets')]
    assert any(a['mime']=='image/webp' and a['source_kind']=='generated' for a in assets)
    assert any(a['derivation'].get('operator')=='muse-source-to-png-v1' for a in assets)
    runner.run();assert len(specialist.sends)==7


def test_incomplete_diagnosis_gets_one_recheck_without_new_artwork(tmp_path):
    config,case=configured(tmp_path)
    class IncompleteSpecialist(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            if request['operation']=='diagnose' and request['attempt']==0:
                self.sends.append(request)
                return Response(canonical(dict(status='incomplete',incomplete_details={'reason':'max_output_tokens'},output=[])),1000,0,{'id':'test-incomplete'})
            if request['operation']=='recheck':
                assert request['payload']['wire']['reasoning']=={'effort':'low'}
                assert request['payload']['wire']['max_output_tokens']==8192
                self.sends.append(request)
                coverage=[dict(category=c,status='uncertain',slots=list(range(6)),limitations='Synthetic uncertainty') for c in CATEGORIES]
                body=dict(status='completed',output=[dict(type='output_text',text=json.dumps(dict(coverage=coverage,findings=[])))])
                return Response(canonical(body),1000,0,{'id':'test-recheck'})
            return super().execute(request,timeout=timeout)
    specialist=IncompleteSpecialist();runner=Runner(tmp_path,config.id,specialist)
    result=runner.run()
    assert result['results'][case.id]['outcome']=='ambiguous',result
    assert sum(r['operation']=='recheck' for r in specialist.sends)==1
    assert sum(r['operation']=='generate' for r in specialist.sends)==1
    count=len(specialist.sends);runner.run();assert len(specialist.sends)==count


def test_inconsistent_teacher_labels_are_quarantined_without_paid_retries(tmp_path):
    config,case=configured(tmp_path)
    class InvalidTeacher(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            response=super().execute(request,timeout=timeout)
            if request['images']:return response
            body=json.loads(response.raw);text=json.loads(body['output'][0]['text'])
            text['findings'][0]['roi']=[0,0,999,999]
            body['output'][0]['text']=json.dumps(text)
            return Response(canonical(body),response.incurred,0,response.receipt)
    specialist=InvalidTeacher();runner=Runner(tmp_path,config.id,specialist);result=runner.run()
    assert result['results'][case.id]['outcome']=='ambiguous',result
    assert len(specialist.sends)==3
    assert list((runner.folder/'annotations').glob('*-quarantine.json'))
    assert not result['status']['stopped']


def test_empty_negative_scope_is_masked_without_losing_other_coverage(tmp_path):
    config,case=configured(tmp_path)
    class ScopedTeacher(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            response=super().execute(request,timeout=timeout)
            if request['images']:return response
            body=json.loads(response.raw);text=json.loads(body['output'][0]['text'])
            text['findings']=[];text['coverage'][1]['status']='uncertain'
            text['coverage'][2]['slots']=[]
            body['output'][0]['text']=json.dumps(text)
            return Response(canonical(body),response.incurred,0,response.receipt)
    runner=Runner(tmp_path,config.id,ScopedTeacher());result=runner.run()
    a=result['results'][case.id]['after_assessment']
    coverage={c['category']:c['status'] for c in a['coverage']}
    assert coverage['identity']=='absent_within_assessed_scope'
    assert coverage['prop']=='not_assessed'
    assert coverage['extraction']=='not_assessed'


def test_six_pose_operation_gate_retains_semantic_uncertainty(tmp_path):
    from framebound.v3.campaign.runner import enable_long_sequences
    import pytest
    config=curriculum('engineering')
    cases=[c for c in config.cases if c.stage=='pilot' and len(c.holds)==6][:2]
    config=config.model_copy(update={'cases':cases,'prices':Prices(verified_at='engineering',source='test-only')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',2000000,evidence='synthetic engineering authority')
    result=Runner(tmp_path,config.id,EngineeringSpecialist()).run()
    assert len(result['results'])==2
    path=tmp_path/'campaigns/engineering/capabilities/long-sequences.json'
    assert path.is_file()
    gate=json.loads(path.read_text())
    assert len(gate['evidence'])==2
    assert 'longer sequence attempts still require measured boundaries' in gate['meaning']
    assert all(result['outcome'] in {'unchanged','ambiguous'} for result in result['results'].values())


def test_later_corroborated_finding_drives_repair(tmp_path):
    config,case=configured(tmp_path)
    class MultipleTargets(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            response=super().execute(request,timeout=timeout)
            if request['operation']!='diagnose' or request['attempt']!=0:return response
            body=json.loads(response.raw);text=json.loads(body['output'][0]['text'])
            unmatched=dict(text['findings'][0],id='a-unmatched',subject='Different actor')
            text['findings'].insert(0,unmatched);body['output'][0]['text']=json.dumps(text)
            return Response(canonical(body),response.incurred,response.successful_images,response.receipt)
    specialist=MultipleTargets();runner=Runner(tmp_path,config.id,specialist);result=runner.run()
    assert result['results'][case.id]['outcome']=='unchanged',result
    assert result['results'][case.id]['corroboration']['eligible_finding_ids']==['f']
    assert sum(r['operation']=='repair' for r in specialist.sends)==1

def test_opaque_generation_is_rejected_before_any_paid_semantic_assessment(tmp_path):
    config,case=configured(tmp_path)
    class Opaque(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            response=super().execute(request,timeout=timeout)
            if not request['images']:raise AssertionError('intake must run before diagnosis')
            im=Image.new('RGBA',(64,64) if request['operation']=='anchor' else (96,64),'white');out=io.BytesIO();im.save(out,format='PNG')
            return Response(canonical(dict(status='completed',output=[dict(type='image_generation_call',result=base64.b64encode(out.getvalue()).decode())])),response.incurred,1,response.receipt)
    specialist=Opaque();result=Runner(tmp_path,config.id,specialist).run()
    assert result['results'][case.id]['outcome']=='rejected'
    assert [r['operation'] for r in specialist.sends]==['anchor','generate']


def test_portable_campaign_keeps_declared_family_ancestry(tmp_path):
    from framebound.v3.campaign.export import export_campaign,load
    config=curriculum('engineering-ancestry')
    case=next(c for c in config.cases if c.stage=='pilot' and len(c.holds)==6)
    case=case.model_copy(update={'ancestry':['declared-source-family']})
    config=config.model_copy(update={'cases':[case],'prices':Prices(verified_at='engineering',source='synthetic')})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',1000000,evidence='Engineering authority')
    Runner(tmp_path,config.id,EngineeringSpecialist()).run()
    output=export_campaign(tmp_path,config.id,version='ancestry')
    rows=load(output['path'])
    assert rows and all(row['metadata']['ancestry']==['declared-source-family'] for row in rows)


def test_invalid_comparator_scope_abstains_without_paid_retry_or_preference_label(tmp_path):
    import pytest
    from framebound.v3.campaign.repair import Comparison,comparison_output_schema
    from framebound.v3.campaign.export import export_campaign
    config,case=configured(tmp_path)
    class InvalidComparator(EngineeringSpecialist):
        def execute(self,request,*,timeout):
            response=super().execute(request,timeout=timeout)
            if request['operation']!='compare':return response
            body=json.loads(response.raw);value=json.loads(body['output'][0]['text'])
            value.update(preference='B',target_improved=True,material_regression=False,
                         assessed_categories=['parts: apparent repair'])
            body['output'][0]['text']=json.dumps(value)
            return Response(canonical(body),response.incurred,0,response.receipt)
    specialist=InvalidComparator();runner=Runner(tmp_path,config.id,specialist)
    result=runner.run();assert result['results'][case.id]['outcome']=='ambiguous'
    assert not result['status']['stopped'] and len(specialist.sends)==7
    from framebound.v3.services import loop
    con=loop.connect(runner.project)
    try:rows=[json.loads(r[0]) for r in con.execute('SELECT data FROM agent_auto_comparisons')]
    finally:con.close()
    comparison=rows[0]['comparison']
    assert comparison['preference']=='insufficient_evidence' and comparison['target_improved'] is None
    assert comparison['material_regression'] is None and comparison['assessed_categories']==[]
    assert rows[0]['outcome']=='ambiguous'
    run_id=runner.ledger.progress(config.id,case.id)['data']['run_id']
    assert loop.get(runner.project,run_id)['learned_coverage_status']=='comparison_abstained'
    with pytest.raises(ValueError):Comparison(**dict(comparison,preference='tie'))
    schema=comparison_output_schema()
    assert 'provenance' not in schema['properties'] and 'assignment_sha256' not in schema['properties']
    assert list((runner.folder/'annotations').glob('*-comparison-quarantine.json'))
    runner.run();assert len(specialist.sends)==7
    exported=export_campaign(tmp_path,config.id,version='invalid-comparison')
    preferences=[json.loads(line) for line in (__import__('pathlib').Path(exported['path'])/'preference.jsonl').read_text().splitlines()]
    assert preferences and all(not row['binary_training_eligible'] for row in preferences)
    assert exported['manifest']['counts']['editing']==0


def test_changed_advice_cannot_rewrite_received_repair_provenance(tmp_path,monkeypatch):
    import hashlib
    from framebound.v3.campaign.curriculum import mvp_curriculum,protocol
    from datetime import datetime,timezone
    from framebound.v3.services import loop
    config=mvp_curriculum('advice-replay-fixture');ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',2000000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),
        source='Engineering fixture',account_access='Synthetic authority',image_microdollars=10000))
    cid=next(c.id for c in config.cases if c.id in protocol(config)['rehearsal'])
    specialist=EngineeringSpecialist();runner=Runner(tmp_path,config.id,specialist)
    finish=runner.ledger.finish_case
    monkeypatch.setattr(runner.ledger,'finish_case',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Synthetic terminal-commit interruption')))
    assert runner.run(max_cases=1,case_ids=[cid])['status']['stopped']
    received=[r for r in runner.ledger.status(config.id)['requests'] if r['operation']=='repair'];assert received
    request=json.loads(runner.ledger.request(received[0]['id'])['request'])
    expected=hashlib.sha256(request['payload']['wire']['input'][0]['content'][0]['text'].encode()).hexdigest()
    from framebound.v3.campaign.contracts import digest
    revision_id='revision-'+digest([config.id,cid,'repair',0])[:40]
    before=loop.revision_get(runner.project,revision_id)['revision']
    sent=len(specialist.sends)
    monkeypatch.setattr('framebound.v3.campaign.advisory.query',lambda *a,**k:dict(authority='advisory_only',entries=['NEW ENGINEERING ADVICE']))
    monkeypatch.setattr(runner.ledger,'finish_case',finish);runner.ledger.resume(config.id)
    result=runner.run(max_cases=1,case_ids=[cid])
    assert not result['status']['stopped'] and result['results'][cid]['outcome']=='unchanged',result.get('deferred')
    assert len(specialist.sends)==sent
    after=loop.revision_get(runner.project,revision_id)['revision']
    assert after==before
    assert after['generation_metadata']['provenance']['generations'][0]['prompt_sha256']==expected
