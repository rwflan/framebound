import base64
from PIL import Image
import pytest
from framebound.v2 import storage as S
from framebound.v2.services import jobs as J,orchestrator as O
from framebound.v2.services.errors import InvalidInput
from test_v2_r3_providers import _seed,_pack_bits,_sam_line
from test_dispatch_reservations import send,response
from test_provider_grants import grant,queued

def segmentation(project,brief,key,settings=None):
    env=J.submit_generation(project,brief,[],key,provider_settings={'provider':'sam','source_asset_id':'f0',**(settings or {})})
    jid=env.artifacts[0]['id'];rid=O.start_run(project,[jid])['run_id']
    return rid,jid,J.job_claim(project,jid,'worker',expected_version=J.job_get(project,jid)['version'])

def test_failed_provider_status_is_failed_job_not_recorded_success(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    ids=segmentation(p,brief,'failed')
    out=send(p,ids,lambda req:{'status':'failed','id':'fixture-failure','output':[]})
    assert out['action']=='failed'
    job=J.job_get(p,ids[1])['job']
    assert job['provider_outcome']=='failed'
    assert job['output_asset_ids']==[]
    assert job['response_artifact']

def test_mask_proposal_has_native_pixels_source_hash_and_no_approval(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    raster=bytes(1 if 2<=i%64<6 and 2<=i//64<6 else 0 for i in range(4096))
    payload=base64.b85encode(_pack_bits(raster)).decode()
    text=_sam_line(0,[(0,(2,2,6,6,64,64),(64,64,'~',payload))])
    ids=segmentation(p,brief,'mask')
    out=send(p,ids,lambda req:{'status':'completed','id':'fixture-sam','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]})
    assert out['action']=='succeeded' and out['usable']
    con=S.connect(p)
    try:
        job=J.job_get(p,ids[1])['job'];asset=S.get(con,'assets',job['output_asset_ids'][0])[0]
        ann=S.get(con,'annotation_revisions',job['output_annotation_ids'][0])[0]
        assert ann['annotator_type']=='model_proposed' and ann['reviewer'] is None
        assert ann['source_pixel_sha256']==S.get(con,'assets','f0')[0]['pixel_sha256']
        assert asset['parent_asset_ids']==['f0'] and asset['source_job_id']==ids[1]
        assert sum(v>127 for v in Image.open(S.blob_path(p,asset['byte_sha256'])).convert('L').tobytes())==16
    finally:con.close()

def test_image_and_segmentation_share_operator_grant(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    grant(p,monkeypatch,max_dispatches=1,models=['muse-image-1.0','sam-3.1'])
    assert send(p,queued(p,brief,'image'),lambda req:response(p))['action']=='succeeded'
    ids=segmentation(p,brief,'sam',{'grant_id':'grant'});calls=[]
    with pytest.raises(InvalidInput,match='grant dispatch ceiling'):send(p,ids,lambda req:calls.append(1))
    assert calls==[]
