import json
import math
import pytest
from PIL import Image
from test_character_consistency import observation,policy
from framebound.v3.character_consistency import image_digest
from framebound.v3.item_measurement import measure


def response(endpoints):
    value=dict(endpoints=endpoints,component='TEST-ONLY rigid component',limitation='TEST-ONLY synthetic localization')
    return json.dumps(dict(status='completed',output=[dict(type='message',role='assistant',content=[dict(type='output_text',text=json.dumps(value))])])).encode()


def test_native_crop_endpoints_map_back_without_resizing_or_changing_pixels(tmp_path):
    image=Image.new('RGBA',(1000,1000));obs=observation().model_copy(update={'image_sha256':image_digest(image)})
    endpoints=[dict(xy=[500,200],visibility='visible',evidence='TEST-ONLY first end'),dict(xy=[500,800],visibility='visible',evidence='TEST-ONLY second end')]
    saved=[];before=image.tobytes()
    result=measure(tmp_path,image,obs,policy().items[0],('head_top','chin'),dispatch=lambda *a:response(endpoints),persist=lambda *a:saved.append(a))
    box=result.measurement_sources['item_detail']['item']['crop']
    for index,p in enumerate(result.items['item'].rigid_span):
        assert p.xy==pytest.approx([box[0]+.5*(box[2]-box[0]),box[1]+endpoints[index]['xy'][1]/1000*(box[3]-box[1])])
    assert image.tobytes()==before
    assert saved and result.image_sha256==obs.image_sha256


def test_occluded_endpoint_remains_unknown_and_unknown_send_is_never_retried(tmp_path):
    image=Image.new('RGBA',(1000,1000));obs=observation().model_copy(update={'image_sha256':image_digest(image)})
    points=[dict(xy=None,visibility='occluded',evidence='TEST-ONLY hidden end')]*2
    result=measure(tmp_path,image,obs,policy().items[0],('head_top','chin'),dispatch=lambda *a:response(points),persist=lambda *a:None)
    assert all(p.xy is None for p in result.items['item'].rigid_span)
    calls=[]
    def dispatch(*a):calls.append(1);raise TimeoutError('TEST-ONLY unknown acceptance')
    with pytest.raises(TimeoutError):measure(tmp_path,image,obs,policy().items[0],('head_top','chin'),dispatch=dispatch,persist=lambda *a:None)
    assert calls==[1]
    with pytest.raises(ValueError,match='Stale'):measure(tmp_path,image,observation(),policy().items[0],('head_top','chin'),dispatch=dispatch,persist=lambda *a:None)
    assert calls==[1]


def test_new_root_cannot_bypass_an_unknown_component_operation(tmp_path):
    image=Image.new('RGBA',(1000,1000));obs=observation().model_copy(update={'image_sha256':image_digest(image)});calls=[]
    def dispatch(root,key,*args):
        folder=root/'private'/key;folder.mkdir(parents=True,exist_ok=True)
        marker=folder/'request.json'
        if marker.exists():raise FileExistsError('TEST-ONLY retained unknown send')
        marker.write_text('TEST-ONLY immutable commitment');calls.append(1)
        raise TimeoutError('TEST-ONLY unknown acceptance')
    with pytest.raises(TimeoutError):measure(tmp_path,image,obs,policy().items[0],('head_top','chin'),dispatch=dispatch,persist=lambda *a:None)
    changed=obs.model_copy(deep=True);changed.items['item'].grip.xy=(601,465)
    with pytest.raises(FileExistsError):measure(tmp_path/'new',image,changed,policy().items[0],('head_top','chin'),dispatch=dispatch,persist=lambda *a:None,cache_roots=[tmp_path])
    assert calls==[1]
