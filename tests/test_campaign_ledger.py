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


def test_control_plane_uses_indexes_without_scanning_inline_wire_blobs(tmp_path):
    ledger=Ledger(tmp_path)
    with ledger.db() as db:
        lookup=db.execute("EXPLAIN QUERY PLAN SELECT * FROM requests WHERE campaign=? AND case_id=? AND operation=? AND json_extract(request,'$.attempt')=0 AND json_extract(request,'$.sheet')=0",('campaign','case','generate')).fetchall()
        totals=db.execute("EXPLAIN QUERY PLAN SELECT SUM(COALESCE(incurred,reserved)) FROM requests WHERE subsystem='api'").fetchall()
        resources=db.execute("EXPLAIN QUERY PLAN SELECT SUM(CASE WHEN receipt IS NOT NULL THEN json_extract(receipt,'$.successful_images') ELSE images END) FROM requests WHERE state!='cancelled'").fetchall()
        assert any('SEARCH' in r[3] and 'requests_campaign_attempt' in r[3] for r in lookup)
        assert all('COVERING INDEX' in r[3] for r in totals)
        assert all('COVERING INDEX' in r[3] for r in resources)
    # Schema installation is repeatable and does not rewrite any outbox row.
    Ledger(tmp_path)


def test_exact_disk_scan_excludes_symlinks_and_keeps_quota(tmp_path):
    from types import SimpleNamespace
    from framebound.v3.campaign.ledger import Ledger,Stopped
    root=tmp_path/'data';root.mkdir();(root/'a').write_bytes(b'a');(root/'nested').mkdir();(root/'nested'/'b').write_bytes(b'bb')
    external=tmp_path/'external';external.write_bytes(b'x'*1000);(root/'link').symlink_to(external);(root/'directory-link').symlink_to(root/'nested',target_is_directory=True)
    ledger=Ledger.__new__(Ledger);ledger.root=root
    ledger._disk(SimpleNamespace(limits=SimpleNamespace(disk_bytes=4)))
    with pytest.raises(Stopped,match='disk quota'):ledger._disk(SimpleNamespace(limits=SimpleNamespace(disk_bytes=3)))


def test_local_denial_audit_releases_only_phantom_slot_not_unknown_or_money(tmp_path):
    import json
    from framebound.v3.campaign.contracts import curriculum,Prices
    from framebound.v3.campaign.ledger import Ledger,Stopped
    ledger=Ledger(tmp_path);requests=[]
    for i in range(3):
        config=curriculum('local-proof-'+str(i));case=config.cases[0].model_copy(update={'family':'proof-family-'+str(i)})
        config=config.model_copy(update={'cases':[case],'prices':Prices(verified_at='engineering',source='fixture')})
        ledger.plan(config);ledger.fund(config.id,'api',1000,evidence='engineering')
        row=ledger.reserve(config.id,case.id,'diagnose',{},quote=100);requests.append((config,case,row))
        if i<2:
            token=ledger.claim(row['id']);ledger.start_wire(row['id'],token);ledger.unknown(row['id'],'unacknowledged')
    config,case,row=requests[0]
    ledger.isolate_unknown(config.id,row['id'],dict(source='engineering',reason='no retry'))
    (tmp_path/'report.json').write_text(json.dumps(dict(campaign=config.id,case_ids=[case.id],deferred={case.id:'Supervisor admission window ended before paid send'})))
    (tmp_path/'adapter.py').write_text("class WindowedMuse(MuseResponses):\n def preflight(self,request):\n  super().preflight(request)\n  raise Stopped('Supervisor admission window ended before paid send')\n")
    c3,_,q3=requests[2];token=ledger.claim(q3['id'])
    with pytest.raises(Stopped,match='concurrency'):ledger.start_wire(q3['id'],token)
    before=ledger.status(config.id)['api_budget']['lifetime_committed']
    ledger.record_local_admission_denial(config.id,row['id'],batch_report='report.json',adapter_source='adapter.py')
    assert ledger.request(row['id'])['state']=='unknown_provider_outcome'
    assert ledger.request(row['id'])['reserved']==100
    assert ledger.status(config.id)['api_budget']['lifetime_committed']==before
    ledger.start_wire(q3['id'],token)
    assert ledger.request(q3['id'])['state']=='wire_started'
    with pytest.raises(Stopped):ledger.claim(row['id'])
