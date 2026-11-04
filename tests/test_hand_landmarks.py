import json
from PIL import Image
from test_character_consistency import observation
from framebound.v3.character_consistency import image_digest
from framebound.v3.hand_landmarks import conflict,recover


def test_opposite_palm_proximity_requests_independent_recovery_without_relabeling_owner():
    o=observation().model_dump(mode='json')
    o['points']['left_hand']=dict(xy=[850,850],visibility='visible',evidence='Other observed palm')
    o['points']['right_hand']=dict(xy=[500,465],visibility='visible',evidence='Initial palm')
    o['items']['item']['anchor']='left_hand'
    o['items']['item']['grip']=dict(xy=[500,465],visibility='visible',evidence='Visible grip')
    assert conflict(o,('head_top','chin'))
    assert o['items']['item']['anchor']=='left_hand'


def test_recovery_is_bound_to_image_and_retains_uncertainty(monkeypatch,tmp_path):
    import framebound.v3.hand_landmarks as hands
    im=Image.new('RGBA',(1000,1000));o=observation().model_dump(mode='json');o['image_sha256']=image_digest(im)
    proposal=dict(left_hand=dict(xy=None,visibility='uncertain',evidence='Elbow hidden, cannot trace chain'),right_hand=dict(xy=[500,465],visibility='visible',evidence='Near shoulder through bent elbow to visible wrist and palm'),limitation='One arm occluded')
    monkeypatch.setattr(hands,'extract_text',lambda raw:proposal)
    captured=[]
    def dispatch(root,key,model,prompt,images):
        assert 'No requested object ownership is supplied' in prompt
        assert len(images)==2
        return b'retained raw independent observation'
    palms,evidence=recover(tmp_path,im,o,dispatch=dispatch,persist=lambda path,value:captured.append(value))
    assert palms.left_hand.xy is None
    assert evidence['image_sha256']==image_digest(im) and not evidence['human_approval']
    assert captured[0]==evidence
