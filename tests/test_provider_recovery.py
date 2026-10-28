"""Operator recovery preserves exact dispatch accounting; no test sends live traffic."""
import json
import pytest
from framebound.v2 import storage as S
from framebound.v2.services import jobs as J,orchestrator as O
from framebound.v2.services import provider_recovery as R,provider_grants as G
from framebound.v2.services.errors import InvalidInput,AuthorizationError
from test_v2_r3_providers import _seed
from test_dispatch_reservations import send,response
from test_provider_grants import grant,queued


def uncertain(p,brief,monkeypatch):
    try:G.get_grant(p,'grant')
    except KeyError:grant(p,monkeypatch)
    monkeypatch.setenv('MODEL_API_KEY','test-never-live');monkeypatch.setenv('FRAMEBOUND_OPERATOR_SECRET','operator-test')
    ids=queued(p,brief,'uncertain')
    def timeout(request):raise TimeoutError('test ambiguous after wire entry')
    result=send(p,ids,timeout)
    assert result['action']=='needs_attention'
    return ids,J.job_get(p,ids[1])


def receipt(job,outcome='response',**extra):
    return {'id':'test-receipt','expected_version':job['version'],'request_sha256':job['job']['frozen_request_sha256'],
        'outcome':outcome,'receipt_reference':'test-fixture-receipt-only','evidence_note':'Controlled test upstream receipt; no participant decision.',**extra}


def test_receipt_recovers_paid_pixels_once_without_another_dispatch(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief']
    ids,job=uncertain(p,brief,monkeypatch)
    request=receipt(job,provider_response=response(p))
    with pytest.raises(AuthorizationError):R.reconcile(p,ids[1],request,'model-token')
    result=R.reconcile(p,ids[1],request,'operator-test')
    assert result['status']=='succeeded'
    assert R.reconcile(p,ids[1],request,'operator-test')==result
    stored=J.job_get(p,ids[1])['job']
    assert stored['dispatch_count']==stored['attempt_count']==1
    assert stored['origin']=='simulated-transport' and not stored['reconciliation_required']
    assert stored['output_asset_ids']
    with pytest.raises(S.ConflictError):R.reconcile(p,ids[1],{**request,'evidence_note':'changed test receipt content'},'operator-test')
    con=S.connect(p)
    try:
        assert con.execute('SELECT count(*) FROM provider_reconciliations').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
    finally:con.close()


def test_confirmed_nonacceptance_refunds_money_but_not_wire_call_units(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief']
    grant(p,monkeypatch,limit_kind='usd',quote_microusd=1000,ceiling_microusd=2000,pricing_reference='operator test quote',max_dispatches=2)
    ids,job=uncertain(p,brief,monkeypatch)
    assert G.get_grant(p,'grant')['grant']['reserved_microusd']==1000
    result=R.reconcile(p,ids[1],receipt(job,'not_accepted'),'operator-test')
    assert result['status']=='queued'
    accounting=G.get_grant(p,'grant')['grant']
    assert accounting['reserved_microusd']==0 and accounting['dispatches_reserved']==1
    assert J.job_get(p,ids[1])['job']['dispatch_count']==1


def test_pre_wire_cancel_refunds_all_reserved_units_and_invalidates_permit(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-never-live')
    grant(p,monkeypatch,max_dispatches=1)
    rid,jid,claim=queued(p,brief,'prewire')
    run,rv,job,version,_,_,permit=O._authorize_send(p,rid,jid,None,'worker',claim['fencing_token'],False,simulation_mode=True)
    assert G.get_grant(p,'grant')['grant']['dispatches_reserved']==1
    J.job_cancel(p,jid,version)
    assert G.get_grant(p,'grant')['grant']['dispatches_reserved']==0
    assert J.job_get(p,jid)['job']['dispatch_count']==0
    con=S.connect(p)
    try:assert S.get(con,'runs',rid)[0]['attempts_used']==0
    finally:con.close()
    with pytest.raises(InvalidInput,match='stale|cancelled'):permit.consume(job.frozen_request,simulated=True)


def test_grant_revocation_and_wrong_receipt_identity_refuse(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];grant(p,monkeypatch,max_dispatches=1)
    ids,job=uncertain(p,brief,monkeypatch)
    with pytest.raises(InvalidInput,match='different frozen request'):
        R.reconcile(p,ids[1],{**receipt(job,'abandoned'),'request_sha256':'0'*64},'operator-test')
    version=G.get_grant(p,'grant')['version'];G.revoke(p,'grant',version,'operator-test')
    assert not G.get_grant(p,'grant')['grant']['active']
    R.reconcile(p,ids[1],receipt(job,'abandoned'),'operator-test')
    assert J.job_get(p,ids[1])['job']['status']=='failed'
    assert G.get_grant(p,'grant')['grant']['dispatches_reserved']==1


def test_segmentation_receipt_recovers_proposals_atomically_without_another_send(tmp_path,monkeypatch):
    import base64
    from test_v2_r3_providers import _pack_bits,_sam_line
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-never-live')
    grant(p,monkeypatch,models=['sam-3.1']);monkeypatch.setenv('FRAMEBOUND_OPERATOR_SECRET','operator-test')
    rid,jid,claim=queued(p,brief,'sam-receipt',{'provider':'sam','source_asset_id':'f0'})
    def timeout(request):raise TimeoutError('test ambiguous SAM dispatch')
    assert send(p,(rid,jid,claim),timeout)['action']=='needs_attention'
    pending=J.job_get(p,jid)
    raster=bytes(1 if 2<=i%64<6 and 2<=i//64<6 else 0 for i in range(4096))
    text=_sam_line(0,[(0,(2,2,6,6,64,64),(64,64,'~',base64.b85encode(_pack_bits(raster)).decode()))])
    request=receipt(pending,provider_response={'status':'completed','id':'test-sam-receipt','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]})
    result=R.reconcile(p,jid,request,'operator-test')
    assert result['status']=='succeeded' and result['usable']
    assert R.reconcile(p,jid,request,'operator-test')==result
    job=J.job_get(p,jid)['job']
    assert job['attempt_count']==job['dispatch_count']==1
    assert len(job['output_annotation_ids'])==1 and not job['reconciliation_required']


@pytest.mark.parametrize('amount',[float('nan'),float('inf'),-1,0])
def test_animation_settings_reject_invalid_money_before_any_persistence(tmp_path,amount):
    from framebound.v2.services.auto_repair import start_run
    with pytest.raises(InvalidInput,match='money ceiling'):
        start_run(str(tmp_path),'does-not-exist',provider_settings={'max_spend_usd':amount},offline=False)
    assert not (tmp_path/'framebound.sqlite3').exists()
