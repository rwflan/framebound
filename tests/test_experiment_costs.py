import json
import shutil
import pytest
from framebound.v3.experiment_costs import summarize


def operation(root,name,cost=None,response_id=None,model='muse-image-1.0',quote=10000):
    path=root/'private'/name;path.mkdir(parents=True)
    (path/'request.json').write_text(json.dumps({'wire':{'model':model},'committed_microdollars':quote}))
    if cost is not None:
        (path/'response.json').write_text(json.dumps({'id':response_id,'status':'completed'}))
        (path/'receipt.json').write_text(json.dumps({'incurred_microdollars':cost,'receipt':{'response_id':response_id,'cost_basis':'provider usage and frozen rate'}}))
    return path


def test_counts_all_attempts_shared_initial_and_unknown_reserves(tmp_path):
    operation(tmp_path,'pose-initial',10000,'a');operation(tmp_path,'repair-rejected',10000,'b')
    operation(tmp_path,'assess',12000,'c',model='muse-spark-1.3',quote=100000);operation(tmp_path,'unknown',quote=100000)
    s=summarize([tmp_path])['summary']
    assert s['observed_microdollars']==32000 and s['unreconciled_reserve_microdollars']==100000
    assert s['total_with_reserve_microdollars']==132000
    assert s['groups']['shared_initial']['observed_microdollars']==10000
    assert s['groups']['framework_work']['observed_microdollars']==22000
    assert s['unreconciled_operations']==1


def test_copied_receipts_are_not_new_spend_but_distinct_responses_are(tmp_path):
    first=tmp_path/'one';second=tmp_path/'two'
    source=operation(first,'repair',10000,'a');shutil.copytree(source,second/'private'/'copied')
    operation(second,'another-paid-attempt',10000,'b')
    assert summarize([first,second,first])['summary']['observed_microdollars']==20000
    receipt=second/'private/copied/receipt.json';d=json.loads(receipt.read_text());d['incurred_microdollars']=20000;receipt.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='Conflicting'):summarize([first,second])


def test_missing_receipt_or_estimated_cost_never_becomes_confirmed_zero(tmp_path):
    p=operation(tmp_path,'uncertain-sam',100000,'a',model='sam-3.1',quote=100000)
    d=json.loads((p/'receipt.json').read_text());d['receipt']['cost_basis']='unreconciled conservative upper bound';(p/'receipt.json').write_text(json.dumps(d))
    s=summarize([tmp_path,tmp_path/'missing'])['summary']
    assert s['observed_microdollars']==0 and s['unreconciled_reserve_microdollars']==100000
    assert s['missing_lineage_roots']==1


def test_cached_receipts_refresh_and_missing_lineage_cannot_reset_recorded_spend(tmp_path):
    from scripts.update_demo_costs import update
    root=tmp_path/'experiment';public=tmp_path/'public';root.mkdir();public.mkdir()
    p=operation(root,'repair',10000,'a');cache={}
    (root/'config.json').write_text(json.dumps({'cost_lineage_roots':[str(root)],'publish_root':str(public)}))
    (public/'manifest.json').write_text('TEST-ONLY immutable live revision')
    (public/'framework.png').write_bytes(b'TEST-ONLY native artwork bytes')
    before=update(root,cache=cache)
    assert (public/'manifest.json').read_text()=='TEST-ONLY immutable live revision'
    assert (public/'framework.png').read_bytes()==b'TEST-ONLY native artwork bytes'
    assert summarize([root],cache=cache)['summary']==before
    operation(root,'second',10000,'b')
    assert update(root,cache=cache)['observed_microdollars']==20000
    shutil.rmtree(p)
    with pytest.raises(ValueError,match='regressed'):update(root,cache=cache)
    assert json.loads((public/'costs.json').read_text())['observed_microdollars']==20000
    assert str(root) not in json.dumps(before) and 'response_id' not in json.dumps(before)


def test_parallel_lineage_updates_publish_one_consistent_total(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from scripts.update_demo_costs import update
    roots=[tmp_path/'one',tmp_path/'two'];public=tmp_path/'public';public.mkdir()
    for index,root in enumerate(roots):
        operation(root,'work',10000,str(index))
        (root/'config.json').write_text(json.dumps({'cost_lineage_roots':[str(r) for r in roots],'publish_root':str(public)}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(update,roots))
    assert all(r['observed_microdollars']==20000 for r in results)
    assert json.loads((public/'costs.json').read_text())['observed_microdollars']==20000
