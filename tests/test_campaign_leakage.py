"""Split quarantine must confirm visual identity, not just hash collisions."""
import hashlib
from pathlib import Path

import pytest
from PIL import Image,ImageDraw,PngImagePlugin

from framebound.v3.campaign.leakage import exclusions,legacy_exclusions,confirm_near_duplicate,_signature


def picture(path,shape='circle',color='red',*,offset=0,metadata=None):
    image=Image.new('RGB',(768,512),'white');draw=ImageDraw.Draw(image)
    for slot in range(6):
        x=slot%3*256+128+offset;y=slot//3*256+128
        if shape=='circle':draw.ellipse((x-32,y-32,x+32,y+32),fill=color)
        elif shape=='square':draw.rectangle((x-32,y-32,x+32,y+32),fill=color)
        elif shape=='thin':draw.rectangle((x-10,y-48,x+10,y+48),fill=color)
        elif shape=='ellipse':draw.ellipse((x-10,y-48,x+10,y+48),fill=color)
    if metadata:
        info=PngImagePlugin.PngInfo();info.add_text('fixture',metadata);image.save(path,pnginfo=info)
    else:image.save(path)
    return path


def example(path,rid,split,*,family=None,conditioning=(),ancestry=()):
    def artifact(p):return dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    return dict(metadata=dict(id=rid,family=family or rid,split=split,frames=[artifact(path)],
        conditioning=[artifact(p) for p in conditioning],ancestry=list(ancestry)))


def test_identical_coarse_hash_different_drawings_do_not_join_splits(tmp_path):
    left=picture(tmp_path/'a.png','circle','red');right=picture(tmp_path/'b.png','square','purple')
    assert _signature(str(left))[0]==_signature(str(right))[0]
    rows=[example(left,'a','train'),example(right,'b','validation')]
    assert set(legacy_exclusions(rows,tmp_path))=={'a','b'}
    assert not confirm_near_duplicate(left,right)['confirmed']
    evidence=[];assert exclusions(rows,tmp_path,evidence=evidence)=={}
    assert evidence and all(not e['confirmed'] for e in evidence)


@pytest.mark.parametrize('basis',['family','ancestry','shared_conditioning'])
def test_nonvisual_split_gates_remain_absolute(tmp_path,basis):
    a=picture(tmp_path/'a.png','circle','red');b=picture(tmp_path/'b.png','thin','green')
    rows=[example(a,'a','train'),example(b,'b','validation')]
    if basis=='family':rows[1]['metadata']['family']='a'
    if basis=='ancestry':rows[1]['metadata']['ancestry']=['a']
    if basis=='shared_conditioning':rows[1]['metadata']['conditioning']=rows[0]['metadata']['frames']
    assert set(exclusions(rows,tmp_path))=={'a','b'}


@pytest.mark.parametrize('variant',['metadata','recolor','shift'])
def test_actual_duplicate_variants_stay_quarantined(tmp_path,variant):
    a=picture(tmp_path/'a.png','circle','red')
    b=picture(tmp_path/'b.png','circle','blue' if variant=='recolor' else 'red',offset=4 if variant=='shift' else 0,metadata='different bytes' if variant=='metadata' else None)
    assert hashlib.sha256(a.read_bytes()).hexdigest()!=hashlib.sha256(b.read_bytes()).hexdigest()
    assert confirm_near_duplicate(a,b)['confirmed']
    assert (_signature(str(a))[0]^_signature(str(b))[0]).bit_count()<=4
    assert set(exclusions([example(a,'a','train'),example(b,'b','validation')],tmp_path))=={'a','b'}


def test_all_collision_owners_are_checked_not_only_last_hash_owner(tmp_path):
    a=picture(tmp_path/'a.png','circle','red');b=picture(tmp_path/'b.png','square','purple');copy=picture(tmp_path/'copy.png','circle','red',metadata='reencoded')
    assert _signature(str(a))[0]==_signature(str(b))[0]==_signature(str(copy))[0]
    rows=[example(a,'a','train'),example(b,'b','train'),example(copy,'copy','validation')]
    assert set(exclusions(rows,tmp_path))=={'a','copy'}
