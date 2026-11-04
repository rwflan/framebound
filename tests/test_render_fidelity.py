import copy
import pytest
from PIL import Image,ImageDraw,ImageFilter
from framebound.v3.render_fidelity import next_source,descriptors,assess
from framebound.v3.character_consistency import image_digest,Policy,evaluate_frame
from test_character_consistency import observation,policy,feature


def test_recursive_edit_budget_never_relabels_depth_as_rendering_quality():
    row=dict(pristine_sha256='1'*64,current_sha256='2'*64,recursive_depth=1)
    assert next_source(row,clarity='pass')['action']=='bounded_edit'
    row['recursive_depth']=2
    assert next_source(row,clarity='pass')['action']=='regenerate_from_pristine'
    row['recursive_depth']=None
    assert next_source(row)['action']=='regenerate_from_pristine'
    row['recursive_depth']=0
    assert next_source(row,clarity='fail')['action']=='regenerate_from_pristine'


def test_blur_loses_native_edge_detail_but_descriptor_does_not_claim_acceptance():
    im=Image.new('RGBA',(180,180),'white');d=ImageDraw.Draw(im)
    for x in range(10,170,8):d.line((x,10,x,170),fill='black',width=2)
    clean=descriptors(im);soft=descriptors(im.filter(ImageFilter.GaussianBlur(3)))
    assert soft['fine_detail_rms']<clean['fine_detail_rms']
    assert soft['edge_gradient_p90']<clean['edge_gradient_p90']
    assert 'not semantic quality' in clean['scope']


def test_render_review_is_bound_to_original_and_one_bad_region_blocks(monkeypatch,tmp_path):
    import framebound.v3.render_fidelity as quality
    pristine=Image.new('RGBA',(100,100),'white');candidate=Image.new('RGBA',(100,100),'grey')
    checks=dict(linework=feature('match'),colour_separation=feature('mismatch'),material_detail=feature('match'),limitation='Automated observation')
    monkeypatch.setattr(quality,'extract_text',lambda raw:checks)
    retained=[]
    result=assess(tmp_path,pristine,candidate,'Same original drawing style',dispatch=lambda *a,**k:b'retained model response',persist=lambda path,value:retained.append(value))
    assert result['status']=='fail' and result['pristine_sha256']==image_digest(pristine)
    assert result['candidate_sha256']==image_digest(candidate) and not result['human_approval']
    checks['colour_separation']=feature('uncertain')
    assert assess(tmp_path,pristine,candidate,'same',dispatch=lambda *a,**k:b'raw',persist=lambda *a:None)['status']=='unmeasured'


def test_wrong_or_stale_clean_reference_cannot_pass_clarity_gate():
    p=policy().model_dump(mode='json');p['required_features'].append('rendering.clarity');p['pristine_render_sha256']='a'*64
    o=observation().model_dump(mode='json');o['features']['rendering.clarity']=feature('match')
    o['measurement_sources']['render_fidelity']=dict(pristine_sha256='b'*64,candidate_sha256=o['image_sha256'],checks=dict(linework=feature('match'),colour_separation=feature('match'),material_detail=feature('match'),limitation='Source-bound review'))
    result=evaluate_frame(p,o,image_sha256=o['image_sha256'],frame_id=o['frame_id'])
    assert not result['passed'] and any(i['code']=='render_fidelity_unmeasured' for i in result['issues'])
    o['measurement_sources']['render_fidelity']['pristine_sha256']='a'*64
    assert evaluate_frame(p,o,image_sha256=o['image_sha256'],frame_id=o['frame_id'])['passed']
    o['measurement_sources']['render_fidelity']['checks']['material_detail']=feature('mismatch')
    assert not evaluate_frame(p,o,image_sha256=o['image_sha256'],frame_id=o['frame_id'])['passed']
    p['pristine_render_sha256']=None
    with pytest.raises(ValueError,match='frozen pristine'):Policy.model_validate(p)


def test_comparison_crops_never_upscale_or_confuse_native_sample_sizes(monkeypatch,tmp_path):
    import io
    import framebound.v3.render_fidelity as quality
    checks=dict(linework=feature('match'),colour_separation=feature('match'),material_detail=feature('match'),limitation='Model review')
    monkeypatch.setattr(quality,'extract_text',lambda raw:checks)
    def dispatch(root,key,model,prompt,images):
        sizes=[Image.open(io.BytesIO(blob)).size for blob in images]
        assert sizes[2:]==[(80,80),(80,80)]
        return b'retained source comparison'
    result=assess(tmp_path,Image.new('RGBA',(300,300),'white'),Image.new('RGBA',(200,200),'grey'),'same',dispatch=dispatch,persist=lambda *a:None,regions={'face':([20,20,220,220],[10,10,90,90])})
    assert result['crops'][0]['comparison_dimensions']==[80,80]


def test_format_recovery_retains_completed_bad_reply_but_never_retries_unknown(monkeypatch,tmp_path):
    import framebound.v3.render_fidelity as quality
    valid=dict(linework=feature('match'),colour_separation=feature('match'),material_detail=feature('match'),limitation='Native comparison limits retained')
    def parse(raw):return dict(valid,limitation={}) if raw==b'bad' else valid
    monkeypatch.setattr(quality,'extract_text',parse)
    calls=[];retained=[]
    def dispatch(root,key,*args):calls.append(key);return b'bad' if len(calls)==1 else b'good'
    im=Image.new('RGBA',(50,50),'white')
    result=assess(tmp_path,im,im,'same',dispatch=dispatch,persist=lambda path,data:retained.append((path.name,data)))
    assert len(calls)==2 and calls[-1].endswith('format-recovery')
    assert any(name.endswith('-invalid.json') for name,_ in retained)
    assert result['status']=='pass'
    calls.clear()
    def unknown(*args):calls.append('unknown');raise TimeoutError('No provider acceptance receipt')
    with pytest.raises(TimeoutError):assess(tmp_path,im,im,'same',dispatch=unknown,persist=lambda *a:None)
    assert calls==['unknown']


def test_partial_edit_depth_cannot_masquerade_as_whole_frame_history():
    from framebound.v3.render_fidelity import Lineage
    row=dict(pristine_sha256='1'*64,current_sha256='2'*64,recursive_depth=0,scope='repair_region',untouched_source_depth=None)
    with pytest.raises(ValueError,match='rectangle'):Lineage.model_validate(row)
    row['region']=[10,10,100,100]
    assert Lineage.model_validate(row).untouched_source_depth is None
    row['scope']='whole_frame'
    with pytest.raises(ValueError,match='partial region'):Lineage.model_validate(row)
