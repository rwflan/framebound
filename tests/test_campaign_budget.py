"""Operator budget amendments preserve frozen experiments and aggregate spend."""
from datetime import datetime, timezone

import pytest

from framebound.v3.campaign.contracts import canonical
from framebound.v3.campaign.curriculum import mvp_curriculum
from framebound.v3.campaign.ledger import Ledger, Stopped
from framebound.v3.campaign.progression import admitted
from framebound.v3.campaign.service import operate


def evidence():
    return dict(source='Explicit engineering operator authorization', reason='Bounded experiment budget',
                authorized_at=datetime.now(timezone.utc).isoformat())


def funding():
    return dict(verified_at=datetime.now(timezone.utc).isoformat(), source='Engineering rate fixture',
                account_access='Synthetic account evidence', image_microdollars=10000)


def reserve(ledger, config, quote, index=0):
    case_id=sorted(admitted(ledger,config))[index]
    return ledger.reserve(config.id,case_id,'diagnose',{'engineering_quote':quote},quote=quote)


def test_amendment_preserves_config_and_requires_separate_funding(tmp_path):
    config=mvp_curriculum('budget-one'); ledger=Ledger(tmp_path); ledger.plan(config)
    before=canonical(ledger.config(config.id))
    result=operate(tmp_path,'api-budget',campaign=config.id,request=dict(microdollars=50000000,evidence=evidence()))
    assert result['campaign_ceiling']==result['lifetime_ceiling']==50000000
    assert canonical(ledger.config(config.id))==before
    with pytest.raises(Stopped,match='unfunded'):reserve(ledger,config,10000)
    ledger.fund(config.id,'api',50000000,evidence=funding())
    with pytest.raises(ValueError,match='allocation exceeds'):ledger.fund(config.id,'api',50000001,evidence=funding())
    assert reserve(ledger,config,49000000)['state']=='reserved'
    assert ledger.status(config.id)['api_budget']['lifetime_remaining']==1000000


def test_global_cap_counts_other_campaigns_and_survives_reopening(tmp_path):
    one=mvp_curriculum('budget-one'); two=mvp_curriculum('budget-two')
    ledger=Ledger(tmp_path);ledger.plan(one);ledger.plan(two)
    ledger.authorize_api_budget(one.id,50000000,evidence=evidence())
    ledger.fund(one.id,'api',50000000,evidence=funding())
    reserve(ledger,one,49000000)
    ledger=Ledger(tmp_path)
    ledger.fund(two.id,'api',15000000,evidence=funding())
    with pytest.raises(Stopped,match='lifetime spending ceiling'):reserve(ledger,two,2000000)
    assert reserve(ledger,two,1000000)['state']=='reserved'
    assert ledger.status(one.id)['api_budget']['lifetime_remaining']==0
    with pytest.raises(ValueError,match='cannot erase'):ledger.authorize_api_budget(one.id,49999999,evidence=evidence())
    with pytest.raises(Stopped,match='lifetime spending ceiling'):reserve(ledger,two,1,index=1)


def test_lowered_authorization_blocks_previous_larger_allocation(tmp_path):
    config=mvp_curriculum();ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.authorize_api_budget(config.id,50000000,evidence=evidence())
    ledger.fund(config.id,'api',50000000,evidence=funding())
    ledger.authorize_api_budget(config.id,1000000,evidence=evidence())
    with pytest.raises(Stopped,match='authorized API campaign ceiling'):reserve(ledger,config,1000001)
    assert ledger.status(config.id)['api_budget']['lifetime_ceiling']==1000000
    with ledger.db() as db:
        assert db.execute('SELECT count(*) FROM api_budget_authorizations').fetchone()[0]==2


def test_received_cost_and_unknown_reservations_remain_booked(tmp_path):
    config=mvp_curriculum();ledger=Ledger(tmp_path);ledger.plan(config)
    ledger.authorize_api_budget(config.id,50000000,evidence=evidence())
    ledger.fund(config.id,'api',50000000,evidence=funding())
    received=reserve(ledger,config,1000000)
    permit=ledger.claim(received['id']);ledger.start_wire(received['id'],permit)
    ledger.receive(received['id'],b'engineering response',incurred=500000,provider_receipt={'fixture':True})
    unknown=reserve(ledger,config,2000000,index=1)
    permit=ledger.claim(unknown['id']);ledger.start_wire(unknown['id'],permit)
    ledger.unknown(unknown['id'],'Synthetic lost response')
    ledger.authorize_api_budget(config.id,50000000,evidence=evidence())
    assert ledger.status(config.id)['api_budget']['lifetime_committed']==2500000
    assert ledger.request(unknown['id'])['state']=='unknown_provider_outcome'
    with pytest.raises(ValueError,match='cannot erase'):
        ledger.authorize_api_budget(config.id,2499999,evidence=evidence())


@pytest.mark.parametrize('amount',[True,-1,125000001,50.0])
def test_invalid_authorizations_do_not_change_ceiling(tmp_path,amount):
    config=mvp_curriculum();ledger=Ledger(tmp_path);ledger.plan(config)
    with pytest.raises(ValueError):ledger.authorize_api_budget(config.id,amount,evidence=evidence())
    assert ledger.status(config.id)['api_budget']['campaign_ceiling']==15000000


def test_authorization_needs_actual_source_and_timezone(tmp_path):
    config=mvp_curriculum();ledger=Ledger(tmp_path);ledger.plan(config)
    for invalid in ({},dict(evidence(),source=' '),dict(evidence(),authorized_at='2026-01-01T00:00:00')):
        with pytest.raises(ValueError):ledger.authorize_api_budget(config.id,50000000,evidence=invalid)
