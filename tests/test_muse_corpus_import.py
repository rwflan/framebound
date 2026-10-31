"""Engineering fixtures only. Fake receipts here are not real corpus evidence."""
import hashlib
import json

from PIL import Image
import pytest

from framebound.v2 import storage as S
from framebound.v2.services.errors import InvalidInput
from framebound.v3.corpus import prepare
from framebound.v3.benchmark import run
from framebound.v3.services import desk, loop


def write_json(path, data):
    path.write_text(json.dumps(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(root):
    anchor=root/'anchor.png';Image.new('RGBA',(64,64),(20,30,40,255)).save(anchor)
    anchor_sha=hashlib.sha256(anchor.read_bytes()).hexdigest()
    write_json(root/'anchor.receipt.json',dict(status='completed',output_sha256=anchor_sha,model_requested='muse-image-1.0'))
    sheet=Image.new('RGBA',(192,128),(200,200,200,255))
    for slot in range(6):sheet.putpixel(((slot%3)*64+10,(slot//3)*64+10),(slot*30,40,50,255))
    sheet.save(root/'sheet.png');sha=hashlib.sha256((root/'sheet.png').read_bytes()).hexdigest()
    write_json(root/'sheet.receipt.json',dict(status='completed',output_sha256=sha,model_requested='muse-image-1.0',
        model_observed='muse-image-1.0',response_id='TEST-ONLY',prompt_sha256='a'*64,
        conditioning_ordered=[dict(source_file='anchor.png',sha256=anchor_sha,kind='anchor_image')]))
    style_sha=write_json(root/'style.json',dict(name='TEST ONLY style card'))
    item=dict(id='test-base',board_id='test-board',split='held_out',status='succeeded',sheet_file='sheet.png',
        receipt_file='sheet.receipt.json',anchor_file='anchor.png',style_card_sha256=style_sha,
        holds=[3,1,2,2,1,3],loop=True,intent='Engineering import fixture, not real artwork evidence.')
    manifest=root/'base_manifest.json';write_json(manifest,dict(cases=[item]));return manifest


def test_import_retains_actual_hashes_derivations_and_unmeasured_scope(tmp_path):
    root=tmp_path/'source';root.mkdir();manifest=source(root)
    project=str(tmp_path/'project')
    result=prepare(manifest,project,native_size=32)
    item=result['imported'][0]
    assert item['technical_status']=='pass' and item['coverage']=='complete'
    assert not desk.snapshot(project)['runs'][0]['needs_intervention']
    view=desk.revision(project,item['revision_id'])
    assert view['provenance']['generations'][0]['observed_model']=='muse-image-1.0'
    con=S.connect(project)
    try:
        asset,_=S.get(con,'assets',item['frames'][0])
        assert asset['source_kind']=='derived' and len(asset['parent_asset_ids'])==2
    finally:con.close()
    assert prepare(manifest,project,native_size=32)['imported']==result['imported']
    benchmark=run(result['benchmark'])
    assert benchmark['cases'][0]['label_source']=='unreviewed'
    assert benchmark['cases'][0]['unmeasured_or_errors']==['gap:generated-art-quality']
    assert benchmark['per_board']['test-board']['incomplete_label_cases']==1


def test_changed_provider_output_and_outside_paths_are_rejected(tmp_path):
    manifest=source(tmp_path)
    Image.new('RGB',(192,128)).save(tmp_path/'sheet.png')
    with pytest.raises(InvalidInput,match='actual successful Muse receipt'):prepare(manifest,str(tmp_path/'project'))
    data=json.loads(manifest.read_text());data['cases'][0]['sheet_file']='../outside.png';write_json(manifest,data)
    with pytest.raises(InvalidInput,match='out-of-corpus'):prepare(manifest,str(tmp_path/'other'))


def test_model_labels_do_not_become_human_acceptance(tmp_path):
    manifest=source(tmp_path)
    review=tmp_path/'review.json'
    write_json(review,dict(cases=[dict(id='test-base',complete_labels=False,expected_defects=[],
        notes='Synthetic model-label declaration testing authority only.')]))
    result=prepare(manifest,str(tmp_path/'project'),review_path=review,native_size=32)
    report=run(result['benchmark'])
    assert report['cases'][0]['label_source']=='model_review'
    assert report['summary']['independent_reviewed_generated_held_out_cases']==0
    assert report['summary']['model_reviewed_generated_held_out_cases']==1
    assert loop.get(str(tmp_path/'project'),result['imported'][0]['run_id'])['creative_status']=='unreviewed'


def test_model_supervision_exports_and_loads_without_human_review(tmp_path):
    from framebound.v2.exports import build_snapshot
    from framebound.v2.exports.agent_reader import load_model_annotations
    root=tmp_path/'source';root.mkdir();manifest=source(root)
    review=root/'review.json';write_json(review,dict(cases=[dict(id='test-base',complete_labels=False,
        expected_defects=[],notes='Engineering model-label fixture, no human review.')]))
    project=str(tmp_path/'project');result=prepare(manifest,project,review_path=review,native_size=32)
    snapshot=tmp_path/'snapshot'
    exported=build_snapshot(project,'model-training',[result['imported'][0]['revision_id']],str(snapshot),
        dict(agent_export_policy='agent-training-v1',include_automatically_verified=False))
    assert exported['counts']['positives']==0
    annotations=load_model_annotations(snapshot)
    assert len(annotations)==1 and len(annotations[0]['frames'])==6
    assert annotations[0]['label_source']=='model_review'
    assert not annotations[0]['human_acceptance']


def test_unsafe_case_identifier_cannot_escape_native_output_directory(tmp_path):
    manifest=source(tmp_path);data=json.loads(manifest.read_text());data['cases'][0]['id']='../../escape'
    write_json(manifest,data)
    with pytest.raises(InvalidInput,match='safe immutable identifier'):prepare(manifest,str(tmp_path/'project'))


def test_repairs_retain_family_budget_and_export_replayable_edit_ancestry(tmp_path):
    manifest=source(tmp_path);data=json.loads(manifest.read_text())
    repaired=dict(data['cases'][0],id='test-repair',repair_of='test-base',repair_reason='Model correction test fixture.')
    Image.new('RGBA',(192,128),(240,80,20,255)).save(tmp_path/'repair.png')
    original_receipt=json.loads((tmp_path/'sheet.receipt.json').read_text())
    repaired_receipt=dict(original_receipt,output_sha256=hashlib.sha256((tmp_path/'repair.png').read_bytes()).hexdigest(),
        conditioning_ordered=[dict(source_file='sheet.png',sha256=original_receipt['output_sha256'],kind='baseline_image')])
    write_json(tmp_path/'repair.receipt.json',repaired_receipt)
    repaired.update(sheet_file='repair.png',receipt_file='repair.receipt.json',target_slots=[0])
    data['cases'].append(repaired);write_json(manifest,data)
    review=tmp_path/'review.json';write_json(review,dict(cases=[dict(id=cid,complete_labels=False,expected_defects=[],notes='Engineering model-label fixture.') for cid in ('test-base','test-repair')]))
    project=str(tmp_path/'project');first=prepare(manifest,project,review_path=review,native_size=32)
    before=loop.get(project,first['imported'][0]['run_id'])
    assert len(before['submission_ids'])==2 and before['remaining_submissions']==1
    assert first['imported'][0]['run_id']==first['imported'][1]['run_id']
    revision=loop.revision_get(project,first['imported'][1]['revision_id'])['revision']
    assert revision['parent_revision_id']==first['imported'][0]['revision_id']
    assert revision['changed_slots']==[0]
    assert revision['generation_metadata']['provenance']['generations'][0]['edit_parent_event_id']=='test-base'
    assert prepare(manifest,project,review_path=review,native_size=32)['imported']==first['imported']
    assert loop.get(project,before['id'])['remaining_submissions']==1
    report=run(first['benchmark']);assert len(report['repairs'])==1
    from framebound.v2.exports import build_snapshot
    from framebound.v2.exports.agent_reader import load_model_corrections
    snapshot=tmp_path/'snapshot'
    build_snapshot(project,'correction',[revision['id']],str(snapshot),dict(agent_export_policy='agent-training-v1'))
    pairs=load_model_corrections(snapshot)
    assert len(pairs)==1 and not pairs[0]['human_acceptance']
    assert len(pairs[0]['baseline']['frames'])==len(pairs[0]['correction']['frames'])==6


def test_review_adapter_keeps_check_matrix_separate_from_observed_defects(tmp_path):
    from framebound.v3.corpus import normalize_model_review
    original=tmp_path/'review.json'
    write_json(original,dict(cases=[dict(id='actual',expected_defects=[dict(check_id='quality:not-a-defect',slots=[0])],
        defects=[dict(family='missing-prop',slots=[2],observed='Model explicitly observed missing prop.',confidence=.6)]),
        dict(id='clean',expected_defects=[dict(check_id='quality:rubric-only',slots=[0,1])],defects=[])]))
    before=original.read_bytes();result=normalize_model_review(original,tmp_path/'normalized.json')
    assert original.read_bytes()==before
    assert result['cases'][0]['expected_defects']==[dict(check_id='quality:missing-prop',slots=[2],roi=None)]
    assert result['cases'][1]['expected_defects']==[]
    assert result['cases'][1]['requested_checks'][0]['check_id']=='quality:rubric-only'
