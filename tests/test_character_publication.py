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
