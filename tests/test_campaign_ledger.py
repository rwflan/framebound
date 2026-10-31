from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from framebound.v3.campaign.contracts import Prices, curriculum
from framebound.v3.campaign.dispatch import Response, dispatch
from framebound.v3.campaign.ledger import Ledger, Stopped


def funded(tmp_path):
    ledger = Ledger(tmp_path)
    config = curriculum().model_copy(update={'prices':Prices(verified_at='test-only',source='synthetic engineering price')})
    ledger.plan(config)
    ledger.fund(config.id,'api',50000,evidence='synthetic access evidence')
    case = next(c for c in config.cases if c.stage == 'pilot')
    return ledger, config.id, case.id


def request(ledger,campaign,case,**kw):
    return ledger.reserve(campaign,case,'generate',{'model':'engineering-only'},quote=10000,images=1,**kw)


def test_two_claimants_crash_and_renamed_request_never_double_send(tmp_path):
    l,c,k = funded(tmp_path)
    row = request(l,c,k)
    def claim(_):
        try: return l.claim(row['id'])
        except Stopped: return None
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(claim,range(2)))
    assert sum(x is not None for x in claims) == 1
    l.start_wire(row['id'],next(x for x in claims if x))
    restarted = Ledger(tmp_path)
    restarted.resume(c)
    with pytest.raises(Stopped): restarted.claim(row['id'])
    with pytest.raises(Stopped): restarted.reserve(c,k,'generate',{'model':'renamed'},quote=10000,images=1)
    with pytest.raises(Stopped): request(restarted,c,k,attempt=1)
    assert restarted.status(c)['budgets']['api']['reserved'] == 10000
    receipt = restarted.receive(row['id'],b'engineering-result',incurred=10000,successful_images=1,provider_receipt={'id':'TEST-ONLY'})
    assert restarted.receive(row['id'],b'engineering-result',incurred=10000,successful_images=1,provider_receipt={'id':'TEST-ONLY'}) == receipt
    assert restarted.status(c)['budgets']['api'] == dict(incurred=10000,reserved=0)


def test_zero_budget_cancel_and_overrun(tmp_path):
    l,c,k = funded(tmp_path)
    l.fund(c,'api',0,evidence='test')
    with pytest.raises(Stopped,match='unfunded'): request(l,c,k)
    l.fund(c,'api',10000,evidence='test')
    r = request(l,c,k)
    l.cancel_reserved(r['id'],'explicit cancellation')
    assert l.status(c)['budgets']['api'] == dict(incurred=0,reserved=0)
    r = request(l,c,k,attempt=1)
    l.start_wire(r['id'],l.claim(r['id']))
    l.receive(r['id'],b'bytes',incurred=20000,successful_images=1,provider_receipt={'id':'test'})
    assert l.status(c)['stopped']
    assert l.status(c)['budgets']['api']['incurred'] == 20000


def test_timeout_retains_unknown_and_quote(tmp_path):
    l,c,k = funded(tmp_path)
    class Timeout:
        def execute(self,request,*,timeout): raise TimeoutError()
    r = request(l,c,k)
    with pytest.raises(TimeoutError): dispatch(l,r['id'],Timeout())
    assert l.status(c)['requests'][0]['state'] == 'unknown_provider_outcome'
    assert l.status(c)['budgets']['api']['reserved'] == 10000
    with pytest.raises(Stopped): l.finish_case(c,k,'exhausted',{'reason':'timeout'})


def test_concurrent_reservations_do_not_overcommit(tmp_path):
    l,c,k = funded(tmp_path)
    l.fund(c,'api',10000,evidence='test')
    cases = [x.id for x in l.config(c).cases if x.stage == 'pilot'][:2]
    def reserve(case):
        try: return request(l,c,case)
        except Stopped: return None
    with ThreadPoolExecutor(2) as pool:
        rows = list(pool.map(reserve,cases))
    assert sum(x is not None for x in rows) == 1
