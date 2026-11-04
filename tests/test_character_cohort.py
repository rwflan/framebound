import json
import pytest
from PIL import Image
from test_character_consistency import observation,feature
from framebound.v3.character_cohort import assess,overlay
from framebound.v3.character_consistency import image_digest
from framebound.v3.character_observations import ObservationInvalid


def review_row(fid):
    return dict(frame_id=fid,features={'body.upper_arm_bulk':feature('mismatch')},items={'item':{'design':feature(),'topology':feature('mismatch')}})


def dispatch_response(value):
    return json.dumps({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(value)}]}]}).encode()


def test_source_bound_bulk_and_item_failures_survive_overlay(tmp_path):
    image=Image.new('RGBA',(1000,1000));reference=image.copy();calls=[]
    def dispatch(root,key,model,prompt,images):
        calls.append((prompt,len(images)))
        return dispatch_response(dict(frames=[review_row('0')],limitation='TEST-ONLY fixture, not a visual evaluation'))
    evidence=assess(tmp_path,reference,[('0',image),('1',image)],['body.upper_arm_bulk'],
        [dict(id='item',required_features=['design','topology'])],'TEST-ONLY',dispatch=dispatch,persist=lambda *a:None,focus_ids=['0'])
    obs=observation().model_dump(mode='json');obs['image_sha256']=image_digest(image)
    merged=overlay(obs,evidence,image_digest(reference))
    assert merged.features['body.upper_arm_bulk'].status=='mismatch'
    assert merged.items['item'].features['topology'].status=='mismatch'
    assert merged.measurement_sources['cohort_review']['raw_sha256']==evidence['raw_sha256']
    assert calls[0][1]==3  # Both neighbours remain visual context for a focused review.
    assert 'biceps' in calls[0][0] and 'thickness' in calls[0][0]
    with pytest.raises(ValueError,match='Stale'):overlay(obs,evidence,'f'*64)
    obs['image_sha256']='a'*64
    with pytest.raises(ValueError,match='Stale'):overlay(obs,evidence,image_digest(reference))


def test_missing_item_coverage_cannot_be_a_successful_review(tmp_path):
    row=review_row('0');row['items']['item'].pop('topology')
    with pytest.raises(ObservationInvalid,match='coverage'):
        assess(tmp_path,Image.new('RGBA',(10,10)),[('0',Image.new('RGBA',(10,10)))],['body.upper_arm_bulk'],
            [dict(id='item',required_features=['design','topology'])],'TEST-ONLY',dispatch=lambda *a:dispatch_response(dict(frames=[row],limitation='TEST-ONLY')),persist=lambda *a:None)


def test_unknown_cohort_send_is_not_retried_or_treated_as_bad_art(tmp_path):
    calls=[]
    def dispatch(*args):calls.append(1);raise TimeoutError('TEST-ONLY unknown acceptance')
    with pytest.raises(TimeoutError):assess(tmp_path,Image.new('RGBA',(10,10)),[('0',Image.new('RGBA',(10,10)))],[],[],'TEST-ONLY',dispatch=dispatch,persist=lambda *a:None)
    assert len(calls)==1


def test_positive_rejudge_cannot_clear_negative_finding_on_unchanged_pixels(tmp_path):
    image=Image.new('RGBA',(1000,1000));obs=observation().model_dump(mode='json');obs['image_sha256']=image_digest(image)
    obs['features']['body.upper_arm_bulk']=feature('mismatch');obs['items']['item']['features']['topology']=feature('mismatch')
    row=review_row('0');row['features']['body.upper_arm_bulk']=feature('match');row['items']['item']['topology']=feature('match')
    evidence=assess(tmp_path,image,[('0',image)],['body.upper_arm_bulk'],[dict(id='item',required_features=['design','topology'])],
        'TEST-ONLY',dispatch=lambda *a:dispatch_response(dict(frames=[row],limitation='TEST-ONLY')),persist=lambda *a:None)
    merged=overlay(obs,evidence,image_digest(image))
    assert merged.features['body.upper_arm_bulk'].status=='mismatch'
    assert merged.items['item'].features['topology'].status=='mismatch'


def test_sequence_format_recovery_splits_only_completed_invalid_reviews(tmp_path,monkeypatch):
    from test_character_publication import fixture
    import scripts.review_character_sequence as script
    root,public,manifest,state=fixture(tmp_path)
    config=json.loads((root/'config.json').read_text());config.update(items=[dict(id='item',required_features=['design','palette','scale','attachment'])],description='TEST-ONLY')
    (root/'config.json').write_text(json.dumps(config));calls=[]
    def assess(root,reference,frames,features,items,description,*,dispatch,persist,focus_ids):
        calls.append(list(focus_ids))
        if len(focus_ids)>1:raise ObservationInvalid('TEST-ONLY','a'*64,'Retained malformed JSON')
        return dict(version='TEST-ONLY',execution_id='TEST-ONLY',raw_sha256='a'*64,reference_sha256=image_digest(reference),
                    image_sha256s={fid:image_digest(im) for fid,im in frames},
                    review=dict(frames=[dict(frame_id=focus_ids[0],features={name:feature() for name in features},items={'item':{name:feature() for name in items[0]['required_features']}})],limitation='TEST-ONLY'))
    monkeypatch.setattr(script,'assess',assess)
    script.review(root,state,[0,1])
    assert calls==[['idle','run'],['idle'],['run']]
    calls.clear()
    def unknown(*args,**kwargs):calls.append(1);raise TimeoutError('TEST-ONLY unknown acceptance')
    monkeypatch.setattr(script,'assess',unknown)
    with pytest.raises(TimeoutError):script.review(root,state,[0,1])
    assert calls==[1]


def test_flat_named_checks_keep_exact_feature_identity_and_reject_duplicates():
    from framebound.v3.character_cohort import canonical_review
    checks=[dict(frame_id='0',item_id=None,feature='body.upper_arm_bulk',**feature('mismatch')),
            dict(frame_id='0',item_id='item',feature='topology',**feature('mismatch'))]
    result=canonical_review(dict(checks=checks,limitation='TEST-ONLY'))
    assert result.frames[0].features['body.upper_arm_bulk'].status=='mismatch'
    assert result.frames[0].items['item']['topology'].status=='mismatch'
    with pytest.raises(ValueError,match='Duplicate'):canonical_review(dict(checks=checks+checks[:1],limitation='TEST-ONLY'))
