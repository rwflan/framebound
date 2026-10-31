import io
import json
import zipfile

import pytest
from PIL import Image

from framebound.v3.campaign.contracts import canonical
from framebound.v3.campaign.transfer import FeatureRow,FeatureShard,inspect_payload,preupload,transfer
from framebound.v3.campaign.export import build,validate


def shard():
    return FeatureShard(rows=[FeatureRow(case_id='a'*64,family_id='b'*64,split='train',features=[[0.1]*8],targets=[0]*9,assessed=[False]*9)])


def test_actual_transferred_payload_has_no_image_or_arbitrary_metadata():
    raw,manifest=preupload(shard());captured=[]
    transfer(raw,lambda bytes_:captured.append(bytes_))
    assert captured==[raw] and not manifest['contains_pixels']
    assert inspect_payload(captured[0]).rows[0].assessed==[False]*9
    for data in [b'\x89PNG\r\n',b'PK\x03\x04',canonical(dict(shard().model_dump(),prompt='PRIVATE'))]:
        with pytest.raises(ValueError): transfer(data,lambda _:pytest.fail('denied bytes transferred'))
    payload=shard().model_dump();payload['rows'][0]['features']=[[0.]*64 for _ in range(64)]
    with pytest.raises(ValueError): inspect_payload(canonical(payload))
    payload=shard().model_dump();payload['rows'][0]['frames']=['image.png']
    with pytest.raises(ValueError): inspect_payload(canonical(payload))


def test_local_exports_keep_failed_candidates_and_unknown_masks(tmp_path):
    p=tmp_path/'frame.png';Image.new('RGBA',(8,8)).save(p)
    (tmp_path/'request.json').write_text('{"request":"Engineering-only"}')
    example=dict(id='test',family='family',split='train',frames=['frame.png'],holds=[1],loop=False,request_file='request.json',
        conditioning_files=['frame.png'],provenance={'source':'engineering'},baseline_frames=['frame.png'],outcome='ambiguous',
        comparison={'preference':'insufficient_evidence'})
    result=build(tmp_path,'test',[example],version='1')
    assert validate(result['path'])['ok']
    assert result['manifest']['counts']['editing']==0
    assert result['manifest']['counts']['preference']==1
    row=json.loads((__import__('pathlib').Path(result['path'])/'detection.jsonl').read_text())
    assert not any(v['mask'] for v in row['labels'].values())


def test_pure_job_duplicate_results_and_hash_verification():
    import hashlib
    from framebound.v3.campaign.remote import Job,execute_pure,verify_result
    raw,_=preupload(shard())
    job=Job(payload_sha256=hashlib.sha256(raw).hexdigest(),recipe_sha256='c'*64,image_digest='sha256:'+'d'*64)
    def executor(shard,job,key): return dict(job=key,weights=[0.1,0.2])
    one=execute_pure(raw,job,executor);two=execute_pure(raw,job,executor)
    assert one['result_sha256']==two['result_sha256']
    assert verify_result(one,job)['weights']==[0.1,0.2]
    one['result']['weights'][0]=9
    with pytest.raises(ValueError,match='hash mismatch'): verify_result(one,job)
    assert job.quote()<10000000
