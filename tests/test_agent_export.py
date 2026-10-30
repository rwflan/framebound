import json
import shutil

import pytest

from framebound.v2.exports import build_snapshot,validate_snapshot
from framebound.v2.exports.agent_snapshot import preview
from framebound.v3.services import loop,interventions as I,tasks
from framebound.v2.services.authz import Actor
from test_agent_loop import setup,import_frames

POLICY={'include_automatically_verified':True,'include_procedural_positives':True,'agent_export_policy':'agent-training-v1'}


def test_reference_free_trajectory_exports_moves_and_keeps_label_sources(tmp_path):
    source=tmp_path/'project';source.mkdir()
    project,spec,good=setup(source)
    bad=import_frames(source,'bad',{'kind':'flicker'})
    failed=loop.submit(project,'run','bad',bad)
    loop.submit(project,'run','good',good,parent_revision_id='bad',feedback_id=failed['id'])
    counts=preview(project,['good'],POLICY)
    assert counts['counts']['human_accepted']==0
    assert counts['counts']['automatically_verified']==3
    assert counts['counts']['research']==3
    out=tmp_path/'snapshot'
    manifest=build_snapshot(project,'agent',['good'],str(out),POLICY)
    assert manifest['dataset_version']=='3.0'
    assert manifest['counts']['positives']==0 and manifest['counts']['automatically_verified']==3
    assert manifest['counts']['preferences']==0 and manifest['counts']['trajectories']==1
    assert validate_snapshot(str(out))['ok'],validate_snapshot(str(out))['issues']
    moved=tmp_path/'moved';out.rename(moved);shutil.rmtree(source)
    report=validate_snapshot(str(moved))
    assert report['ok'],report['issues']
    assert (moved/'hf/metadata.jsonl').read_text()==''
    auto=[json.loads(line) for line in (moved/'automatically_verified/metadata.jsonl').read_text().splitlines()]
    assert {r['label_source'] for r in auto}=={'technical_policy'}
    assert {r['creative_status'] for r in auto}=={'unreviewed'}
    temporal=[json.loads(line) for line in (moved/'temporal.jsonl').read_text().splitlines()]
    assert all(row['generation_metadata'] is None for row in temporal)
    cond=json.loads((moved/'closure/conditioning.json').read_text())
    assert cond['motion_guides']=={} and cond['tasks']['task']['spec']['inputs']==[]
    # An old reviewed-guide preference reader must reject the new semantics.
    from framebound.v2.exports.dpo_adapter import load_preferences
    with pytest.raises(ValueError,match='label semantics'):load_preferences(moved)


def test_unresolved_human_correction_withholds_auto_and_exact_acceptance_is_positive(tmp_path):
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    loop.submit(project,'run','good',good)
    human=Actor(type='reviewer',id='human')
    mark=I.mark(project,human,'run',dict(id='subjective',revision_id='good',evaluation_id='evaluation:good',tick_range=[0,2],desired_outcome='Clarify the face.'))
    pending=preview(project,['good'],POLICY)
    assert pending['counts']['human_accepted']==pending['counts']['automatically_verified']==0
    loop.submit(project,'run','replacement',good,parent_revision_id='good',feedback_id=mark['handoff_id'])
    current=I.get(project,'subjective')
    I.resolve(project,human,'subjective',dict(expected_version=current['version'],revision_id='replacement',evaluation_id='evaluation:replacement'))
    I.decision(project,human,'run',dict(id='exact',revision_id='replacement',evaluation_id='evaluation:replacement',action='approve',note='Exact replacement reviewed.'))
    out=tmp_path/'accepted'
    manifest=build_snapshot(project,'accepted',['replacement'],str(out),POLICY)
    assert manifest['counts']['positives']==3 and manifest['counts']['preferences']==0
    report=validate_snapshot(str(out));assert report['ok'],report['issues']
    events=[json.loads(line) for line in (out/'closure/events.jsonl').read_text().splitlines()]
    assert any(e['event']=='resolve_issue' and e['source']=='human' for e in events)
    assert any(e['event']=='approve' and e['revision_id']=='replacement' for e in events)


def test_rights_excluded_pixels_are_explicitly_withheld(tmp_path):
    from framebound.v2.services.assets import import_asset
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    import_asset(project,str(source/'good-1.png'),'restricted',rights='unknown',source_kind='procedural')
    loop.submit(project,'run','restricted',[good[0],'restricted',good[2]])
    out=tmp_path/'restricted-export'
    manifest=build_snapshot(project,'restricted',['restricted'],str(out),POLICY)
    assert manifest['counts']['positives']==manifest['counts']['automatically_verified']==0
    assert manifest['counts']['withheld']==1
    report=validate_snapshot(str(out));assert report['ok'],report['issues']
    withheld=json.loads((out/'closure/withheld.json').read_text())
    assert withheld==[{'asset_id':'restricted','reason':'rights_not_permitted'}]


def _resign(snapshot,changed):
    from framebound.v3.evaluate import digest
    from framebound.v2.exports.snapshot import _h
    manifest=json.loads((snapshot/'manifest.json').read_text())
    for rel in changed:manifest['files'][rel]=_h((snapshot/rel).read_bytes())
    (snapshot/'manifest.json').write_text(json.dumps(manifest))
    complete=json.loads((snapshot/'COMPLETE').read_text());complete['manifest_sha256']=_h((snapshot/'manifest.json').read_bytes())
    (snapshot/'COMPLETE').write_text(json.dumps(complete))


def test_validator_rejects_fabricated_human_label_even_with_rehashed_files(tmp_path):
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    loop.submit(project,'run','good',good)
    out=tmp_path/'snapshot';build_snapshot(project,'tamper',['good'],str(out),POLICY)
    # Move a technical label into the human view and recompute the container hashes.
    membership=[json.loads(line) for line in (out/'membership.jsonl').read_text().splitlines()]
    for row in membership:row['view']='human_accepted';row['label_source']='human'
    (out/'membership.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in membership))
    rows=[json.loads(line) for line in (out/'automatically_verified/metadata.jsonl').read_text().splitlines()]
    for row in rows:
        row['view']='human_accepted';row['label_source']='human'
        (out/'hf'/row['file_name']).parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(out/'automatically_verified'/row['file_name'],out/'hf'/row['file_name'])
    (out/'hf/metadata.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));(out/'automatically_verified/metadata.jsonl').write_text('')
    manifest=json.loads((out/'manifest.json').read_text());manifest['counts']['positives']=3;manifest['counts']['automatically_verified']=0
    for p in (out/'hf').rglob('*.png'):
        from framebound.v2.exports.snapshot import _h
        manifest['files'][str(p.relative_to(out))]=_h(p.read_bytes())
    (out/'manifest.json').write_text(json.dumps(manifest))
    _resign(out,['membership.jsonl','hf/metadata.jsonl','automatically_verified/metadata.jsonl'])
    report=validate_snapshot(str(out))
    assert not report['ok'] and any('invented or stale human positive' in r for r in report['issues'])


def test_family_safe_splits_include_related_runs_and_policy_rejects_weak_booleans(tmp_path):
    source=tmp_path/'project';source.mkdir();project,spec,good=setup(source)
    loop.submit(project,'run','first',good)
    spec['id']='other-task';spec['animation_id']='other';tasks.create(project,spec);loop.start(project,'other-task','other-run')
    loop.submit(project,'other-run','second',good)
    policy=dict(POLICY,split={'train':['first'],'dev':['second'],'test':[]},split_policy='strict')
    with pytest.raises(ValueError,match='straddles'):preview(project,['first','second'],policy)
    policy['split_policy']='exclude'
    planned=preview(project,['first','second'],policy)
    assert planned['counts']['automatically_verified']==0
    assert any('family_split_conflict' in e['reasons'] for e in planned['exclusions'])
    with pytest.raises(ValueError,match='boolean'):preview(project,['first'],dict(POLICY,include_automatically_verified='false'))


def test_versioned_consumer_materializes_only_requested_label_view(tmp_path):
    from framebound.v2.exports.agent_reader import load_examples
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    loop.submit(project,'run','good',good)
    out=tmp_path/'snapshot';build_snapshot(project,'consume',['good'],str(out),POLICY)
    assert load_examples(out,'human_accepted')==[]
    batch=load_examples(out,'automatically_verified')
    assert len(batch)==3 and batch[0]['image'].size==(8,8)
    assert batch[0]['metadata']['label_source']=='technical_policy'
    with pytest.raises(ValueError,match='label semantics'):load_examples(out,'automatically_verified',supported_versions=('2.3',))


def test_public_manual_export_selection_and_replay(tmp_path):
    from fastapi.testclient import TestClient
    from framebound.v2.api.app import create_app
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    loop.submit(project,'run','good',good)
    client=TestClient(create_app(project))
    selection=dict(name='manual',run_ids=['run'],include_automatically_verified=True,include_procedural_positives=True)
    planned=client.post('/v3/exports/preview',json=selection)
    assert planned.status_code==200,planned.text
    assert planned.json()['counts']['automatically_verified']==3
    exported=client.post('/v3/exports',json=selection)
    assert exported.status_code==200,exported.text
    assert exported.json()['validation']['ok']
    assert client.post('/v3/exports',json=selection).json()==exported.json()
    assert '3.0' in client.get('/v3/reader-capabilities').json()['dataset_versions']
    assert client.post('/v3/exports/preview',json=dict(selection,include_automatically_verified='false')).status_code==422


def test_conditioning_inputs_and_derived_restrictions_remain_portable(tmp_path):
    from framebound.v2 import storage as S
    from framebound.v2.services.assets import import_asset
    source=tmp_path/'project';source.mkdir();project,spec,good=setup(source)
    import_asset(project,str(source/'good-0.png'),'identity',source_kind='procedural')
    spec['id']='with-identity';spec['animation_id']='identity-task'
    spec['inputs']=[dict(asset_id='identity',role='identity',provenance='procedural appearance proposal',designated_by='parent-agent',basis='proposed anchor, not a motion guide')]
    tasks.create(project,spec);loop.start(project,'with-identity','identity-run')
    loop.submit(project,'identity-run','identity-output',good)
    out=tmp_path/'with-input'
    build_snapshot(project,'input',['identity-output'],str(out),POLICY)
    asset_files=json.loads((out/'closure/asset_files.json').read_text())
    assert 'identity' in asset_files and (out/asset_files['identity']).is_file()
    report=validate_snapshot(str(out));assert report['ok'],report['issues']
    # Independent generated job provenance cannot turn restricted ancestry into a positive.
    import_asset(project,str(source/'good-1.png'),'restricted-parent',rights='unknown',source_kind='original')
    from framebound.v2.domain import Asset
    con=S.connect(project)
    original,_=S.get(con,'assets',good[1])
    derived=Asset.model_validate(dict(original,id='derived',source_kind='derived',parent_asset_ids=['restricted-parent'],rights='original'))
    S.insert(con,derived);con.close()
    spec['id']='derived-task';spec['animation_id']='derived';spec['inputs']=[]
    tasks.create(project,spec);loop.start(project,'derived-task','derived-run')
    loop.submit(project,'derived-run','derived-output',[good[0],'derived',good[2]])
    planned=preview(project,['derived-output'],POLICY)
    assert any('derivation_parent_excluded' in e['reasons'] for e in planned['exclusions'])


def test_human_and_automatic_sources_share_snapshot_without_inferred_preferences(tmp_path):
    source=tmp_path/'project';source.mkdir();project,spec,good=setup(source)
    loop.submit(project,'run','automatic',good)
    spec['id']='human-task';spec['animation_id']='human';tasks.create(project,spec);loop.start(project,'human-task','human-run')
    loop.submit(project,'human-run','human-result',good)
    I.decision(project,Actor(type='reviewer',id='human'),'human-run',dict(id='human-approval',revision_id='human-result',evaluation_id='evaluation:human-result',action='approve'))
    out=tmp_path/'mixed';manifest=build_snapshot(project,'mixed',['automatic','human-result'],str(out),POLICY)
    assert manifest['counts']['positives']==manifest['counts']['automatically_verified']==3
    assert manifest['counts']['preferences']==0
    report=validate_snapshot(str(out));assert report['ok'],report['issues']


def test_provider_origin_is_retained_and_hidden_settings_are_not_exported(tmp_path):
    from framebound.v2 import domain as D,storage as S
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    con=S.connect(project)
    job=D.Job(id='source-job',kind='generation',status='succeeded',idempotency_key='source-job',payload_sha256='a'*64,
        provider='fixture',origin='simulated-transport',provider_settings={'api_key':'sensitive-do-not-export'},
        request_brief={'prompt':'Authored fixture generation brief','authorization_token':'private-token'})
    S.insert(con,job)
    original,_=S.get(con,'assets',good[1])
    output=D.Asset.model_validate(dict(original,id='provider-output',source_job_id=job.id,origin='generated',source_kind='generated'))
    S.insert(con,output);con.close()
    loop.submit(project,'run','simulated',[good[0],'provider-output',good[2]])
    out=tmp_path/'simulated';manifest=build_snapshot(project,'simulated',['simulated'],str(out),POLICY)
    assert manifest['counts']['automatically_verified']==2
    provider=(out/'closure/provider_sources.jsonl').read_text()
    assert 'simulated-transport' in provider and 'Authored fixture generation brief' in provider
    assert 'sensitive-do-not-export' not in provider and 'private-token' not in provider
    assert '[redacted]' in provider
    report=validate_snapshot(str(out));assert report['ok'],report['issues']


def test_validator_remeasures_evidence_even_after_container_resigning(tmp_path):
    from framebound.v3.evaluate import digest
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    loop.submit(project,'run','good',good)
    out=tmp_path/'snapshot';build_snapshot(project,'evidence',['good'],str(out),POLICY)
    path=out/'closure/evaluations.jsonl'
    evaluation=json.loads(path.read_text())
    observed=next(r for r in evaluation['results'] if r['id']=='feature-1')
    observed['observed']=200
    # JSON decoding creates independent lists; mutate both recorded representations.
    next(r for r in evaluation['evidence']['results'] if r['id']=='feature-1')['observed']=200
    evaluation['evidence_digest']=digest(evaluation['evidence'])
    path.write_text(json.dumps(evaluation)+'\n')
    _resign(out,['closure/evaluations.jsonl'])
    report=validate_snapshot(str(out))
    assert not report['ok'] and any('does not reproduce' in issue for issue in report['issues'])


def test_agent_export_recovers_after_process_death_from_pinned_state(tmp_path):
    import subprocess,sys
    source=tmp_path/'project';source.mkdir();project,_,good=setup(source)
    loop.submit(project,'run','good',good)
    out=tmp_path/'crash-export'
    script='''
import json,os,sys
from framebound.v2.exports import publication,build_snapshot
publication._checkpoint=lambda stage: os._exit(79) if stage=='staged' else None
build_snapshot(sys.argv[1],'crash',['good'],sys.argv[2],json.loads(sys.argv[3]))
'''
    died=subprocess.run([sys.executable,'-c',script,project,str(out),json.dumps(POLICY)])
    assert died.returncode==79 and not out.exists()
    # New live state must not rewrite the frozen dataset during recovery.
    I.mark(project,Actor(type='reviewer',id='human'),'run',dict(id='later-correction',revision_id='good',evaluation_id='evaluation:good',tick_range=[0,2],desired_outcome='A later human correction'))
    recovered=build_snapshot(project,'crash',['good'],str(out),POLICY)
    assert recovered['counts']['automatically_verified']==3
    assert build_snapshot(project,'crash',['good'],str(out),POLICY)==recovered
    report=validate_snapshot(str(out));assert report['ok'],report['issues']
