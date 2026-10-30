import json

import pytest
from PIL import Image

from framebound.v2 import storage as S
from framebound.v2.services.assets import import_asset
from framebound.v2.services.errors import InvalidInput
from framebound.v2.services.projects import create_project
from framebound.v3.services import tasks,loop,desk
from framebound.v3 import correspondence as C
from framebound.v3.domain import TaskRecord


def source_task(tmp_path,goal='enhancement_and_interpolation',preservation='alpha_geometry'):
    project=str(tmp_path);create_project(project,{'id':'project'})
    for index,x in enumerate([1,3,1]):
        im=Image.new('RGBA',(8,8));im.putpixel((x,3),(255,0,0,255))
        path=tmp_path/f'source{index}.png';im.save(path);import_asset(project,str(path),f'source-{index}',source_kind='procedural')
    spec=dict(id='enhance',project_id='project',animation_id='enhance',intent='Enhance detail and add in-betweens while preserving source keys and duration.',subjects='single moving subject',
        canvas={'width':8,'height':8},timing={'ticks_per_second':60,'holds':[4]*6},
        source_correspondence=dict(frame_asset_ids=['source-0','source-1','source-2'],timing={'ticks_per_second':30,'holds':[4,4,4]},loop=True,
            designated_by='fixture-author',designation_basis='authored known-good key sequence; not human acceptance',provenance='procedural source fixture',goal=goal,
            time_map=[dict(source_tick=0,output_tick=0),dict(source_tick=12,output_tick=24)],
            protected_keys=[dict(source_tick=i*4,output_tick=i*8,preservation=preservation) for i in range(3)]))
    candidate=[]
    for slot,x in enumerate([1,2,3,2,1,1]):
        im=Image.new('RGBA',(8,8));im.putpixel((x,3),(0,255,0,255))
        path=tmp_path/f'candidate{slot}.png';im.save(path);import_asset(project,str(path),f'candidate-{slot}',source_kind='procedural');candidate.append(f'candidate-{slot}')
    return project,spec,candidate


def test_unequal_counts_timebases_and_detail_changes_are_mapped_by_authored_time(tmp_path):
    project,spec,candidate=source_task(tmp_path)
    task=tasks.create(project,spec)
    assert tasks.get(project,'enhance')==task
    loop.start(project,'enhance','run');feedback=loop.submit(project,'run','enhanced',candidate)
    assert feedback['disposition']=='complete' and feedback['creative_status']=='unreviewed'
    evidence=loop.revision_get(project,'enhanced')['evaluation']['evidence']['source_correspondence']
    mapped=evidence['output_correspondence']
    assert [m['source_slot'] for m in mapped]==[0,0,1,1,2,2]
    assert [m['source_tick'] for m in mapped]==[[0,1],[2,1],[4,1],[6,1],[8,1],[10,1]]
    assert mapped[1]['correspondence']=='source_motion_interval' and mapped[2]['correspondence']=='protected_key'
    assert len(tasks.compile_inputs(project,'enhance')['source_assets'])==3
    assert desk.revision(project,'enhanced')['source_comparison']['frames'][2]['asset_id']=='source-1'
    evaluation=loop.revision_get(project,'enhanced')['evaluation']
    assert all(r['outcome']=='pass' for r in evaluation['results'] if r['family']=='source_fidelity')


def test_changed_key_is_localized_and_repaired_without_index_substitution(tmp_path):
    project,spec,candidate=source_task(tmp_path)
    tasks.create(project,spec);loop.start(project,'enhance','run')
    faulty=list(candidate);faulty[2]=candidate[1]
    feedback=loop.submit(project,'run','bad-key',faulty)
    issue=next(t for t in feedback['targets'] if t['check_id']=='source-key-2')
    assert issue['slots']==[2] and issue['tick_range']==[8,12]
    assert issue['evidence_assets'][-1]['id']=='source-1'
    assert issue['source_correspondence']['source_slot']==1
    repaired=loop.submit(project,'run','fixed',candidate,parent_revision_id='bad-key',feedback_id=feedback['id'])
    assert repaired['disposition']=='complete'


def test_exact_pixels_and_geometry_are_distinct_preservation_rules(tmp_path):
    project,spec,candidate=source_task(tmp_path,preservation='exact_pixels')
    tasks.create(project,spec);loop.start(project,'enhance','run')
    feedback=loop.submit(project,'run','palette-change',candidate)
    assert feedback['technical_status']=='fail'
    assert {t['check_id'] for t in feedback['targets']}=={'source-key-0','source-key-2','source-key-4'}


@pytest.mark.parametrize('change', ['duration','nonmonotonic','missing-key','key-time','loop','map-end'])
def test_source_contract_changes_need_new_valid_specification(tmp_path,change):
    project,spec,_=source_task(tmp_path)
    source=spec['source_correspondence']
    if change=='duration':spec['timing']['holds']=[5]*6;source['time_map'][-1]['output_tick']=30
    if change=='nonmonotonic':source['time_map'].insert(1,dict(source_tick=10,output_tick=25))
    if change=='missing-key':source['protected_keys'].pop()
    if change=='key-time':source['protected_keys'][1]['output_tick']=12
    if change=='loop':source['loop']=False
    if change=='map-end':source['time_map'][-1]['output_tick']=23
    with pytest.raises((InvalidInput,ValueError)):tasks.create(project,spec)


def test_missing_source_pixels_block_required_fidelity_and_compilation(tmp_path):
    project,spec,candidate=source_task(tmp_path)
    tasks.create(project,spec);loop.start(project,'enhance','run')
    con=S.connect(project);asset,_=S.get(con,'assets','source-1');con.close()
    S.blob_path(project,asset['byte_sha256']).unlink()
    feedback=loop.submit(project,'run','missing-source',candidate)
    assert feedback['technical_status']=='incomplete'
    assert next(t for t in feedback['targets'] if t['check_id']=='source-key-2')['outcome']=='unmeasured'
    with pytest.raises(InvalidInput,match='source asset'):tasks.compile_inputs(project,'enhance')


def test_known_good_source_exports_without_dummy_guides_and_revalidates_after_move(tmp_path):
    import shutil
    from framebound.v2.exports import build_snapshot,validate_snapshot
    source_dir=tmp_path/'project';source_dir.mkdir()
    project,spec,candidate=source_task(source_dir)
    tasks.create(project,spec);loop.start(project,'enhance','run');loop.submit(project,'run','enhanced',candidate)
    out=tmp_path/'snapshot'
    manifest=build_snapshot(project,'source',['enhanced'],str(out),{'include_automatically_verified':True,'include_procedural_positives':True})
    assert manifest['counts']['automatically_verified']==6
    moved=tmp_path/'moved';out.rename(moved);shutil.rmtree(source_dir)
    report=validate_snapshot(str(moved));assert report['ok'],report['issues']
    files=json.loads((moved/'closure/asset_files.json').read_text())
    assert {'source-0','source-1','source-2'}<=set(files)
    temporal=json.loads((moved/'temporal.jsonl').read_text())
    assert temporal['time_map']['timing']['ticks_per_second']==30
    assert len(temporal['frames'])==6


def test_actual_source_revision_binding_and_dependency_closure(tmp_path):
    from framebound.v2.exports import build_snapshot,validate_snapshot
    project,spec,candidate=source_task(tmp_path)
    baseline=dict(spec,id='source-task',animation_id='source-animation',source_correspondence=None,
                  timing={'ticks_per_second':30,'holds':[4,4,4]})
    tasks.create(project,baseline);loop.start(project,'source-task','source-run')
    loop.submit(project,'source-run','original-source',['source-0','source-1','source-2'])
    spec['source_correspondence']['source_revision_id']='original-source'
    mismatched=json.loads(json.dumps(spec));mismatched['source_correspondence']['frame_asset_ids'][1]='source-0'
    with pytest.raises(InvalidInput,match='actual stored source revision'):tasks.create(project,mismatched)
    tasks.create(project,spec);loop.start(project,'enhance','run');loop.submit(project,'run','enhanced',candidate)
    out=tmp_path/'export'
    manifest=build_snapshot(project,'lineage',['enhanced'],str(out),{'include_automatically_verified':True,'include_procedural_positives':True})
    assert manifest['counts']['automatically_verified']==6
    assert manifest['counts']['research']==3  # Source-only dependency was not requested as a training example.
    revisions=[json.loads(line)['id'] for line in (out/'closure/revisions.jsonl').read_text().splitlines()]
    assert set(revisions)=={'original-source','enhanced'}
    report=validate_snapshot(str(out));assert report['ok'],report['issues']


def test_existing_v2_source_record_is_preserved_without_fabricating_approval(tmp_path):
    from framebound.v2.services import contracts,clips
    project,spec,candidate=source_task(tmp_path)
    contract=dict(id='legacy-source-contract',character_revision_id='legacy-character',action=dict(name='sway',view='side',facing='right',loop=True),
        canvas={'width':8,'height':8},timing={'ticks_per_second':30,'holds':[4,4,4]},references={'identity':'source-0'},
        phase_schedule=[dict(slot=i,phase=f'key-{i}',motion_reference_id=f'source-{i}') for i in range(3)],
        constraints=[dict(id='registration',check='native_registration')])
    contracts.propose_contract(project,contract)
    clips.create_revision(project,'legacy-source-contract','legacy-source',['source-0','source-1','source-2'],['key-0','key-1','key-2'])
    spec['source_correspondence']['source_revision_id']='legacy-source'
    tasks.create(project,spec);loop.start(project,'enhance','run')
    feedback=loop.submit(project,'run','enhanced',candidate)
    assert feedback['disposition']=='complete'
    con=S.connect(project)
    assert S.count(con,'reference_approvals')==0
    assert S.count(con,'review_events')==0
    con.close()


def test_earlier_v3_snapshot_without_optional_source_records_still_validates(tmp_path):
    from test_agent_loop import setup
    from test_agent_export import _resign
    from framebound.v2.exports import build_snapshot,validate_snapshot
    project_dir=tmp_path/'project';project_dir.mkdir();project,_,good=setup(project_dir)
    loop.submit(project,'run','good',good)
    out=tmp_path/'older'
    build_snapshot(project,'earlier',['good'],str(out),{'include_automatically_verified':True,'include_procedural_positives':True})
    # This optional file did not exist in the original v3 portable format.
    (out/'closure/source_records.jsonl').unlink()
    manifest=json.loads((out/'manifest.json').read_text());manifest['files'].pop('closure/source_records.jsonl')
    (out/'manifest.json').write_text(json.dumps(manifest));_resign(out,[])
    report=validate_snapshot(str(out));assert report['ok'],report['issues']
