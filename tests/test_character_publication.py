"""Publication preserves control pixels and never labels an incomplete preview passed."""
import copy
import json
from PIL import Image,ImageDraw
import pytest
from test_character_consistency import observation,policy,feature
from framebound.v3.character_consistency import image_digest,digest
from scripts.publish_character_demo import publish


def fixture(tmp_path):
    public=tmp_path/'public';old=public/'old';old.mkdir(parents=True)
    source=tmp_path/'source';source.mkdir();(source/'brief.json').write_text(json.dumps({'poses':[{'id':'idle'},{'id':'run'}]}))
    root=tmp_path/'work';root.mkdir();(root/'private').mkdir()
    base=Image.new('RGBA',(1000,1000));ImageDraw.Draw(base).rectangle((350,100,650,850),fill='red')
    for slot in range(2):
        base.save(old/f'direct-{slot}.png');base.save(old/f'framework-{slot}.png')
    candidate=base.copy();candidate.putpixel((500,500),(240,0,0,255));candidate.save(root/'regenerated.png')
    manifest=dict(schema=2,canvas=[1000,1000],ground_y=900,revision='old',frame_count=2,source_dimensions=[[1000,1000]],
                  source_pixel_scales={'direct':[1,1],'framework':[1,1]},states={'idle':{'frames':[0],'duration_ticks':[90]},'run':{'frames':[1],'duration_ticks':[6],'loop':True}})
    (public/'manifest.json').write_text(json.dumps(manifest));(root/'start-manifest.json').write_text(json.dumps(manifest))
    config=dict(source_root=str(source),publish_root=str(public),source_revision='old',master_image=str(old/'framework-0.png'),policy_version='test')
    (root/'config.json').write_text(json.dumps(config))
    p=policy().model_dump(mode='json');p['master']['image_sha256']=image_digest(base)
    (root/'policy-test.json').write_text(json.dumps(p))
    rows={}
    for slot,(fid,image) in enumerate([('idle',base),('run',candidate)]):
        obs=observation(fid).model_dump(mode='json');obs['image_sha256']=image_digest(image)
        if slot:obs['items']['item']['features']['design']=feature('mismatch')
        rows[fid]=dict(image=str(root/'regenerated.png' if slot else old/'framework-0.png'),image_sha256=image_digest(image),pixel_scale=1,observation=obs)
    return root,public,manifest,dict(frames=rows)


def test_failed_gate_blocks_delivery_and_preview_is_explicit(tmp_path):
    root,public,before,state=fixture(tmp_path)
    with pytest.raises(ValueError,match='withheld'):publish(root,state)
    assert json.loads((public/'manifest.json').read_text())==before
    after=publish(root,state,preview=True)
    assert after['quality']['status']=='refining'
    assert after['quality']['human_approval'] is False
    assert after['quality']['regenerated_frames']==1
    assert after['states']==before['states']
    assert after['source_pixel_scales']['direct']==before['source_pixel_scales']['direct']
    for slot in range(2):assert (public/after['revision']/f'direct-{slot}.png').read_bytes()==(public/'old'/f'direct-{slot}.png').read_bytes()
    assert after['source_offsets']['framework'][1][1]==49


def test_generator_receives_explicit_matte_without_changing_artwork():
    import io
    from scripts.refine_character_demo import generation_png
    source=Image.new('RGBA',(20,20));source.putpixel((10,10),(240,240,240,255))
    before=source.tobytes();received=Image.open(io.BytesIO(generation_png(source))).convert('RGBA')
    assert received.getpixel((0,0))==(255,0,255,255)
    assert received.getpixel((10,10))==(240,240,240,255)
    assert source.tobytes()==before


def test_jump_state_boundaries_are_assessed_as_temporal_neighbours():
    from scripts.refine_character_demo import pairs_for
    manifest={'states':{'jump':{'frames':[1]},'apex':{'frames':[2]},'fall':{'frames':[3]},'run':{'frames':[4,5],'loop':True}}}
    assert set(pairs_for(manifest))=={(1,2),(2,3),(4,5),(5,4)}


def test_known_visible_design_failure_blocks_even_preview(tmp_path):
    root,public,before,state=fixture(tmp_path)
    path=root/'config.json';config=json.loads(path.read_text());config['preview_blocking_features']=['item:design'];path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='visible body/item'):publish(root,state,preview=True)
    assert json.loads((public/'manifest.json').read_text())==before


def test_detached_item_blocks_preview_even_when_only_numeric_attachment_failed(tmp_path):
    root,public,before,state=fixture(tmp_path)
    path=root/'config.json';config=json.loads(path.read_text());config['preview_blocking_codes']=['item_detached'];path.write_text(json.dumps(config))
    state['frames']['run']['observation']['items']['item']['grip']['xy']=[800,465]
    with pytest.raises(ValueError,match='visible body/item'):publish(root,state,preview=True)
    assert json.loads((public/'manifest.json').read_text())==before


def test_publication_recipe_changes_get_a_new_immutable_revision(tmp_path,monkeypatch):
    import scripts.publish_character_demo as publisher
    root,public,before,state=fixture(tmp_path)
    recipe=tmp_path/'publisher.py';recipe.write_text('TEST-ONLY recipe one')
    monkeypatch.setattr(publisher,'__file__',str(recipe))
    first=publisher.publish(root,state,preview=True)
    recipe.write_text('TEST-ONLY recipe two')
    second=publisher.publish(root,state,preview=True)
    assert first['revision']!=second['revision']
    assert first['publication_recipe_sha256']!=second['publication_recipe_sha256']
    assert (public/first['revision']/'direct-0.png').read_bytes()==(public/second['revision']/'direct-0.png').read_bytes()


def test_required_transition_evidence_blocks_preview(tmp_path):
    root,public,before,state=fixture(tmp_path)
    path=root/'policy-test.json';p=json.loads(path.read_text())
    p['transitions']=[dict(id='grip',left='idle',right='run',feature='item.orientation',item_id='item')]
    path.write_text(json.dumps(p))
    with pytest.raises(ValueError,match='transition'):publish(root,state,preview=True)
    assert json.loads((public/'manifest.json').read_text())==before


def test_transition_runner_retains_negative_and_rechecks_changed_pixels(tmp_path,monkeypatch):
    import scripts.review_character_transitions as runner
    root,public,before,state=fixture(tmp_path)
    path=root/'policy-test.json';p=json.loads(path.read_text());p['transitions']=[dict(id='grip',left='idle',right='run',feature='item.orientation',item_id='item')];path.write_text(json.dumps(p))
    calls=[]
    def assess(work,reference,frames,rules,description,**kwargs):
        calls.append([fid for fid,_ in frames])
        return dict(reference_sha256=image_digest(reference),image_sha256s={fid:image_digest(im) for fid,im in frames},rules_sha256=digest([r.model_dump(mode='json') for r in rules]),checks=[dict(id='grip',**feature('mismatch'))])
    monkeypatch.setattr(runner,'assess',assess)
    config=root/'config.json';data=json.loads(config.read_text());data['description']='same tool, conventional grip';config.write_text(json.dumps(data))
    assert runner.review(root,state)[0]['status']=='fail'
    assert runner.review(root,state)[0]['status']=='fail'
    assert len(calls)==1
    image=Image.open(state['frames']['run']['image']);image.putpixel((600,600),(0,0,255,255));image.save(root/'new.png');state['frames']['run']['image']=str(root/'new.png')
    assert runner.review(root,state)[0]['status']=='fail'
    assert len(calls)==2


def test_repair_reviews_the_replacement_observation_with_replacement_pixels(tmp_path,monkeypatch):
    import scripts.refine_character_demo as driver
    import scripts.review_character_transitions as reviewer
    from framebound.v3.character_consistency import Policy
    root,public,before,state=fixture(tmp_path)
    config_path=root/'config.json';config=json.loads(config_path.read_text());config.update(items=[i.model_dump(mode='json') for i in policy().items],description='Preserve one tool and its grip',max_rounds=1);config_path.write_text(json.dumps(config))
    brief_path=public.parent/'source'/'brief.json';brief=json.loads(brief_path.read_text())
    for pose in brief['poses']:pose['instruction']='Same character, articulated pose'
    brief_path.write_text(json.dumps(brief))
    policy_path=root/'policy-test.json';p=json.loads(policy_path.read_text());p['transitions']=[dict(id='grip',left='idle',right='run',feature='item.orientation',item_id='item')];policy_path.write_text(json.dumps(p));p=Policy.model_validate(p)
    state['policy_sha256']=digest(p.model_dump(mode='json'));(root/'repair-state-run.json').write_text(json.dumps(state))
    replacement=Image.open(state['frames']['run']['image']).convert('RGBA');replacement.putpixel((510,510),(0,0,255,255));new_sha=image_digest(replacement)
    def observe(work,fid,image,reference,config,**kwargs):
        obs=copy.deepcopy(state['frames'][fid]['observation']);obs['image_sha256']=image_digest(image)
        if image_digest(image)==new_sha:obs['items']['item']['features']['design']=feature('match')
        from framebound.v3.character_consistency import Observation
        return Observation.model_validate(obs)
    def review(work,current,**kwargs):
        row=current['frames']['run'];im=Image.open(row['image']).convert('RGBA')
        assert row['observation']['image_sha256']==image_digest(im)
        return [dict(id='grip',feature='item.orientation',item_id='item',frames=['idle','run'],status='pass' if image_digest(im)==new_sha else 'fail',observed='Reversed handle',expected='Active end at index side')]
    monkeypatch.setattr(driver,'safe_observe',observe);monkeypatch.setattr(reviewer,'review',review)
    monkeypatch.setattr(driver,'send',lambda *a,**k:b'test retained provider response')
    monkeypatch.setattr(driver,'decode',lambda *a,**k:(replacement,dict(framing=dict(eligible=True),source_dimensions=[1000,1000])))
    result=driver.repair(root,only='run',max_new_attempts=1)
    row=result['frames']['run']
    assert row['observation']['image_sha256']==new_sha
    assert all(r['status']=='pass' for r in row['transition_results'])
