import pytest
from framebound.v3.cohort_selection import select_profiles


def test_choose_a_complete_consistent_cohort_instead_of_independent_favourites():
    candidates={'contact':[{'id':'wide','profile':[1.4,1.6]},{'id':'consistent','profile':[1.05,1.43]}],'pass':[{'id':'narrow','profile':[1.0,1.4]}],'compress':[{'id':'match','profile':[1.09,1.48]}]}
    result=select_profiles(candidates)
    assert result['frames']['contact']['id']=='consistent'
    assert result['worst_ratio']<=1.12 and not result['accepted']
    assert select_profiles({'a':[dict(profile=[1,1])],'b':[dict(profile=[1.2,1.2])]}) is None


def test_unknown_profiles_and_work_budget_never_become_passes():
    assert select_profiles({'a':[dict(profile=[1,float('nan')])],'b':[dict(profile=[1,1])]}) is None
    assert select_profiles({'a':[]}) is None
    with pytest.raises(ValueError,match='budget'):select_profiles({'a':[dict(profile=[1,1])]*2,'b':[dict(profile=[1,1])]*2},combination_limit=3)
