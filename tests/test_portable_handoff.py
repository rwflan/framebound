import io,json,zipfile

import pytest
from PIL import Image

from framebound.v2 import storage as S
from framebound.v2.services.authz import Actor
from framebound.v3.services import loop,interventions as I,portable_handoff as P
from test_agent_loop import setup,import_frames


def test_disconnected_agent_returns_directory_without_mcp_or_internal_ids_resolution(tmp_path):
    project_dir=tmp_path/'project';project_dir.mkdir();project,_,good=setup(project_dir)
    bad=import_frames(project_dir,'bad',{'kind':'flicker'})
    feedback=loop.submit(project,'run','bad',bad,generation_metadata={'hidden_token':'must-not-be-in-handoff'})
    mark=I.mark(project,Actor(type='reviewer',id='human'),'run',dict(id='mark',revision_id='bad',evaluation_id='evaluation:bad',tick_range=[2,5],roi=dict(left=2,top=3,right=5,bottom=4),authorize_edit_scope=True,desired_outcome='Restore the green costume.'))
    directory=tmp_path/'external-agent';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(P.archive(project,mark['handoff_id']))) as archive:archive.extractall(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    assert 'must-not-be-in-handoff' not in (directory/'manifest.json').read_text()
    text=(directory/'instructions.txt').read_text()
    assert 'agent-handoff-import' in text and 'Open manifest.json' in text
    assert 'First fetch agent_run_get' not in text
    assert 'Observed:' in text and 'expected:' in text
    assert 'assets/' in text
    baseline=manifest['revisions']['bad']['frame_asset_ids']
    image=Image.open(directory/manifest['assets'][baseline[1]]['file']).convert('RGBA')
    image.putpixel((3,3),(0,255,0,255));image.save(directory/'corrected.png')
    response=dict(revision_id='returned',frames=[dict(asset_id=baseline[0]),dict(file='corrected.png',rights='original',source_kind='procedural'),dict(asset_id=baseline[2])],generation_metadata=None)
    path=directory/'response.json';path.write_text(json.dumps(response))
    result=P.import_response(project,directory/'manifest.json',path)
    assert result['technical_status']=='pass' and result['disposition']=='awaiting_decision'
    assert P.import_response(project,directory/'manifest.json',path)==result
    assert loop.get(project,'run')['submission_ids']==['bad','returned']
    response['revision_id']='late';path.write_text(json.dumps(response))
    with pytest.raises(S.StaleRevisionError):P.import_response(project,directory/'manifest.json',path)


def test_portable_import_rejects_changed_saved_task_and_path_escape(tmp_path):
    project_dir=tmp_path/'project';project_dir.mkdir();project,_,_=setup(project_dir)
    bad=import_frames(project_dir,'bad',{'kind':'flicker'});feedback=loop.submit(project,'run','bad',bad)
    directory=tmp_path/'external';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(P.archive(project,feedback['id']))) as archive:archive.extractall(directory)
    manifest=directory/'manifest.json';original=json.loads(manifest.read_text())
    changed=json.loads(json.dumps(original));changed['task_specs']['task']['spec']['intent']='weakened instructions'
    manifest.write_text(json.dumps(changed))
    response=directory/'response.json';response.write_text(json.dumps(dict(revision_id='new',frames=[dict(asset_id=a) for a in bad])))
    from framebound.v2.services.errors import InvalidInput
    with pytest.raises(InvalidInput,match='frozen project'):P.import_response(project,manifest,response)
    manifest.write_text(json.dumps(original))
    response.write_text(json.dumps(dict(revision_id='new',frames=[dict(file='../project/good-0.png'),dict(asset_id=bad[1]),dict(asset_id=bad[2])],generation_metadata=None)))
    with pytest.raises(InvalidInput,match='outside'):P.import_response(project,manifest,response)
