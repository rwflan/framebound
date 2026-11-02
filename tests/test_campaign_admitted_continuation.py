"""Released pilot collection never implies resolving an unknown or release."""
from datetime import datetime,timezone
import json
import pytest
from framebound.v3.campaign import drain
from framebound.v3.campaign.assessment import Binding,Provenance,abstention
from framebound.v3.campaign.contracts import canonical,digest
from framebound.v3.campaign.curriculum import upskill_curriculum,protocol
from framebound.v3.campaign.ledger import Ledger
from framebound.v3.campaign.runner import Runner


def prepared(root):
    ledger=Ledger(root);config=upskill_curriculum('synthetic-admitted')
    ledger.plan(config);ledger.fund(config.id,'api',6000000,evidence=dict(verified_at=datetime.now(timezone.utc).isoformat(),source='synthetic',account_access='synthetic',image_microdollars=10000))
    pilot=protocol(config)['pilot'];prior=pilot[:20]
    with ledger.db() as db:db.execute('INSERT INTO knowledge_releases VALUES(?,?,?,?,?)',(config.id,'pilot',canonical(pilot).decode(),'{}','{}'))
    row=ledger.reserve(config.id,prior[0],'diagnose',{'synthetic':True},quote=1000)
    ledger.start_wire(row['id'],ledger.claim(row['id']));ledger.unknown(row['id'],'synthetic reset')
    ledger.isolate_unknown(config.id,row['id'],dict(source='synthetic',reason='no retry'))
    for cid in prior[1:]:finish(ledger,config,cid)
    ledger.stop(config.id)
    parent=root/'campaigns'/config.id/'drains'/'parent';parent.mkdir(parents=True)
    (parent/'request.json').write_bytes(canonical(dict(case_ids=prior,config_sha256=digest(config))))
    (parent/'result.json').write_bytes(canonical(dict(stage_release_permitted=False)))
    return ledger,config,pilot,prior,parent


def finish(ledger,config,cid,*,scoped=True):
    ledger.resume(config.id)
    case=next(c for c in config.cases if c.id==cid)
    row=ledger.reserve(config.id,cid,'diagnose',{'synthetic':True},quote=1000)
    ledger.start_wire(row['id'],ledger.claim(row['id']));ledger.receive(row['id'],b'synthetic receipt',incurred=1000,provider_receipt={'id':'TEST-ONLY'})
    assessment=abstention(Binding(**{k:'a'*64 for k in Binding.model_fields}),Provenance(provider='engineering',requested_model='test',rubric_sha256='b'*64,raw_sha256='c'*64,execution_id='fixture'),list(range(len(case.holds))),'Synthetic coverage fixture').model_dump(mode='json')
    if scoped:assessment['coverage'][0].update(status='absent_within_assessed_scope',slots=list(range(len(case.holds))))
    ledger.finish_case(config.id,cid,'ambiguous',dict(outcome='ambiguous',assessment=assessment,intake=[]))


def test_next_already_released_cases_freeze_and_never_release_expansion(tmp_path,monkeypatch):
    ledger,config,pilot,prior,parent=prepared(tmp_path);calls=[]
    def run(self,**kwargs):
        calls.append(kwargs)
        for cid in kwargs['case_ids']:finish(ledger,config,cid)
        ledger.stop(config.id)
        return dict(results={},deferred={},status=ledger.status(config.id))
    monkeypatch.setattr(Runner,'run',run)
    original=(parent/'result.json').read_bytes()
    result=drain.continue_admitted(tmp_path,config.id,parent_version='parent',version='next',specialist=object())
    assert len(result['case_ids'])==20 and not set(result['case_ids']).intersection(prior)
    assert set(result['case_ids'])<=set(pilot)
    assert result['stage_release_permitted'] is False
    assert result['cohort_evidence']['scoped_assessed']==20
    assert result['cohort_evidence']['passed'] is False # global unknown unchanged
    assert (parent/'result.json').read_bytes()==original
    assert drain.continue_admitted(tmp_path,config.id,parent_version='parent',version='next',specialist=object())==result
    assert len(calls)==1
    with ledger.db() as db:assert db.execute('SELECT COUNT(*) FROM knowledge_releases').fetchone()[0]==1


def test_unfinished_unaffected_parent_cannot_select_more(tmp_path):
    ledger,config,pilot,prior,parent=prepared(tmp_path)
    with ledger.db() as db:db.execute('UPDATE cases SET result=NULL WHERE campaign=? AND id=?',(config.id,prior[-1]))
    with pytest.raises(ValueError,match='quality|unaffected'):
        drain.continue_admitted(tmp_path,config.id,parent_version='parent',version='forbidden',specialist=object())


def test_actual_scope_failure_cannot_unlock_next_batch(tmp_path):
    ledger,config,pilot,prior,parent=prepared(tmp_path)
    with ledger.db() as db:
        for cid in prior[1:8]:
            r=json.loads(db.execute('SELECT result FROM cases WHERE campaign=? AND id=?',(config.id,cid)).fetchone()[0])
            for c in r['assessment']['coverage']:c.update(status='not_assessed',slots=[])
            db.execute('UPDATE cases SET result=? WHERE campaign=? AND id=?',(canonical(r).decode(),config.id,cid))
    with pytest.raises(ValueError,match='quality'):
        drain.continue_admitted(tmp_path,config.id,parent_version='parent',version='forbidden',specialist=object())


@pytest.mark.parametrize('mode',['unreleased','final'])
def test_no_new_stage_admission(tmp_path,mode):
    ledger,config,pilot,prior,parent=prepared(tmp_path)
    with ledger.db() as db:
        if mode=='unreleased':db.execute('DELETE FROM knowledge_releases')
        else:db.execute('INSERT INTO knowledge_releases VALUES(?,?,?,?,?)',(config.id,'final','[]','{}','{}'))
    with pytest.raises(ValueError,match='existing released'):
        drain.continue_admitted(tmp_path,config.id,parent_version='parent',version='forbidden',specialist=object())
