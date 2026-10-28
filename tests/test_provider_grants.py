import io
import json
from unittest.mock import patch
import pytest
from framebound.v2.services import jobs as J,orchestrator as O,provider_grants as G
from framebound.v2.services.errors import AuthorizationError,InvalidInput
from framebound.v2.providers import base
from framebound.v2 import storage as S
from test_v2_r3_providers import _seed
from test_dispatch_reservations import response,send

def grant(project,monkeypatch,**overrides):
    monkeypatch.setenv('FRAMEBOUND_OPERATOR_SECRET','test-owner')
    fields={'id':'grant','targets':['contract-R3#slot-0'],'models':['muse-image-1.0'],
            'max_dispatches':3,**overrides}
    return G.issue(project,fields,'test-owner')

def queued(project,brief,key,settings=None):
    env=J.submit_generation(project,brief,[],key,provider_settings={'grant_id':'grant',**(settings or {})})
    jid=env.artifacts[0]['id'];rid=O.start_run(project,[jid])['run_id']
    return rid,jid,J.job_claim(project,jid,'worker',expected_version=J.job_get(project,jid)['version'])

def test_only_operator_can_issue_grants_and_replay_keeps_accounting(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    g=grant(p,monkeypatch)
    with pytest.raises(AuthorizationError):G.issue(p,g,'wrong-owner')
    assert send(p,queued(p,brief,'one'),lambda req:response(p))['action']=='succeeded'
    assert grant(p,monkeypatch)['dispatches_reserved']==1

def test_money_reserved_before_io_cannot_exceed_quote_ceiling(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    grant(p,monkeypatch,limit_kind='usd',ceiling_microusd=1500,quote_microusd=1000,
          pricing_reference='test fixture: fixed maximum per response')
    calls=[]
    def fake(req):calls.append(1);return response(p)
    assert send(p,queued(p,brief,'one'),fake)['action']=='succeeded'
    with pytest.raises(InvalidInput,match='money ceiling'):send(p,queued(p,brief,'two'),fake)
    assert calls==[1]
    con=S.connect(p)
    try:assert S.get(con,'provider_grants','grant')[0]['reserved_microusd']==1000
    finally:con.close()

def test_endpoint_and_model_are_frozen_through_the_actual_http_branch(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    grant(p,monkeypatch,max_dispatches=1)
    ids=queued(p,brief,'frozen-http');monkeypatch.setenv('META_BASE_URL','https://must-not-be-used.invalid')
    monkeypatch.setenv('FRAMEBOUND_IMAGE_MODEL','must-not-be-used')
    seen=[]
    def http(req,timeout):
        seen.append((req.full_url,json.loads(req.data)['model']))
        return io.BytesIO(json.dumps(response(p)).encode())
    with patch('urllib.request.urlopen',side_effect=http):
        rid,jid,claim=ids
        assert O.orchestrator_send(p,rid,jid,worker_id='worker',fencing_token=claim['fencing_token'])['action']=='succeeded'
    assert seen==[('https://api.meta.ai/v1/responses','muse-image-1.0')]

def test_low_level_live_bypass_refused_without_permit(tmp_path,monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    with patch('urllib.request.urlopen') as network:
        with pytest.raises(InvalidInput,match='permit'):base.http_post('/responses',{'model':'test'})
    network.assert_not_called()

def test_grant_scope_cannot_be_bypassed_with_new_key_or_settings(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    grant(p,monkeypatch,max_dispatches=1)
    assert send(p,queued(p,brief,'one'),lambda req:response(p))['action']=='succeeded'
    calls=[]
    with pytest.raises(InvalidInput,match='grant dispatch ceiling'):send(p,queued(p,brief,'new-key'),lambda req:calls.append(1))
    assert calls==[]

def test_unpriced_grant_cannot_claim_a_usd_limit(tmp_path,monkeypatch):
    p=str(tmp_path);brief=_seed(p)['brief'];monkeypatch.setenv('MODEL_API_KEY','test-no-network')
    grant(p,monkeypatch);monkeypatch.setenv('FRAMEBOUND_SPEND_CEILING','usd-5')
    with pytest.raises(InvalidInput,match='unpriced'):send(p,queued(p,brief,'unpriced'),lambda req:response(p))
