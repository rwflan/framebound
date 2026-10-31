import copy
import pytest

from framebound.v3.campaign.learning import fit,eligibility,predict,calibrate,fit_ranker
from framebound.v3.campaign.transfer import FeatureRow,FeatureShard


def data():
    rows=[]
    for n in range(24):
        value=float(n%2)
        rows.append(FeatureRow(case_id=f'{n:064x}',family_id=f'{n:064x}',split='train' if n<20 else 'validation',
            features=[[value]*8,[value+0.01]*8],targets=[n%2]+[0]*8,assessed=[True]+[False]*8))
    return FeatureShard(rows=rows)


def test_support_gate_is_not_bypassed_by_pilot_labels():
    gate=eligibility(data(),['identity'])
    assert not gate['eligible']
    assert fit(data(),categories=['identity'])['status']=='insufficient_support'
    assert fit_ranker([])['status']=='insufficient_support'


def test_masked_training_deterministic_and_validation_is_not_training():
    shard=data()
    one=fit(shard,categories=['identity'],engineering=True,steps=40)
    two=fit(shard,categories=['identity'],engineering=True,steps=40)
    assert one['checkpoint']['weights']==two['checkpoint']['weights']
    assert predict(one['checkpoint'],shard.rows[1])['scores']['identity']>predict(one['checkpoint'],shard.rows[0])['scores']['identity']
    assert predict(one['checkpoint'],shard.rows[0])['scores']['parts'] is None
    changed=shard.model_dump()
    for r in changed['rows']:
        if r['split']=='validation': r['targets'][0]=1-r['targets'][0]
    other=fit(FeatureShard.model_validate(changed),categories=['identity'],engineering=True,steps=40)
    assert other['checkpoint']['weights']==one['checkpoint']['weights']
    assert not calibrate(one['checkpoint'],shard)['promoted']


def test_temporal_head_retains_native_window_predictions():
    shard=data();result=fit(shard,categories=['identity'],engineering=True,model='temporal',steps=10)
    assert len(predict(result['checkpoint'],shard.rows[0])['windows'])==2
