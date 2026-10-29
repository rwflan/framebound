"""Public setup uses subprocess CLI and authenticated reviewer HTTP only."""
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest
from framebound.v2.api.app import create_app


def cli(project, *args):
    env = {k:v for k,v in os.environ.items() if k not in ('MODEL_API_KEY','META_API_KEY')}
    result = subprocess.run([sys.executable,'-m','framebound',*args,'--project',str(project)],
                            capture_output=True,text=True,env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def public_project(root, monkeypatch, color=(230,80,30), width=12):
    project = root/'project'
    assert cli(project,'project-create','--project-id','p')['ok']
    assert cli(project,'project-create','--project-id','p')['ok']
    hashes = {}
    for index, aid in enumerate(('identity','style','pose0','pose1')):
        im = Image.new('RGBA',(64,64));d=ImageDraw.Draw(im)
        d.rectangle((32-width//2,12,32+width//2,52),fill=color+(255,))
        d.rectangle((20+index,48,22+index,55),fill=(20,180,250,255))
        path=root/(aid+'.png');im.save(path)
        hashes[aid]=cli(project,'asset-import','--src',str(path),'--asset-id',aid)['artifacts'][0]['byte_sha256']
    char={'id':'char','project_id':'p','identity_asset_ids':['identity'],
          'style_asset_ids':['style'],'view_set':['side'],
          'canvas':{'width':64,'height':64},'scale_ruler':'native 64px canvas'}
    path=root/'character.json';path.write_text(json.dumps(char))
    assert cli(project,'character-propose','--character',str(path))['ok']
    assert cli(project,'character-propose','--character',str(path))['ok']
    guide={'id':'guide','character_revision_id':'char','entries':[
        {'phase':f'p{i}','asset_id':f'pose{i}','byte_sha256':hashes[f'pose{i}']} for i in range(2)]}
    path=root/'guide.json';path.write_text(json.dumps(guide))
    cli(project,'guide-propose','--guide',str(path))
    cli(project,'guide-propose','--guide',str(path))
    monkeypatch.setenv('FRAMEBOUND_OPERATOR_SECRET','test-operator')
    client=TestClient(create_app(str(project)))
    from framebound.v2.services.sessions import create_session
    session=create_session(str(project),'test-reviewer')
    headers={'X-Session-Token':session['session_token']}
    body={'character_revision_id':'char','motion_guide_id':'guide','event_id':'approve-guide'}
    assert client.post('/api/references/approve',json=body).status_code == 403
    approved=client.post('/api/references/approve',json=body,headers=headers)
    assert approved.status_code == 200, approved.text
    assert client.post('/api/references/approve',json=body,headers=headers).json() == approved.json()
    contract={'id':'contract','character_revision_id':'char',
        'action':{'name':'run','view':'side','facing':'right','loop':True},
        'canvas':{'width':64,'height':64,'units':'native_px'},
        'timing':{'ticks_per_second':60,'holds':[4,4]},
        'references':{'identity':'identity','style':'style','motion_guide_revision':'guide'},
        'phase_schedule':[{'slot':i,'phase':f'p{i}','motion_reference_id':f'guide-{i}'} for i in range(2)],
        'constraints':[{'id':'registration','check':'native_registration','required':True}],
        'allowed_transforms':{'per_pose_scale':False,'rigid_translation_budget_px':2}}
    path=root/'contract.json';path.write_text(json.dumps(contract))
    cli(project,'contract-propose','--contract',str(path))
    cli(project,'clip-create','--contract-id','contract','--revision-id','base','--frames','pose0,pose1','--phases','p0,p1')
    return project,client,headers,contract


@pytest.mark.parametrize('color,width',[((230,80,30),12),((60,190,90),20)])
def test_public_creation_survives_new_process_and_has_no_hidden_character_insert(tmp_path,monkeypatch,color,width):
    project,client,headers,contract=public_project(tmp_path,monkeypatch,color,width)
    evaluated=cli(project,'clip-evaluate','--revision-id','base')
    assert evaluated['technical_status']=='pass'
    brief=cli(project,'brief-compile','--contract-id','contract','--slot','0')
    assert brief['motion_guide_id']=='guide'
    refs=TestClient(create_app(str(project))).get('/api/references').json()
    assert len(refs['character_revisions'])==1
    assert len(refs['reference_approvals'])==1


def test_new_guide_does_not_rebind_old_contract_brief(tmp_path,monkeypatch):
    project,client,headers,_=public_project(tmp_path,monkeypatch)
    guide=client.get('/api/references').json()['motion_guides'][0]
    guide['id']='new-guide';guide['supersedes']='guide'
    path=tmp_path/'new-guide.json';path.write_text(json.dumps(guide))
    cli(project,'guide-propose','--guide',str(path))
    response=client.post('/api/references/approve',json={'character_revision_id':'char','motion_guide_id':'new-guide'},headers=headers)
    assert response.status_code==200,response.text
    assert cli(project,'brief-compile','--contract-id','contract','--slot','0')['motion_guide_id']=='guide'
