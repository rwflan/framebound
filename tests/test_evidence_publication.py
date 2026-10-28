"""Independent evidence/scope counterexamples, not source-string gates."""
import io
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import Image
from framebound.v2 import domain as D,storage as S
from framebound.v2.checks import evaluate as E
from framebound.v2.services import assets as AS,annotations as ANN,clips,corrections as C,masks as M
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError, InvalidInput
from framebound.v2.services.evidence import verify_evidence
from framebound.v2.media.canonical import canonical_pixels
from test_v2_r3_providers import _seed as seed3
from test_v2_r5_export import _seed as seed5

HUMAN=Actor(type='reviewer',id='test-human');MODEL=Actor(type='orchestrator',id='test-worker')

def test_protected_raster_contents_change_identity_and_verdict(tmp_path):
    p=str(tmp_path);seed3(p);con=S.connect(p)
    try:
        c=S.get(con,'contract_revisions','contract-R3')[0]
        frames=[Image.open(S.blob_path(p,S.get(con,'assets',f'f{i}')[0]['byte_sha256'])).convert('RGBA') for i in range(8)]
    finally:con.close()
    c['constraints']=[{'id':'native','check':'native_registration','required':True},{'id':'guard','check':'repair_protection','required':True}]
    contract=D.ClipContractRevision.model_validate(c)
    baseline=[canonical_pixels(f) for f in frames];frames[0].putpixel((0,0),(255,0,0,255))
    records=[]
    for protected in [bytes(4096),bytes([1])+bytes(4095)]:
        records.append(E.evaluate_frames(contract,frames,{},context={'repair':{'baseline':baseline,
            'allowed_mask':bytes([1]*4096),'protected_mask':protected,'repaired_slots':[0]}}))
    assert [next(r.outcome.value for r in e.results if r.constraint_id=='guard') for e in records]==['pass','fail']
    assert records[0].evidence_manifest_sha256!=records[1].evidence_manifest_sha256

def test_applicable_membership_checked_but_unused_proposals_do_not_churn(tmp_path):
    p=str(tmp_path);seed3(p);env=clips.evaluate(p,'clip-R3');con=S.connect(p)
    try:
        ev=D.Evaluation.model_validate(S.get(con,'evaluations',env.artifacts[0]['id'])[0])
        asset=S.get(con,'assets','f0')[0]
    finally:con.close()
    proposal={'id':'proposal','source_asset_id':'f0','source_pixel_sha256':asset['pixel_sha256'],
              'view':'side','frame_instance_id':'clip-R3-fi-00','points':[[0,0]]}
    ANN.propose(p,MODEL,proposal)
    assert verify_evidence(p,'clip-R3',ev)[0]
    assert clips.evaluate(p,'clip-R3').artifacts[0]['id']==ev.id
    proposal={**proposal,'id':'reviewed','annotator_type':'human_reviewed'}
    with pytest.raises(AuthorizationError) as rejected:ANN.propose(p,MODEL,proposal)
    assert 'reviewer' in str(rejected.value)
    ANN.propose(p,HUMAN,proposal)
    assert not verify_evidence(p,'clip-R3',ev)[0]
    assert clips.evaluate(p,'clip-R3').artifacts[0]['id']!=ev.id

def test_scope_change_after_precheck_refuses_packet_publication(tmp_path):
    p=str(tmp_path);seed5(p)
    _,task=C.open_issue(p,HUMAN,{'action':'mark_issue','clip_revision_id':'rev-bad','frame_range':[12,15],
        'roi':{'left':30,'top':30,'right':31,'bottom':31},'note':'test fault'})
    for name,value in [('full',255),('empty',0)]:
        path=tmp_path/(name+'.png');Image.new('L',(64,64),value).save(path)
        AS.import_asset(p,str(path),name,rights='original')
    M.approve_mask(p,HUMAN,task.source_issue_event_id,'full',[3])
    claimed=C.claim(p,MODEL,task.id,C.get_task(p,task.id)['version'])
    original=C._revalidate_before_publish
    def barrier(*args,**kwargs):
        original(*args,**kwargs)
        if kwargs.get('connection') is None:
            M.approve_mask(p,HUMAN,task.source_issue_event_id,'empty',[3])
    with patch.object(C,'_revalidate_before_publish',side_effect=barrier):
        with pytest.raises(S.StaleRevisionError):
            C.submit_correction(p,MODEL,task.id,claim_token=claimed['claim_token'],expected_version=claimed['version'],
                new_revision_id='race-child',slot_asset_ids={3:'f3'},recipe='repair:bounded-patch',
                baseline_evaluation_id=task.baseline_evaluation_id,idempotency_key='race')
    con=S.connect(p)
    try:
        assert con.execute("SELECT id FROM review_packets WHERE id='pkt-race-child'").fetchone() is None
        assert not S.get(con,'correction_tasks',task.id)[0]['attempt_ids']
    finally:con.close()

def test_non_png_and_oriented_png_are_explicitly_rejected(tmp_path):
    for name,fmt in [('photo.jpg','JPEG'),('oriented.png','PNG')]:
        path=tmp_path/name;im=Image.new('RGB',(32,64));exif=im.getexif();exif[274]=6;im.save(path,format=fmt,exif=exif)
        with pytest.raises(InvalidInput) as err:AS.import_asset(str(tmp_path/'project'),str(path),name)
        assert 'format' in str(err.value) or 'oriented' in str(err.value)
