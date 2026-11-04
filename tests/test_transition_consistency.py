import copy
import json
import pytest
from PIL import Image,ImageDraw
from test_character_consistency import observation,policy,feature
from framebound.v3.character_consistency import Policy,digest,image_digest,evaluate_sequence
from framebound.v3.transition_consistency import evaluate
from framebound.v3.torso_profile import measure


def transition_policy():
    p=policy().model_dump(mode='json');p['transitions']=[dict(id='texture',left='0',right='1',feature='item.texture',item_id='item')]
    return Policy.model_validate(p)


def evidence(p,status='mismatch'):
    return dict(reference_sha256=p.master.image_sha256,image_sha256s={'0':'1'*64,'1':'1'*64},
        rules_sha256=digest([r.model_dump(mode='json') for r in p.transitions]),checks=[dict(id='texture',**feature(status))])


def test_matching_poses_cannot_waive_failed_or_missing_transition():
    p=transition_policy();obs=[observation('0'),observation('1')]
    result=evaluate_sequence(p,obs,['1'*64]*2,['0','1'],transition_review=evidence(p))
    assert all(f['passed'] for f in result['frames']) and not result['passed']
    assert result['transition_results'][0]['status']=='fail'
    assert evaluate_sequence(p,obs,['1'*64]*2,['0','1'],transition_review=evidence(p,'match'))['passed']
    assert not evaluate_sequence(p,obs,['1'*64]*2,['0','1'])['passed']


def test_stale_pairs_and_positive_rejudge_cannot_erase_failure():
    p=transition_policy();bad=evidence(p);good=evidence(p,'match')
    assert evaluate(p,[bad,good],{'0':'1'*64,'1':'1'*64})[0]['status']=='fail'
    assert evaluate(p,good,{'0':'1'*64,'1':'2'*64})[0]['status']=='unmeasured'
    assert evaluate(p,good,{'0':'1'*64})[0]['status']=='unmeasured'
    bad['image_sha256s']['context']='2'*64
    assert evaluate(p,bad,{'0':'1'*64,'1':'1'*64,'context':'3'*64})[0]['status']=='fail'


def torso(width=100):
    image=Image.new('RGBA',(1000,1000));ImageDraw.Draw(image).rectangle((500-width//2,230,500+width//2,450),fill='white')
    obs=observation().model_copy(update={'image_sha256':image_digest(image)})
    return image,obs


def test_native_torso_profile_catches_width_warp_and_ignores_narrow_seam():
    a,oa=torso();b,ob=torso(140)
    first=measure(a,oa,('head_top','chin'));second=measure(b,ob,('head_top','chin'))
    assert first['measured'] and second['measured']
    assert second['profile'][0]/first['profile'][0]>1.35
    ImageDraw.Draw(a).rectangle((498,230,502,450),fill='darkred');oa=oa.model_copy(update={'image_sha256':image_digest(a)})
    assert measure(a,oa,('head_top','chin'))['profile']==pytest.approx(first['profile'])
    p=policy().model_dump(mode='json');p['torso_profile_pairs']=[['0','1']]
    oa=oa.model_copy(update={'frame_id':'0'});ob=ob.model_copy(update={'frame_id':'1'})
    result=evaluate_sequence(p,[oa,ob],[oa.image_sha256,ob.image_sha256],['0','1'],images=[a,b])
    assert not result['passed'] and result['torso_profile_issues'][0]['code']=='torso_shape_pulse'
    result=evaluate_sequence(p,[oa,ob],[oa.image_sha256,ob.image_sha256],['0','1'])
    assert result['torso_profile_issues'][0]['status']=='unmeasured'


def test_display_calibration_cannot_disguise_low_native_character_detail():
    o=observation().model_dump(mode='json')
    for point in o['points'].values():
        if point['xy']:point['xy']=[v*.4 for v in point['xy']]
    for pt in [o['items']['item']['grip'],*o['items']['item']['rigid_span']]:pt['xy']=[v*.4 for v in pt['xy']]
    p=policy().model_dump(mode='json');p['minimum_scale_reference_pixels']=80
    result=evaluate_sequence(p,[o],['1'*64],['0'],pixel_scales=[2.5])
    assert not result['passed']
    assert any(i['code']=='insufficient_native_character_detail' for i in result['frames'][0]['issues'])


def test_owner_and_functional_direction_are_independent_item_gates():
    from framebound.v3.transition_consistency import repair_tasks
    p=policy().model_dump(mode='json')
    p['transitions']=[dict(id=key,left='0',right='1',feature='item.'+key,item_id='item') for key in ('owner','orientation')]
    p=Policy.model_validate(p)
    ev=dict(reference_sha256=p.master.image_sha256,image_sha256s={'0':'1'*64,'1':'1'*64},rules_sha256=digest([r.model_dump(mode='json') for r in p.transitions]),checks=[dict(id='owner',**feature('match')),dict(id='orientation',**feature('mismatch'))])
    rows=evaluate(p,ev,{'0':'1'*64,'1':'1'*64})
    assert [r['status'] for r in rows]==['pass','fail']
    assert repair_tasks(rows,'1')[0]['feature']=='item.orientation'
    assert not repair_tasks(rows,'other')
    assert not repair_tasks(evaluate(p,None,{'0':'1'*64,'1':'1'*64}),'1')
