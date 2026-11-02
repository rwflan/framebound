"""SAM protocol and acquisition invariants; published protocol fixture, no art."""
import io
import json
from datetime import datetime,timezone

import pytest
from PIL import Image

from framebound.v3.campaign.contracts import Prices,canonical,curriculum
from framebound.v3.campaign.curriculum import upskill_curriculum
from framebound.v3.campaign.dispatch import Response
from framebound.v3.campaign.ledger import Ledger,Stopped
from framebound.v3.campaign.runner import Runner,AcquisitionRejected
from framebound.v3.campaign.segmentation import isolate
from framebound.v3.campaign.specialists import MuseResponses

# Meta's public parser README example, deliberately using its non-RFC85 codec.
TEXT="<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"


def pixels(color='white'):
    image=Image.new('RGB',(320,334),color);out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def response(text=TEXT):
    return canonical(dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text=text)])]))


def test_official_codec_maps_half_open_bounds_and_preserves_source():
    pytest.importorskip('meta_sam_parser')
    raw=pixels();image,recipe=isolate(raw,response())
    assert image.size==(320,334) and image.getchannel('A').getbbox()==(211,228,271,255)
    assert image.getpixel((0,0))==(255,255,255,0)
    assert recipe['masks'][0]['bounds']==[211,228,271,255]
    assert recipe['technical_background_fraction']==[1.0]
    assert pixels()==raw


@pytest.mark.parametrize('text,color,reason',[
    ('','white','dimensions'),
    (TEXT.replace('w=320','w=321'),'white','dimensions'),
    (TEXT+','+TEXT.removeprefix('<0f>').replace('0<|box','1<|box',1),'white','exactly one'),
    (TEXT,'green','nontechnical background'),
    (TEXT.replace('data=27,60,~','data=27,60,~garbage'),'white','protocol'),
])
def test_rejects_wrong_geometry_missing_duplicate_corrupt_or_scenic_masks(text,color,reason):
    pytest.importorskip('meta_sam_parser')
    with pytest.raises(ValueError,match=reason):isolate(pixels(color),response(text))


def test_new_contract_is_disjoint_explicitly_priced_and_old_bytes_stay_default():
    old=upskill_curriculum('default');new=upskill_curriculum('segmented',source_policy='sam-isolation-v5')
    assert 'segmentation_microdollars' not in old.model_dump(mode='json')['prices']
    assert new.prices.segmentation_microdollars==2500
    assert not {c.family for c in old.cases}&{c.family for c in new.cases}
    assert all('DECLARED EXTRACTION KEY:' not in c.request and 'sam-isolation-v5' in c.request for c in new.cases)


def test_received_segmentation_replays_without_paid_retry_even_on_rejection(tmp_path):
    pytest.importorskip('meta_sam_parser')
    config=curriculum('sam-engineering');case=config.cases[0].model_copy(update={'subject':'animal'})
    config=config.model_copy(update={'cases':[case],'prices':Prices(verified_at='engineering',source='fixture',segmentation_microdollars=2500)})
    ledger=Ledger(tmp_path);ledger.plan(config);ledger.fund(config.id,'api',10000,evidence='engineering')
    class SamFixture:
        sends=0
        def execute_stream(self,request,**kwargs):
            self.sends+=1
            return Response(response(),2500,0,dict(response_id='engineering',observed_model='sam-3.1'))
    specialist=SamFixture();runner=Runner(tmp_path,config.id,specialist)
    image,recipe=runner._segment(case,pixels(),'engineering-source','anchor')
    assert specialist.sends==1
    assert runner._segment(case,pixels(),'engineering-source','anchor')[1]==recipe
    assert specialist.sends==1 and ledger.status(config.id)['api_budget']['lifetime_committed']==2500
    # Replay cannot purchase another mask even if received data is unsuitable.
    with pytest.raises(AcquisitionRejected):runner._segment(case,pixels('green'),'engineering-source','anchor')
    assert specialist.sends==1
    with pytest.raises(Stopped):ledger.reserve(config.id,case.id,'segment_anchor',dict(requested_model='sam-3.1',wire={'model':'sam-3.1'}),quote=2500,attempt=1)


def test_sam_preflight_excludes_video_multiple_inputs_and_unstored_transport():
    adapter=MuseResponses(key='engineering')
    wire=dict(model='sam-3.1',stream=True,store=True,metadata={'mask_encoding':'one_bit'},input=[dict(content=[dict(type='input_image',image_url='data:image/png;base64,AA==')])])
    adapter.preflight(dict(payload={'wire':wire}))
    for changed in ({'store':False},{'input':[dict(content=[dict(type='input_video')])]}, {'input':[dict(content=[dict(type='input_image'),dict(type='input_image')])]}):
        with pytest.raises(ValueError,match='SAM supports'):adapter.preflight(dict(payload={'wire':dict(wire,**changed)}))


def test_mask_rescaling_is_explicit_and_cross_cell_results_fail_closed():
    pytest.importorskip('meta_sam_parser')
    enlarged=TEXT.replace('x1=211','x1=100').replace('y1=228','y1=100').replace('x2=270','x2=219').replace('y2=254','y2=153')
    image,recipe=isolate(pixels(),response(enlarged))
    assert image.getchannel('A').getbbox()==(100,100,220,154)
    assert recipe['masks'][0]['mask_size']==[60,27]
    image=Image.new('RGB',(960,640),'white');out=io.BytesIO();image.save(out,format='PNG')
    texts=[]
    for slot in range(6):
        x=slot%3*320+100;y=slot//3*320+100
        texts.append(TEXT.removeprefix('<0f>').replace('0<|box',str(slot)+'<|box').replace('x1=211',f'x1={x}').replace('x2=270',f'x2={x+59}').replace('y1=228',f'y1={y}').replace('y2=254',f'y2={y+26}').replace('w=320;h=334','w=960;h=640'))
    text='<0f>'+','.join(texts)
    image,recipe=isolate(out.getvalue(),response(text),columns=3,rows=2)
    assert sorted(m['slot'] for m in recipe['masks'])==list(range(6))
    crossed=text.replace('x1=100;y1=100;x2=159','x1=300;y1=100;x2=359',1)
    with pytest.raises(ValueError,match='crosses cell'):isolate(out.getvalue(),response(crossed),columns=3,rows=2)
