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
    ('','white','no matches'),
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
    config=curriculum('sam-engineering');case=config.cases[0].model_copy(update={'subject':'animal','request':'Original isolated 2D animal: one rounded heron, distinctive teal and gold palette.'})
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


def test_concrete_concept_comes_only_from_frozen_design():
    from framebound.v3.campaign.segmentation import concept_for
    config=upskill_curriculum('concepts',source_policy='sam-isolation-v5')
    concepts={concept_for(case) for case in config.cases}
    assert {'folding umbrella','chef','wooden mannequin','heron'}<=concepts
    assert not concepts&{'object','person','animal','figure'}
    with pytest.raises(ValueError,match='concrete frozen'):concept_for(config.cases[0].model_copy(update={'request':'Guess a subject'}))


@pytest.mark.parametrize('source_policy',['sam-isolation-v5','sam-spatial-v6'])
def test_segmented_sheet_reaches_strict_revision_submission(tmp_path,monkeypatch,source_policy):
    import base64,hashlib
    from PIL import ImageDraw
    from framebound.v3.campaign.curriculum import protocol
    from framebound.v3.services import loop
    from framebound.v3.provenance import RevisionProvenance
    config=upskill_curriculum('segmented-submission',source_policy=source_policy)
    ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',100000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='engineering',account_access='fixture',image_microdollars=10000,segmentation_microdollars=2500))
    case=next(c for c in config.cases if c.id==protocol(config)['rehearsal'][0])
    class GenerationFixture:
        def execute_stream(self,request,**kwargs):
            size=(96,64) if request['operation']!='anchor' else (64,64)
            im=Image.new('RGBA',size);draw=ImageDraw.Draw(im)
            for slot in range(6 if request['operation']!='anchor' else 1):
                x=slot%3*32;y=slot//3*32
                draw.rectangle((x+8,y+8,x+23,y+23),fill=(40,80,120,255))
            out=io.BytesIO();im.save(out,format='PNG')
            return Response(canonical(dict(status='completed',output=[dict(type='image_generation_call',result=base64.b64encode(out.getvalue()).decode())])),10000,1,dict(response_id='engineering',observed_model='muse-image-1.0'))
    runner=Runner(tmp_path,config.id,GenerationFixture())
    # Protocol codec has independent tests; this fixture isolates the complete
    # materialization/asset-derivation/strict-provenance integration boundary.
    def segmented(case,raw,parent,operation,**kwargs):
        return Image.open(io.BytesIO(raw)).convert('RGBA'),dict(operator='engineering-segmentation',request_id='engineering-mask',source_sha256=hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(runner,'_segment',segmented)
    _,anchor=runner._anchor(case)
    _,revision=runner._materialize(case,anchor)
    saved=loop.revision_get(runner.project,revision)['revision']
    provenance=RevisionProvenance.model_validate(saved['generation_metadata']['provenance'])
    assert len(saved['frame_asset_ids'])==6
    assert 'engineering-mask' in provenance.generations[0].transformations[0].operation
    # Replaying materialization preserves its revision and paid request count.
    assert runner._materialize(case,anchor)[1]==revision
    assert len(ledger.status(config.id)['requests'])==2


def test_spatial_prompts_use_actual_ink_and_declared_native_cells_without_class_labels():
    pytest.importorskip('meta_sam_parser')
    from framebound.v3.campaign.segmentation import spatial_prompt
    image=Image.new('RGB',(1920,1280),'white')
    from PIL import ImageDraw
    draw=ImageDraw.Draw(image)
    for slot in range(6):
        x=slot%3*640;y=slot//3*640;draw.rectangle((x+200,y+200,x+439,y+439),fill='navy')
    out=io.BytesIO();image.save(out,format='PNG')
    text,recipe=spatial_prompt(out.getvalue(),columns=3,rows=2)
    assert text.startswith('<0f>0<|box;') and text.count('<|box;')==6
    assert text.count('-<|point;')==24 and text.count('<|point;')>24
    assert 'w=1920;h=1280' in text
    assert recipe['boxes'][0]['bounds']==[195,195,445,445]
    assert recipe['boxes'][5]['bounds']==[1475,835,1725,1085]
    assert all(image.getpixel(tuple(point))==(0,0,128) for box in recipe['boxes'] for point in box['positive_ink'])
    assert all(b['object_id']==str(b['slot']) for b in recipe['boxes'])
    with pytest.raises(ValueError,match='only anchor or six-cell'):spatial_prompt(out.getvalue(),columns=2,rows=1)
    with pytest.raises(ValueError,match='layout mismatch'):spatial_prompt(pixels(),columns=3,rows=2)


def test_spatial_policy_changes_method_and_families_without_changing_old_recipe():
    old=upskill_curriculum('same-name',source_policy='sam-isolation-v5')
    new=upskill_curriculum('same-name',source_policy='sam-spatial-v6')
    assert old.source_policy=='sam-isolation-v5' and new.prices.segmentation_microdollars==2500
    assert not {c.family for c in old.cases}&{c.family for c in new.cases}
    assert all('SOURCE CONTRACT sam-spatial-v6.' in c.request for c in new.cases)


def test_spatial_wire_and_receipt_replay_keep_one_paid_attempt(tmp_path):
    pytest.importorskip('meta_sam_parser')
    config=upskill_curriculum('spatial-wire',source_policy='sam-spatial-v6')
    from framebound.v3.campaign.curriculum import protocol
    case=next(c for c in config.cases if c.id==protocol(config)['rehearsal'][0])
    ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',10000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='engineering',account_access='fixture',image_microdollars=10000,segmentation_microdollars=2500))
    class SamFixture:
        sends=[]
        def execute_stream(self,request,**kwargs):
            self.sends.append(request)
            return Response(response(),2500,0,dict(response_id='engineering',observed_model='sam-3.1'))
    fixture=SamFixture();runner=Runner(tmp_path,config.id,fixture)
    source=Image.new('RGB',(320,334),'white')
    from PIL import ImageDraw
    ImageDraw.Draw(source).rectangle((211,228,270,254),fill='navy');out=io.BytesIO();source.save(out,format='PNG');source=out.getvalue()
    _,recipe=runner._segment(case,source,'engineering','anchor')
    assert recipe['operator']=='sam-spatial-v6'
    payload=fixture.sends[0]['payload'];text=payload['wire']['input'][0]['content'][0]['text']
    assert payload['concept_recipe']=='observed-ink-object-prompts-v2'
    assert text.startswith('<0f>0<|box;') and 'person' not in text
    assert 'spatial_recipe' in payload
    assert runner._segment(case,source,'engineering','anchor')[1]==recipe
    assert len(fixture.sends)==1


def test_spatial_negative_clicks_require_actual_technical_corner_pixels():
    pytest.importorskip('meta_sam_parser')
    from framebound.v3.campaign.segmentation import spatial_prompt
    with pytest.raises(ValueError,match='negative corner'):spatial_prompt(pixels('green'))


def test_native_cell_lanes_are_bounded_unique_and_do_not_change_legacy_bindings(tmp_path):
    from framebound.v3.campaign.curriculum import protocol
    from framebound.v3.campaign.contracts import digest
    config=upskill_curriculum('native-lanes',source_policy='sam-native-cell-v7')
    case=next(c for c in config.cases if c.id==protocol(config)['rehearsal'][0])
    ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',30000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='engineering',account_access='fixture',image_microdollars=10000,segmentation_microdollars=2500))
    payload=dict(requested_model='sam-3.1',wire={'model':'sam-3.1'})
    original=ledger.reserve(config.id,case.id,'segment_generate',payload,quote=2500)
    assert 'cell' not in json.loads(original['request'])
    assert original['binding']==digest([config.id,case.id,'segment_generate',0,0])
    lanes=[ledger.reserve(config.id,case.id,'segment_generate',payload,quote=2500,cell=i) for i in range(6)]
    assert len({x['binding'] for x in lanes}|{original['binding']})==7
    assert ledger.reserve(config.id,case.id,'segment_generate',payload,quote=2500,cell=0)['id']==lanes[0]['id']
    with pytest.raises(Stopped):ledger.reserve(config.id,case.id,'segment_generate',dict(payload,changed=True),quote=2500,cell=0)
    for cell in [-1,6,True]:
        with pytest.raises(ValueError,match='cell lane'):ledger.reserve(config.id,case.id,'segment_generate',payload,quote=2500,cell=cell)
    with pytest.raises(ValueError,match='cell lane'):ledger.reserve(config.id,case.id,'generate',payload,quote=10000,images=1,cell=0)


def test_raw_ink_clipping_cannot_be_hidden_by_an_interior_mask():
    pytest.importorskip('meta_sam_parser')
    from PIL import ImageDraw
    from framebound.v3.campaign.segmentation import spatial_prompt,raw_clip_check
    image=Image.new('RGB',(320,320),'white');draw=ImageDraw.Draw(image)
    draw.rectangle((100,100,220,220),fill='navy')
    def encoded():
        out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()
    raw=encoded();_,proposal=spatial_prompt(raw)
    assert raw_clip_check(raw,proposal)['margin']==6
    draw.rectangle((0,150,110,155),fill='navy');raw=encoded();_,proposal=spatial_prompt(raw)
    with pytest.raises(ValueError,match='clips native cell'):raw_clip_check(raw,proposal)


def test_native_cells_preflight_all_before_send_and_reassemble_original_rgb(tmp_path,monkeypatch):
    pytest.importorskip('meta_sam_parser')
    from PIL import ImageDraw
    config=upskill_curriculum('native-preflight',source_policy='sam-native-cell-v7')
    ledger=Ledger(tmp_path);ledger.plan(config);runner=Runner(tmp_path,config.id,object());case=config.cases[0]
    sheet=Image.new('RGB',(960,640),'white');draw=ImageDraw.Draw(sheet)
    for i in range(6):draw.rectangle((i%3*320+100,i//3*320+100,i%3*320+220,i//3*320+220),fill='navy')
    def encoded():
        out=io.BytesIO();sheet.save(out,format='PNG');return out.getvalue()
    calls=[]
    def segment(case,raw,parent,operation,**kwargs):
        calls.append(kwargs['cell']);im=Image.open(io.BytesIO(raw)).convert('RGBA');im.putalpha(255)
        return im,dict(request_id='request-'+str(kwargs['cell']))
    monkeypatch.setattr(runner,'_segment',segment)
    raw=encoded();image,recipe=runner._segment_cells(case,raw,'original','generate')
    assert image.convert('RGB').tobytes()==sheet.tobytes() and calls==list(range(6))
    assert recipe['request_ids']==['request-'+str(i) for i in range(6)]
    calls.clear();draw.rectangle((640,470,750,475),fill='navy')
    with pytest.raises(AcquisitionRejected,match='clips native cell'):runner._segment_cells(case,encoded(),'new','generate')
    assert not calls


def test_native_received_cell_replay_never_reposts_or_consumes_other_cell(tmp_path):
    pytest.importorskip('meta_sam_parser')
    from framebound.v3.campaign.curriculum import protocol
    from PIL import ImageDraw
    config=upskill_curriculum('native-replay',source_policy='sam-native-cell-v7')
    case=next(c for c in config.cases if c.id==protocol(config)['rehearsal'][0])
    ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.fund(config.id,'api',30000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='engineering',account_access='fixture',image_microdollars=10000,segmentation_microdollars=2500))
    class SamFixture:
        sends=[]
        def execute_stream(self,request,**kwargs):
            self.sends.append(request)
            return Response(response(),2500,0,dict(response_id='engineering-'+str(len(self.sends)),observed_model='sam-3.1'))
    fixture=SamFixture();runner=Runner(tmp_path,config.id,fixture)
    im=Image.new('RGB',(320,334),'white');ImageDraw.Draw(im).rectangle((211,228,270,254),fill='navy')
    out=io.BytesIO();im.save(out,format='PNG');source=out.getvalue()
    first=runner._segment(case,source,'original','generate',cell=0)[1]
    second=runner._segment(case,source,'original','generate',cell=1)[1]
    assert first['request_id']!=second['request_id'] and len(fixture.sends)==2
    assert runner._segment(case,source,'original','generate',cell=0)[1]==first
    assert len(fixture.sends)==2
    with pytest.raises(AcquisitionRejected,match='source differs'):runner._segment(case,pixels('green'),'original','generate',cell=0)
    assert len(fixture.sends)==2


def test_whole_sheet_contract_preflights_then_masks_once(tmp_path,monkeypatch):
    pytest.importorskip('meta_sam_parser')
    from PIL import ImageDraw
    config=upskill_curriculum('sheet-mask-fixture',source_policy='sam-sheet-v8',transport='stream-all-v2')
    ledger=Ledger(tmp_path);ledger.plan(config);runner=Runner(tmp_path,config.id,object());case=config.cases[0]
    sheet=Image.new('RGB',(960,640),'white');draw=ImageDraw.Draw(sheet)
    for i in range(6):draw.rectangle((i%3*320+100,i//3*320+100,i%3*320+220,i//3*320+220),fill='navy')
    def encoded():
        out=io.BytesIO();sheet.save(out,format='PNG');return out.getvalue()
    calls=[]
    def segment(case,raw,parent,operation,**kwargs):
        calls.append((raw,kwargs));return Image.open(io.BytesIO(raw)).convert('RGBA'),dict(request_id='single-whole-sheet-request')
    monkeypatch.setattr(runner,'_segment',segment)
    source=encoded();image,recipe=runner._segment_sheet(case,source,'original','generate')
    assert len(calls)==1 and calls[0][0]==source and calls[0][1]['columns']==3 and calls[0][1]['rows']==2
    assert recipe['request_id']=='single-whole-sheet-request' and len(recipe['raw_cell_clipping'])==6
    assert image.convert('RGB').tobytes()==sheet.tobytes()
    calls.clear();draw.rectangle((640,470,750,475),fill='navy')
    with pytest.raises(AcquisitionRejected,match='clips native cell'):runner._segment_sheet(case,encoded(),'new','generate')
    assert not calls


def test_reduced_template_scale_is_frozen_opt_in_without_legacy_byte_changes():
    old=upskill_curriculum('old-scale',source_policy='sam-sheet-v8')
    assert old.conditioning_subject_max==256 and 'conditioning_subject_max' not in old.model_dump(mode='json')
    new=upskill_curriculum('smaller-scale',source_policy='sam-sheet-v8',conditioning_subject_max=192)
    assert new.model_dump(mode='json')['conditioning_subject_max']==192
    with pytest.raises(ValueError,match='whole-sheet'):upskill_curriculum('wrong-policy',source_policy='sam-native-cell-v7',conditioning_subject_max=192)
    with pytest.raises(ValueError):upskill_curriculum('unfrozen-scale',source_policy='sam-sheet-v8',conditioning_subject_max=160)
