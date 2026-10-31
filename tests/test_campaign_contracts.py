from collections import Counter
from pathlib import Path

import pytest

from framebound.v3.campaign.contracts import Campaign, curriculum, freeze, local_path


def test_curriculum_freezes_all_splits_but_releases_only_80(tmp_path):
    c = curriculum()
    assert len(c.cases) == 800
    assert Counter(x.split for x in c.cases) == dict(train=480, validation=160, test=160)
    assert len({x.family for x in c.cases}) == 200
    assert Counter(x.action for x in c.cases if x.stage == 'pilot') == dict.fromkeys(['locomotion', 'acting', 'interaction', 'effects'], 20)
    assert sum(x.stage == 'pilot' for x in c.cases) == 80
    assert freeze(tmp_path, c) == freeze(tmp_path, c)
    with pytest.raises(ValueError, match='immutable'):
        freeze(tmp_path, c.model_copy(update={'seed': 1}))


def test_ancestry_and_local_root_cannot_escape(tmp_path):
    c = curriculum().model_dump()
    c['cases'][0]['ancestry'] = [c['cases'][-1]['family']]
    with pytest.raises(ValueError, match='crosses splits'):
        Campaign.model_validate(c)
    with pytest.raises(ValueError, match='escapes'):
        local_path(tmp_path, '../escape')
    (tmp_path / 'link').symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match='escapes'):
        local_path(tmp_path, 'link/escape')
    with pytest.raises(ValueError, match='outside'):
        local_path(Path.cwd(), 'campaigns')
