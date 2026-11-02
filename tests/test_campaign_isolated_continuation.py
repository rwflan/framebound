import json
from datetime import datetime,timedelta,timezone
import pytest
from framebound.v3.campaign.contracts import canonical,digest
from framebound.v3.campaign.ledger import Stopped
from framebound.v3.campaign import drain
from framebound.v3.campaign.runner import Runner
from test_campaign_ledger import funded


def fixture(tmp_path):
    ledger,campaign,_=funded(tmp_path)
    ledger.fund(campaign,'api',200000,evidence='synthetic engineering evidence')
    cases=[];families=set()
    for case in ledger.config(campaign).cases:
        if case.stage=='pilot' and case.family not in families:
            cases.append(case.id);families.add(case.family)
        if len(cases)==4:break
    unknown=[]
    for cid in cases[:2]:
        row=ledger.reserve(campaign,cid,'diagnose',{'synthetic':True},quote=1000,images=0)
        ledger.start_wire(row['id'],ledger.claim(row['id']));ledger.unknown(row['id'],'synthetic reset')
        ledger.isolate_unknown(campaign,row['id'],dict(source='synthetic fixture',reason='unacknowledged; no retry'))
        unknown.append(row['id'])
    ledger.stop(campaign)
    parent=tmp_path/'campaigns'/campaign/'upskill'/'interrupted';parent.mkdir(parents=True)
    config=ledger.config(campaign)
    (parent/'request.json').write_bytes(canonical(dict(config_sha256=digest(config),case_ids=cases)))
    (parent/'result.json').write_bytes(canonical(dict(status='blocked',case_ids=cases,deferred={cases[0]:'URLError'},batch_evidence={'acquisition_failed':0})))
    return ledger,campaign,cases,unknown,parent


def capacity(ledger,campaign):
    return ledger.authorize_recovery_capacity(campaign,expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
        evidence=dict(source='synthetic provider capacity',account_access='synthetic account',reason='retain two unknown slots plus one bounded live slot'))


def test_capacity_keeps_unknown_slots_and_denies_a_fourth(tmp_path):
    ledger,campaign,cases,unknown,_=fixture(tmp_path);ledger.resume(campaign)
    row=ledger.reserve(campaign,cases[2],'diagnose',{'synthetic':True},quote=1000,images=0)
    permit=ledger.claim(row['id'])
    with pytest.raises(Stopped,match='concurrency'):ledger.start_wire(row['id'],permit)
    assert capacity(ledger,campaign)['unknowns_still_count']
    ledger.start_wire(row['id'],permit)
    fourth=ledger.reserve(campaign,cases[3],'diagnose',{'synthetic':True},quote=1000,images=0)
    with pytest.raises(Stopped,match='concurrency'):ledger.start_wire(fourth['id'],ledger.claim(fourth['id']))
    assert all(r['state']=='unknown_provider_outcome' for r in ledger.status(campaign)['requests'] if r['id'] in unknown)


def test_original_cohort_drains_unaffected_cases_without_gate_or_retry(tmp_path,monkeypatch):
    ledger,campaign,cases,unknown,parent=fixture(tmp_path);capacity(ledger,campaign)
    original=[(parent/n).read_bytes() for n in ('request.json','result.json')];sent=[]
    def case(self,spec):
        sent.append(spec.id)
        row=self.ledger.reserve(campaign,spec.id,'diagnose',{'synthetic':True},quote=1000,images=0)
        self.ledger.start_wire(row['id'],self.ledger.claim(row['id']))
        self.ledger.receive(row['id'],b'synthetic',incurred=1000,provider_receipt={'id':'TEST-ONLY'},successful_images=0)
        result={'outcome':'ambiguous','intake':[]}
        self.ledger.finish_case(campaign,spec.id,'ambiguous',result)
        return result
    monkeypatch.setattr(Runner,'case',case)
    result=drain.run(tmp_path,campaign,parent_batch='interrupted',version='drain1',specialist=object())
    assert sent==cases[2:]
    assert result['stage_release_permitted'] is False
    assert result['original_cohort_evidence']['passed'] is False
    assert ledger.is_stopped(campaign)
    assert [(parent/n).read_bytes() for n in ('request.json','result.json')]==original
    assert drain.run(tmp_path,campaign,parent_batch='interrupted',version='drain1',specialist=object())==result
    assert sent==cases[2:]
    assert ledger.status(campaign)['budgets']['api']['reserved']==2000
    with pytest.raises(Stopped):ledger.reserve(campaign,cases[0],'diagnose',{'changed':True},quote=1000,images=0,attempt=1)


def test_unisolated_unknown_and_invalid_capacity_never_resume(tmp_path):
    ledger,campaign,cases,unknown,_=fixture(tmp_path)
    with ledger.db() as db:db.execute('DELETE FROM unknown_isolations WHERE request_id=?',(unknown[0],))
    with pytest.raises(ValueError,match='permanently isolated'):
        Runner(tmp_path,campaign,object()).run(case_ids=cases,isolated_continuation=True)
    assert ledger.is_stopped(campaign)
    with pytest.raises(ValueError,match='expiry'):
        ledger.authorize_recovery_capacity(campaign,expires_at=datetime.now(timezone.utc).isoformat(),evidence={})


def test_failed_source_cohort_cannot_be_replenished(tmp_path):
    ledger,campaign,cases,unknown,parent=fixture(tmp_path)
    path=parent/'result.json';report=json.loads(path.read_text())
    report['batch_evidence']['acquisition_failed']=2
    path.write_bytes(canonical(report))
    with pytest.raises(ValueError,match='scientifically unfailed'):
        drain.run(tmp_path,campaign,parent_batch='interrupted',version='forbidden',specialist=object())
    assert ledger.is_stopped(campaign)


def test_new_failure_stops_again_and_cannot_claim_resolution(tmp_path,monkeypatch):
    ledger,campaign,cases,unknown,parent=fixture(tmp_path);capacity(ledger,campaign)
    def fail(self,case):raise ConnectionResetError('synthetic new failure')
    monkeypatch.setattr(Runner,'case',fail)
    result=drain.run(tmp_path,campaign,parent_batch='interrupted',version='interrupted-again',specialist=object())
    assert ledger.is_stopped(campaign)
    assert not result['original_cohort_evidence']['passed']
    assert result['stage_release_permitted'] is False
