"""Offline framing-repair and native-publication regressions."""
import json
from pathlib import Path

from PIL import Image
import pytest

from scripts import build_individual_demo as demo


def config(tmp_path):
    reference=tmp_path/'reference.png'
    Image.new('RGBA',(8,8)).save(reference)
    return dict(references=[str(reference)],brief='shared base instructions',native_canvas=[200,200],
                minimum_subject_span=80,max_repairs=1,poses=[dict(id='run',instruction='run contact',image_size='1024x1536',states={'run':[0]})])


def gate(safe):
    return dict(framing=dict(eligible=safe,unsafe_edges=[] if safe else ['left'],reasons=[] if safe else ['clipped cape']))


def judgement():
    return dict(score=95,issues=[],repair='restore full cape',wardrobe_matches=True,complete_silhouette=True)


def test_horizontal_clip_triggers_wider_generation_and_retains_control(tmp_path,monkeypatch):
    calls=[]
    def send(root,name,model,prompt,images,**kwargs):
        calls.append((name,kwargs['image_size']))
        return name.encode()
    monkeypatch.setattr(demo,'send',send)
    monkeypatch.setattr(demo,'extract_image',lambda raw:raw)
    def decode(raw,_):
        image=Image.new('RGBA',(100,120))
        image.paste((20,100 if b'repair' in raw else 40,50,255),(10,10,90,110))
        if b'repair' not in raw:image.putpixel((0,60),(20,40,50,255))
        return image,gate(b'repair' in raw)
    monkeypatch.setattr(demo,'decode',decode)
    monkeypatch.setattr(demo,'review',lambda *args:judgement())
    (tmp_path/'private').mkdir()
    demo.build(config(tmp_path),tmp_path)
    manifest=json.loads((tmp_path/'published/manifest.json').read_text())
    assert calls==[('run-initial','1024x1536'),('run-repair-wide-0','1536x1024')]
    assert manifest['repairs_selected']==1
    assert manifest['framework_framing_pass']
    output=tmp_path/'published'/manifest['revision']
    assert Image.open(output/'direct-0.png').getpixel((100,100))[1]==40
    assert Image.open(output/'framework-0.png').getpixel((100,100))[1]==100
    assert manifest['actor_bounds']==[50,90,140,190]


def test_failed_framing_never_replaces_existing_demo(tmp_path,monkeypatch):
    monkeypatch.setattr(demo,'send',lambda *a,**kw:b'failed')
    monkeypatch.setattr(demo,'extract_image',lambda raw:raw)
    monkeypatch.setattr(demo,'decode',lambda *a:(Image.new('RGBA',(100,120),'blue'),gate(False)))
    monkeypatch.setattr(demo,'review',lambda *a:judgement())
    (tmp_path/'private').mkdir()
    (tmp_path/'published').mkdir()
    manifest=tmp_path/'published/manifest.json'
    manifest.write_text('{"revision":"previous-valid-demo"}')
    with pytest.raises(ValueError,match='publication withheld'):
        demo.build(config(tmp_path),tmp_path)
    assert json.loads(manifest.read_text())['revision']=='previous-valid-demo'
    assert (tmp_path/'private/assessment-summary.json').exists()


def test_letterboxing_never_shrinks_or_crops_source(tmp_path):
    cfg=dict(native_canvas=[64,64])
    image=Image.new('RGBA',(65,64),'red')
    with pytest.raises(ValueError,match='crop an original'):
        demo.publish(cfg,tmp_path,[image],[image],[],{})


def test_source_format_density_preserves_pixels_and_expands_viewer_bounds(tmp_path):
    cfg=dict(native_canvas=[200,200],minimum_subject_span=50)
    portrait=Image.new('RGBA',(100,120))
    portrait.paste((20,40,60,255),(10,10,90,110))
    wide=Image.new('RGBA',(120,80))
    wide.paste((20,40,60,255),(10,10,110,70))
    (tmp_path/'private').mkdir()
    demo.publish(cfg,tmp_path,[portrait],[wide],[dict(selected='repair-0')],{'idle':dict(frames=[0],duration_ticks=[90],loop=True)})
    manifest=json.loads((tmp_path/'published/manifest.json').read_text())
    assert manifest['source_pixel_scales']==dict(direct=[1.0],framework=[1.5])
    output=tmp_path/'published'/manifest['revision']/'framework-0.png'
    restored=Image.open(output).crop((40,120,160,200))
    assert restored.tobytes()==wide.tobytes()
    assert manifest['actor_bounds'][0] <= 25
    assert manifest['actor_bounds'][2] >= 175


def test_playback_contract_change_publishes_new_immutable_revision(tmp_path):
    cfg=dict(native_canvas=[200,200],minimum_subject_span=50)
    image=Image.new('RGBA',(100,120))
    image.paste((20,40,60,255),(10,10,90,110))
    (tmp_path/'private').mkdir()
    old_states={'idle':dict(frames=[0],duration_ticks=[90],loop=True)}
    demo.publish(cfg,tmp_path,[image],[image],[],old_states)
    first=json.loads((tmp_path/'published/manifest.json').read_text())
    old_image=(tmp_path/'published'/first['revision']/'framework-0.png').read_bytes()
    new_states={'idle':dict(frames=[0],duration_ticks=[30],loop=True)}
    demo.publish(cfg,tmp_path,[image],[image],[],new_states)
    second=json.loads((tmp_path/'published/manifest.json').read_text())
    assert first['revision']!=second['revision']
    assert (tmp_path/'published'/first['revision']/'framework-0.png').read_bytes()==old_image
