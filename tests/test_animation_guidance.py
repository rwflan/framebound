from framebound.v3.guidance import compile_guidance, PRINCIPLES
from framebound.v3.campaign.contracts import digest


def spec(count=6):
    return dict(subjects='one red fox', intent='jump and land', appearance='flat ink',
                canvas=dict(width=256, height=256),
                timing=dict(holds=[2]*count, ticks_per_second=12), loop=True)


def test_guidance_is_bound_broad_and_has_no_training_or_paid_dependency():
    result=compile_guidance(spec())
    assert len(result['rules'])==9
    assert {r['category'] for r in result['rules']}=={p[0] for p in PRINCIPLES}
    assert result['training_required'] is False
    assert result['model_improvement_established'] is False
    assert result['authority']=='advisory_only'
    assert result['sha256']==digest({k:v for k,v in result.items() if k!='sha256'})
    assert result==compile_guidance(spec())
    changed=spec(); changed['intent']='sleep'
    assert result['sha256']!=compile_guidance(changed)['sha256']


def test_anchor_does_not_inherit_action_or_sheet_request():
    result=compile_guidance(spec())
    assert 'jump and land' in result['prompt']
    assert 'jump and land' not in result['identity_anchor_prompt']
    assert 'one neutral' in result['identity_anchor_prompt']
    for count in (6,12,24):
        guide=compile_guidance(spec(count))
        layout=guide['sheet_layout']
        assert layout['columns']*layout['rows']==count
        assert f"{layout['columns']} columns" in guide['prompt']
