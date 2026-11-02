import io
from PIL import Image,ImageDraw
import pytest
from framebound.v3.intake import inspect,keyed,cell
from framebound.v3.services import studio,loop,interventions
from framebound.v2.services.errors import InvalidInput
from framebound.v2.services.authz import Actor
from framebound.v2.services.assets import import_asset
from test_agent_loop import setup

@pytest.mark.parametrize('color',['white','black','#e9e0cf'])
def test_opaque_and_token_alpha_are_not_isolated(color):
    im=Image.new('RGBA',(64,64),color)
    assert not inspect(im)['eligible']
    im.putpixel((0,0),(0,0,0,0))
    assert not inspect(im)['eligible']

def test_empty_checkerboard_and_border_scene_fail():
    assert not inspect(Image.new('RGBA',(64,64)))['eligible']
    im=Image.new('RGBA',(64,64),'white');d=ImageDraw.Draw(im)
    for x in range(0,64,8):
        for y in range(0,64,8):
            if (x+y)%16:d.rectangle((x,y,x+7,y+7),fill='#ccc')
    assert not inspect(im)['eligible']
    im=Image.new('RGBA',(64,64));ImageDraw.Draw(im).rectangle((0,0,63,25),fill='blue')
    assert not inspect(im)['eligible']

def test_declared_key_preserves_white_foreground_and_closed_gaps():
    im=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(im);d.ellipse((12,8,52,56),fill='white');d.ellipse((25,20,35,30),fill='#ff00ff')
    result,recipe=keyed(im)
    assert inspect(result)['eligible'] and result.getpixel((20,30))==(255,255,255,255)
    assert result.getpixel((30,25))[3]==0 and recipe['enclosed_key_pixels']>0
    with pytest.raises(ValueError):keyed(Image.new('RGBA',(64,64),'white'))

def test_only_uniform_sheet_rules_can_be_removed():
    im=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(im);d.rectangle((20,20,40,40),fill='blue');d.line((0,0,63,0),fill='black');d.line((0,0,0,63),fill='black')
    result,recipe=cell(im)
    assert inspect(result)['eligible'] and recipe['uniform_sheet_rules_removed']
    d.rectangle((0,0,63,20),fill='white')
    with pytest.raises(ValueError):cell(im)


def test_white_rules_require_explicit_source_contract_and_preserve_art():
    im=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(im)
    d.ellipse((20,20,40,40),fill='white');d.rectangle((0,0,63,63),outline='white',width=3)
    with pytest.raises(ValueError):cell(im)
    result,recipe=cell(im,declared_white_rules=True)
    assert inspect(result)['eligible'] and result.getpixel((30,30))==(255,255,255,255)
    assert result.getpixel((30,0))[3]==0 and recipe['white_sheet_rules_explicitly_declared']
    assert im.getpixel((30,0))==(255,255,255,255) # original remains untouched
    d.rectangle((0,0,63,8),fill='white') # nine-pixel matte is outside the contract
    with pytest.raises(ValueError):cell(im,declared_white_rules=True)
    with pytest.raises(ValueError):cell(Image.new('RGBA',(64,64),'white'),declared_white_rules=True)


def test_declared_rules_do_not_remove_nonuniform_scenery_or_wrong_key():
    im=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(im)
    d.rectangle((20,20,40,40),fill='blue');d.line((0,0,63,0),fill='white');d.rectangle((4,0,20,0),fill='green')
    with pytest.raises(ValueError):cell(im,declared_white_rules=True)


def test_scaled_white_rule_antialiasing_keeps_subject_and_requires_white_seed():
    sheet=Image.new('RGBA',(1920,1280),'#ff00ff');draw=ImageDraw.Draw(sheet)
    draw.rectangle((0,0,1919,1279),outline='white',width=6)
    for x in (640,1280):draw.rectangle((x-3,0,x+2,1279),fill='white')
    draw.rectangle((0,637,1919,642),fill='white')
    for slot in range(6):
        x=slot%3*640;y=slot//3*640
        draw.ellipse((x+200,y+200,x+440,y+440),fill='white')
    original=sheet.tobytes()
    for slot in range(6):
        x=slot%3*640;y=slot//3*640
        frame=sheet.crop((x,y,x+640,y+640)).resize((256,256),Image.Resampling.LANCZOS)
        with pytest.raises(ValueError):cell(frame)
        result,recipe=cell(frame,declared_white_rules=True)
        assert inspect(result)['eligible'] and result.getpixel((128,128))==(255,255,255,255)
        assert recipe['uniform_sheet_rules_removed'] and 'observed-white' in recipe['white_rule_edge_recipe']
    assert sheet.tobytes()==original
    pink=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(pink)
    d.ellipse((20,20,40,40),fill='blue');d.rectangle((0,0,63,2),fill=(255,180,255,255))
    with pytest.raises(ValueError):cell(pink,declared_white_rules=True)
    # A nominally straight raster rule can vary by one pixel after resampling;
    # every edge position still needs observed white within the bounded band.
    varied=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(varied)
    d.ellipse((20,20,40,40),fill='white')
    for x in range(64):
        varied.putpixel((x,0),(255,255,255,255) if x%2 else (248,180,247,255))
        varied.putpixel((x,1),(248,180,247,255) if x%2 else (255,255,255,255))
    result,recipe=cell(varied,declared_white_rules=True)
    assert inspect(result)['eligible'] and result.getpixel((30,30))==(255,255,255,255)


def test_native_rule_budget_preserves_canonical_eight_pixel_limit():
    im=Image.new('RGBA',(640,640),'#ff00ff');d=ImageDraw.Draw(im)
    d.ellipse((180,180,460,460),fill='blue');d.rectangle((0,0,639,17),fill='white')
    result,recipe=cell(im,declared_white_rules=True,rule_pixels=8*640//256)
    assert inspect(result.resize((256,256),Image.Resampling.LANCZOS))['eligible']
    assert recipe['native_rule_pixel_limit']==20
    d.rectangle((0,0,639,20),fill='white')
    with pytest.raises(ValueError):cell(im,declared_white_rules=True,rule_pixels=20)
    with pytest.raises(ValueError):cell(im,rule_pixels=65)
    split=Image.new('RGBA',(64,64),(240,0,216,255));d=ImageDraw.Draw(split)
    d.ellipse((20,20,40,40),fill='white');d.rectangle((0,0,63,2),fill='white')
    d.rectangle((0,63,63,63),fill=(228,77,225,255))
    result,recipe=cell(split,declared_white_rules=True)
    assert inspect(result)['eligible'] and result.getpixel((30,30))==(255,255,255,255)
    im=Image.new('RGBA',(64,64),'#b000b0');ImageDraw.Draw(im).ellipse((20,20,40,40),fill='white')
    with pytest.raises(ValueError):cell(im,declared_white_rules=True)

def test_input_gate_precedes_quality_and_blocks_historical_approval(tmp_path):
    p,spec,frames=setup(tmp_path)
    im=Image.new('RGBA',(8,8),'white');path=tmp_path/'bad.png';im.save(path);import_asset(p,str(path),'opaque',source_kind='generated')
    result=loop.submit(p,'run','opaque-revision',['opaque']*3)
    assert result['technical_status']=='fail'
    assert all(t['check_id'].startswith(('media','intake')) for t in result['targets'])
    assert not loop.eligibility(p,'run')['eligible']
    cid=studio.seed(p,'opaque-revision');assert studio.snapshot(p,cid)['case']['status']=='excluded'
    reviewer=Actor(type='reviewer',id='test')
    with pytest.raises(InvalidInput):studio.approve(p,reviewer,cid,'opaque-revision')
    with pytest.raises(InvalidInput):interventions.decision(p,reviewer,'run',dict(id='bad-approve',revision_id='opaque-revision',evaluation_id='evaluation:opaque-revision',action='approve'))
    studio.allocate(p,10000)
    studio.replace(p,reviewer,cid,dict(id='replacement',version_id='opaque-revision',category='animal',description='A blue cat walking in profile'))
    assert studio.snapshot(p)['budget']['reserved']==10000

def test_key_edge_unmatting_retains_non_key_interiors():
    im=Image.new('RGBA',(64,64),'#ff00ff');d=ImageDraw.Draw(im)
    d.rectangle((16,16,47,47),fill=(0,100,255,255))
    # Synthetic 50% antialias between blue subject and declared key.
    d.line((15,16,15,47),fill=(128,50,255,255))
    result,recipe=keyed(im)
    assert result.getpixel((20,20))==(0,100,255,255)
    edge=result.getpixel((15,25))
    assert edge[0]<5 and 120<=edge[3]<=135 and recipe['edge_pixels']>0

def test_white_matte_with_transparent_padding_cannot_bypass_intake():
    im=Image.new('RGBA',(64,64));ImageDraw.Draw(im).rectangle((5,5,58,58),fill='white')
    assert not inspect(im)['eligible']
    # A white animal/figure silhouette remains a valid isolated raster.
    im=Image.new('RGBA',(64,64));ImageDraw.Draw(im).ellipse((5,5,58,58),fill='white')
    assert inspect(im)['eligible']
