import pytest
from PIL import Image
from framebound.v3.campaign.assessment import *
from framebound.v3.campaign.features import extract


def fixture():
    b = Binding(request_sha256='a'*64,revision_sha256='b'*64,timing_sha256='c'*64,evaluation_sha256='d'*64)
    p = Provenance(provider='engineering',requested_model='test',rubric_sha256='e'*64,raw_sha256='f'*64,execution_id='fixture')
    return abstention(b,p,[0,1],'Synthetic uncertainty'), b


def test_unknown_masks_and_legitimate_holds():
    a,b = fixture()
    assert not any(v['mask'] for v in a.targets().values())
    assert a.validate_evidence(b,[2,3],(32,32))
    frames = [Image.new('RGBA',(32,32))]*2
    features = extract(frames,[2,3],loop=True,allowed_identical_slots=[0,1])
    assert features['proposals'] == []
    assert any(w['loop_boundary'] for w in features['windows'])


def test_rubric_only_nonexistent_roi_and_stale_binding():
    a,b = fixture()
    data = a.model_dump()
    data['coverage'][0]['status'] = 'present'
    with pytest.raises(ValueError,match='observed findings'): Assessment.model_validate(data)
    data['findings'] = [dict(id='f',category='identity',slots=[0],tick_range=[0,2],subject='actor',severity='material',observed='pixel shift',expected='same identity',counterexamples='occlusion considered',roi=[0,0,99,99])]
    model = Assessment.model_validate(data)
    with pytest.raises(ValueError,match='ROI'): model.validate_evidence(b,[2,3],(32,32))
    with pytest.raises(ValueError,match='stale'): a.validate_evidence(b.model_copy(update={'request_sha256':'0'*64}),[2,3],(32,32))


def test_explicit_longer_sequence_preserves_receipts_and_timing(tmp_path):
    import hashlib, json
    from framebound.v3.corpus import prepare
    image = tmp_path/'sheet.png'
    Image.new('RGBA',(256,192),(80,90,100,255)).save(image)
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    (tmp_path/'sheet.receipt.json').write_text(json.dumps(dict(status='completed',output_sha256=sha,
        model_requested='muse-image-test',prompt_sha256='a'*64)))
    manifest = dict(schema_version='2.0',cases=[dict(id='long',family='test',split='train',holds=[1]*12,loop=True,intent='Synthetic sequence test',
        frames=[dict(source_file='sheet.png',receipt_file='sheet.receipt.json',crop=[i%4*64,i//4*64,i%4*64+64,i//4*64+64]) for i in range(12)])])
    path = tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    result = prepare(path,str(tmp_path/'project'),native_size=32)
    assert len(result['imported'][0]['frames']) == 12
    assert prepare(path,str(tmp_path/'project'),native_size=32) == result
