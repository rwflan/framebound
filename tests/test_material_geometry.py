import numpy as np
from PIL import Image,ImageDraw
from framebound.v3.material_geometry import material_section


def test_internal_seam_is_not_mistaken_for_garment_width():
    image=Image.new('RGBA',(200,200))
    draw=ImageDraw.Draw(image);draw.rectangle((60,10,140,190),fill='white')
    draw.rectangle((98,10,102,190),fill='darkred')
    section=material_section(image,np.array([100.,10.]),np.array([100.,190.]),60.)
    assert section is not None
    assert abs(np.linalg.norm(section[1]-section[0])-80)<2


def test_small_isolated_stripe_cannot_count_as_body_width():
    image=Image.new('RGBA',(200,200));ImageDraw.Draw(image).rectangle((98,10,102,190),fill='white')
    assert material_section(image,np.array([100.,10.]),np.array([100.,190.]),60.) is None


def test_lower_torso_band_uses_garment_not_skirt_centre(monkeypatch):
    from framebound.v3.torso_geometry import HumanPoseObserver
    from framebound.v3 import material_geometry
    points={key:dict(xy=xy,visibility='visible',evidence='TEST-ONLY visible proxy') for key,xy in {
        'neck':[500,100],'pelvis':[500,900],'face_top':[500,0],'face_chin':[500,200]}.items()}
    monkeypatch.setattr(material_geometry.HumanPoseObserver,'measure',lambda self,image:dict(points=points.copy()))
    observer=HumanPoseObserver.__new__(HumanPoseObserver);observer.recipe={};observer.recipe_sha256='0'*64
    image=Image.new('RGBA',(200,200));draw=ImageDraw.Draw(image)
    draw.rectangle((60,35,140,120),fill='white');draw.rectangle((30,130,170,190),fill='black')
    observed=observer.measure(image)['points']
    assert observed['waist_left']['visibility']=='visible'
    x=sorted(observed[k]['xy'][0]*.2 for k in ('waist_left','waist_right'))
    assert x==[60,140]
    assert all(observed[k]['xy'][1]*.2<120 for k in ('waist_left','waist_right'))
