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
