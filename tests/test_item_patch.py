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
