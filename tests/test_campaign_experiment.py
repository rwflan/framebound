import pytest

from framebound.v3.campaign.contracts import curriculum
from framebound.v3.campaign.experiment import controls,adaptive,paired_report,freeze_final


def test_controls_are_predeclared_and_test_never_sampled():
    c=curriculum();allocation=controls(c)
    assert len(allocation['cases'])==80 and len({r['family'] for r in allocation['cases']})==40
    eligible=[dict(id=s.id,uncertain=True) for s in c.cases if s.stage=='expansion']
    result=adaptive(c,eligible,size=10,evidence=dict(pilot_gate_passed=True,detector_evaluated=True))
    assert len(result['selected'])<=10
    assert all(0<r['selection_probability']<=1 for r in result['selected'])
    with pytest.raises(ValueError,match='cannot use test'):
        adaptive(c,[dict(id=next(s.id for s in c.cases if s.split=='test'))],size=1,evidence=dict(pilot_gate_passed=True,detector_evaluated=True))


def test_intent_to_treat_retains_failed_calls_and_clusters_families():
    rows=[]
    for n in range(4):
        for arm,outcome in [('guided_edit','provider_failure'),('blind_rerun','unchanged')]:
            rows.append(dict(case_id=str(n),family='same-family',arm=arm,outcome=outcome))
    report=paired_report(rows)
    assert report['allocated_cases']==4 and report['families']==1
    assert report['confidence_interval'] is None and not report['promoted']
    assert report['outcomes']['guided_edit:provider_failure']==4
    with pytest.raises(ValueError,match='both arm'): paired_report(rows[:-1])


def test_final_evaluation_requires_frozen_evidence():
    with pytest.raises(ValueError,match='promoted'):
        freeze_final(curriculum(),detector_sha256='a'*64,policy_sha256='b'*64,prompts_sha256='c'*64,preprocessing_sha256='d'*64,evidence={})
