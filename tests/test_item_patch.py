import pytest
from PIL import Image
from scripts.repair_item_patch import patch_box,assemble


def test_generated_patch_cannot_change_pixels_outside_declared_region():
    source=Image.new('RGBA',(600,400),(30,60,90,255));source.putpixel((40,40),(200,100,50,255))
    box=(200,120,350,220);patch=Image.new('RGBA',(600,400),(100,150,200,255))
    out=assemble(source,patch,box)
    assert out.getpixel((250,150))==(100,150,200,255)
    for y in range(source.height):
        for x in range(source.width):
            if not (box[0]<=x<box[2] and box[1]<=y<box[3]):assert out.getpixel((x,y))==source.getpixel((x,y))
    assert source.getpixel((250,150))==(30,60,90,255)


def test_patch_requires_native_detail_and_matching_aspect():
    source=Image.new('RGBA',(600,400));box=(100,100,400,300)
    with pytest.raises(ValueError,match='never upscale'):assemble(source,Image.new('RGBA',(150,100)),box)
    with pytest.raises(ValueError,match='aspect'):assemble(source,Image.new('RGBA',(600,600)),box)
    region=patch_box(source,[[400,400],[600,450]],30)
    assert 0<=region[0]<region[2]<=source.width and 0<=region[1]<region[3]<=source.height
    assert (region[2]-region[0])/(region[3]-region[1])==pytest.approx(1.5,abs=.015)


def test_internal_crop_keying_preserves_art_crossing_crop_edges_without_intake_claim():
    from scripts.repair_item_patch import extract_patch
    from PIL import ImageDraw
    crop=Image.new('RGBA',(120,80),(255,0,255,255));ImageDraw.Draw(crop).rectangle((0,30,119,45),fill=(100,50,20,255))
    out,evidence=extract_patch(crop)
    assert out.size==crop.size
    assert out.getpixel((0,35))==(100,50,20,255)
    assert out.getpixel((119,35))==(100,50,20,255)
    assert out.getpixel((60,5))[3]==0
    assert 'no intake' in evidence['scope']
    with pytest.raises(ValueError,match='reserved magenta'):extract_patch(Image.new('RGBA',(120,80),'white'))


def test_item_patch_restores_protected_torso_but_never_erases_a_crossing_grip():
    from scripts.repair_item_patch import preserve_torso
    from framebound.v3.character_consistency import image_digest
    from test_character_consistency import observation
    source=Image.new('RGBA',(600,400),'red');candidate=Image.new('RGBA',(600,400),'blue');o=observation().model_dump(mode='json');o.update(width=600,height=400,image_sha256=image_digest(source))
    for name,xy in {'left_shoulder':[350,200],'right_shoulder':[650,200],'right_hip':[650,700],'left_hip':[350,700]}.items():o['points'][name]=dict(xy=xy,visibility='visible',evidence='Source contour')
    o['items']['item']['grip']['xy']=[100,750]
    for p in o['items']['item']['rigid_span']:p['xy']=[100,700]
    out,evidence=preserve_torso(source,candidate,o)
    assert evidence['applied'] and out.getpixel((300,180))==source.getpixel((300,180))
    assert out.getpixel((40,350))==candidate.getpixel((40,350))
    o['items']['item']['grip']['xy']=[500,450]
    out,evidence=preserve_torso(source,candidate,o)
    assert not evidence['applied'] and out.tobytes()==candidate.tobytes()

    o['items']['item']['grip']['xy']=[100,450]
    o['items']['item']['rigid_span'][0]['xy']=[100,450]
    o['items']['item']['rigid_span'][1]['xy']=[900,450]
    _,evidence=preserve_torso(source,candidate,o)
    assert not evidence['applied']


def test_unchanged_pixels_retain_estimates_but_edited_hand_gets_new_measurement():
    from scripts.repair_item_patch import retain_unchanged_landmarks
    from test_character_consistency import observation
    from framebound.v3.character_consistency import image_digest
    from PIL import ImageDraw
    source=Image.new('RGBA',(1000,1000),'red');candidate=source.copy();ImageDraw.Draw(candidate).rectangle((550,430,650,500),fill='blue')
    prior=observation().model_dump(mode='json');prior['image_sha256']=image_digest(source)
    import copy
    proposed=copy.deepcopy(prior);proposed['image_sha256']=image_digest(candidate)
    proposed['points']['neck']['xy']=[505,260];proposed['points']['right_hand']['xy']=[510,470]
    result=retain_unchanged_landmarks(source,candidate,prior,proposed,('head_top','chin'))
    assert tuple(result.points['neck'].xy)==tuple(prior['points']['neck']['xy'])
    assert tuple(result.points['right_hand'].xy)==(510,470)
    evidence=result.measurement_sources['preserved_landmarks']
    assert evidence['source_image_sha256']==image_digest(source)
    assert 'neck' in evidence['points'] and 'right_hand' not in evidence['points']
