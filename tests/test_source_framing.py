"""Small extremities must not hide behind average-border alpha or later padding."""
import pytest
from PIL import Image, ImageDraw

from framebound.v3.intake import framing, inspect


def figure():
    im = Image.new('RGBA',(200,200))
    ImageDraw.Draw(im).rectangle((50,30,150,170),fill=(80,40,20,255))
    return im


@pytest.mark.parametrize('tip',[(0,100),(199,100),(100,0),(100,199)])
def test_single_pixel_tip_fails_even_when_average_border_passes(tip):
    im = figure()
    im.putpixel(tip,(120,20,20,255))
    assert inspect(im)['eligible']
    assert not framing(im)['eligible']


def test_padding_cannot_hide_original_crop():
    im = figure()
    ImageDraw.Draw(im).line((0,100,50,100),fill=(180,20,20,255),width=2)
    padded = Image.new('RGBA',(300,300))
    padded.alpha_composite(im,(50,50))
    assert framing(padded)['eligible']
    check = framing(padded,source_box=(50,50,250,250))
    assert not check['eligible']
    assert 'left' in check['unsafe_edges']


def test_safe_native_resolution_and_margin_are_separate_requirements():
    im = figure()
    assert framing(im)['eligible']
    assert not framing(im,minimum_subject_span=160)['eligible']
    check = framing(im,minimum_subject_span=140)
    assert check['native_subject_span']==141
    assert check['clearance_pixels']['bottom']==29


def test_reject_invalid_source_bounds():
    with pytest.raises(ValueError):
        framing(figure(),source_box=(-1,0,200,200))
