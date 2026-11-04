"""Offline safeguards for the paid movement demo builder."""
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

spec = importlib.util.spec_from_file_location('movement_demo', Path(__file__).parents[1] / 'scripts/build_movement_demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_unresolved_send_never_reposts(tmp_path, monkeypatch):
    folder = tmp_path / 'private' / 'initial'
    folder.mkdir(parents=True)
    (folder / 'request.json').write_text('{"committed_microdollars":10000}')
    monkeypatch.setattr(demo, 'MuseResponses', lambda: pytest.fail('must not post again'))
    with pytest.raises(FileExistsError):
        demo.send(tmp_path, 'initial', 'muse-image-1.0', 'private prompt', [])
    assert json.loads((folder / 'request.json').read_text())['committed_microdollars'] == 10000


def test_completed_send_reuses_retained_response(tmp_path, monkeypatch):
    folder = tmp_path / 'private' / 'initial'
    folder.mkdir(parents=True)
    (folder / 'response.json').write_bytes(b'{"status":"completed"}')
    monkeypatch.setattr(demo, 'MuseResponses', lambda: pytest.fail('must not post again'))
    assert demo.send(tmp_path, 'initial', 'muse-image-1.0', 'ignored', []) == b'{"status":"completed"}'


def test_native_measurements_expose_scale_drift():
    frames = []
    for bottom in (70, 90, 70):
        frame = Image.new('RGBA', (100,100))
        frame.paste((40,30,20,255), (30,10,60,bottom))
        frames.append(frame)
    measured = demo.metrics(frames)
    assert measured['height_spread'] > .2
    assert measured['baseline_spread'] == .2
    assert 'bbox_height' in measured['feature_names']


def test_builder_preserves_control_and_publishes_complete_revision(tmp_path, monkeypatch):
    reference = tmp_path / 'reference.png'
    Image.new('RGBA', (10,10)).save(reference)
    config = tmp_path / 'brief.json'
    config.write_text(json.dumps(dict(references=[str(reference)], brief='same basic brief', batches=[
        dict(id='first', instruction='poses one to three', states={'run':[0,1,2]}),
        dict(id='second', instruction='poses four to six', states={'run':[0,1,2], 'idle':[0]}),
    ])))
    sent = []
    def fake_send(root, name, model, prompt, images):
        sent.append((name, prompt))
        return name.encode()
    monkeypatch.setattr(demo, 'send', fake_send)
    monkeypatch.setattr(demo, 'extract_image', lambda raw: raw)
    def native_frames(raw):
        images=[]
        for _ in range(3):
            image=Image.new('RGBA',(100,100))
            image.paste((0,200 if b'repair' in raw else 50,0,255),(40,40,60,60))
            images.append(image)
        return images
    monkeypatch.setattr(demo, 'frames', native_frames)
    monkeypatch.setattr(demo, 'metrics', lambda images: dict(clipped_slots=[], height_spread=0, baseline_spread=0))
    monkeypatch.setattr(demo, 'assess', lambda root,name,*args: dict(score=95 if 'recheck' in name else 60, issues=[] if 'recheck' in name else ['motion'], repair='fix motion'))
    monkeypatch.setattr(demo.sys, 'argv', ['build', '--config', str(config), '--root', str(tmp_path)])
    (tmp_path / 'private').mkdir()
    demo.main()
    manifest = json.loads((tmp_path / 'published/manifest.json').read_text())
    assert manifest['states']['run']['frames'] == list(range(6))
    assert manifest['repairs_selected'] == 2
    output = tmp_path / 'published' / manifest['revision']
    assert len(list(output.glob('*.png'))) == 12
    assert Image.open(output / 'direct-0.png').getpixel((50,50))[1] == 50
    assert Image.open(output / 'framework-0.png').getpixel((50,50))[1] == 200
    assert len([name for name,_ in sent if name.endswith('-initial')]) == 2


def test_local_preflight_failure_does_not_create_a_committed_send(tmp_path,monkeypatch):
    class Adapter:
        def preflight(self,request):raise ValueError('TEST-ONLY rejected before transport')
        def execute(self,*a,**kw):pytest.fail('must not send failed preflight')
    monkeypatch.setattr(demo,'MuseResponses',Adapter)
    with pytest.raises(ValueError,match='before transport'):demo.send(tmp_path,'local-rejected','muse-image-1.0','TEST-ONLY',[])
    assert not (tmp_path/'private/local-rejected/request.json').exists()
